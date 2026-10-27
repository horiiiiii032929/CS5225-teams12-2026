"""Place and station persistence behind `GET /places` (#14).

`find_places` resolved candidates but wrote nothing, so every preference save
failed with `Place not found or expired.`: `groups.py::_place` reads
`PLACE#<placeId>/META` and the save transaction condition-checks its `ttl`, but
nothing ever created the record they read. This module is that missing write
side. A lookup that cannot be persisted is not a successful lookup, because the
`placeId` it returns cannot be saved.

Three records, with three different lifetimes, all from `docs/api-contract.md`:

- `PLACE#<placeId>/META` is a 24-hour cache of one resolved place. An older
  `placeId` is not valid for a save and must fail honestly rather than invent a
  destination.
- `STATION#<stationKey>/META` is the pinned routing coordinate and carries no
  ttl. It is created conditionally, the first writer wins, and every later
  lookup that snaps to that station reuses the winning coordinate.
- `PLACELOOKUP#<query>/META` is the 24-hour query cache: it maps a normalised
  query to the response it produced, so a repeated query costs no upstream
  calls at all. Without it a repeat of the same query still cost one search
  plus one nearest-station call per candidate — measured at six calls and
  ~800 ms for `kent ridge` on 20 October.

#3 measured why the station coordinate has to be pinned rather than refreshed:
`getNearestMrtStops` returns one entry per line code for an interchange, in a
varying order, with coordinates up to ~100 m apart (Dhoby Ghaut returns CC1,
NS24 and NE6). If a lookup could overwrite the coordinate, one member would
get different commute minutes on different days, and minutes computed from
different origins would accumulate under a single `COMMUTE#<stationKey>` key,
which is E4's primary metric. Aliases may be merged into an existing record;
the coordinate may not change without an explicit cache refresh.

Because the pinned coordinate can be further from the place than the exit this
lookup happened to return, the 1,000 m selection bound is re-measured after
pinning. A candidate that no longer qualifies moves to `unsupported` with
`STATION_TOO_FAR` instead of being offered as selectable.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError

from flatsplit_api.errors import ApiError
from flatsplit_api.onemap import (
    MAX_SNAP_METRES,
    SNAP_WARNING_METRES,
    haversine_metres,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = Logger(child=True)

#: docs/api-contract.md: the Place item expires after 24 hours.
PLACE_TTL_SECONDS = 24 * 60 * 60

#: docs/api-contract.md: "Query/lookup cache entries expire after 24 hours."
LOOKUP_TTL_SECONDS = 24 * 60 * 60

#: Compare-and-swap attempts when merging line-code aliases into a pinned
#: station. Two lookups that resolve the same station concurrently both try to
#: add their own aliases, and a read-modify-write loses one of them (found by
#: @wkkuu on #65 with a controlled Moto interleaving). Three attempts is
#: generous: the window is one round trip, and the merge is retried by the next
#: cold lookup of that station anyway.
ALIAS_MERGE_ATTEMPTS = 3

_TOO_FAR_MESSAGE = "Choose a nearby MRT station or a more precise address."


def _storable(value: Any) -> Any:
    """DynamoDB rejects floats; JSON conversion keeps coordinate precision."""
    return json.loads(json.dumps(value), parse_float=Decimal)


def _plain(value: Any) -> Any:
    """The inverse: `Decimal` back to the JSON numbers the response uses."""
    return json.loads(json.dumps(value, default=float))


def _lookup_key(query: str) -> str:
    """The query cache key.

    Case-folded because OneMap's search is case-insensitive: on 20 October,
    `kent ridge`, `KENT RIDGE`, `Kent Ridge` and `kEnT rIdGe` all returned
    found=80 with byte-identical results. Folding the key turns those four into
    one cache entry instead of four. The handler has already trimmed and
    collapsed whitespace.
    """
    return query.casefold()


def _unavailable(action: str, exc: ClientError) -> ApiError:
    logger.warning(
        "Place persistence failed",
        extra={"action": action, "awsCode": exc.response["Error"]["Code"]},
    )
    return ApiError(
        503,
        "SERVICE_UNAVAILABLE",
        "Destination search is unavailable. Try again shortly.",
    )


class PlaceStore:
    """Writes the records `groups.py` reads when a preference is saved."""

    def __init__(
        self, table: Table, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.table = table
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> int:
        return int(self._clock().astimezone(UTC).timestamp())

    def persist(
        self, found: dict[str, Any], *, query: str | None = None
    ) -> dict[str, Any]:
        """Store every selectable candidate and return the adjusted response.

        With `query`, the resulting response is also cached under that query so
        the next identical lookup needs no upstream call. An empty result is
        cached too: a repeated typo should not keep spending quota.
        """
        places: list[dict[str, Any]] = []
        unsupported: list[dict[str, Any]] = list(found.get("unsupported") or [])
        for candidate in found.get("places") or []:
            station = self._pinned_station(candidate)
            if station["snapMetres"] > MAX_SNAP_METRES:
                # The pinned coordinate is further away than the exit this
                # lookup returned, so this candidate is no longer selectable.
                unsupported.append(
                    {
                        "label": candidate["label"],
                        "address": candidate["address"],
                        "code": "STATION_TOO_FAR",
                        "message": _TOO_FAR_MESSAGE,
                        "snapMetres": station["snapMetres"],
                    }
                )
                continue
            self._write_place(candidate, station)
            places.append(dict(candidate, station=station))
        if query is not None:
            self._write_lookup(query, places, unsupported)
        return {
            "places": places,
            "unsupported": unsupported,
            "ambiguous": len(places) > 1,
        }

    # --------------------------------------------------------- query cache

    def cached(self, query: str) -> dict[str, Any] | None:
        """The stored response for this query, or None if it must be looked up.

        A hit has to reproduce a response whose `placeId`s are all still
        saveable, so every referenced place record is re-read and its own ttl
        checked. An alias that outlives one of its place records is a miss, not
        a partial answer: handing back a `placeId` that `groups.py` will reject
        is the exact defect this module exists to prevent.

        A hit does not extend any ttl. The contract gives these entries 24
        hours, not a sliding window, so a stale upstream result cannot live
        indefinitely by being queried often.
        """
        alias = self._read(f"PLACELOOKUP#{_lookup_key(query)}")
        if alias is None or not self._fresh(alias):
            return None
        places: list[dict[str, Any]] = []
        for place_id in alias.get("placeIds") or []:
            record = self._read(f"PLACE#{place_id}")
            if record is None or not self._fresh(record):
                return None
            places.append(
                {
                    "placeId": str(place_id),
                    "label": str(record["label"]),
                    "address": str(record["address"]),
                    "station": _plain(record["station"]),
                }
            )
        return {
            "places": places,
            "unsupported": _plain(alias.get("unsupported") or []),
            "ambiguous": len(places) > 1,
        }

    def _write_lookup(
        self,
        query: str,
        places: list[dict[str, Any]],
        unsupported: list[dict[str, Any]],
    ) -> None:
        item = _storable(
            {
                "query": query,
                "placeIds": [str(place["placeId"]) for place in places],
                "unsupported": unsupported,
                "refreshedAt": self._clock().astimezone(UTC).isoformat(),
            }
        )
        try:
            self.table.put_item(
                Item=dict(
                    item,
                    pk=f"PLACELOOKUP#{_lookup_key(query)}",
                    sk="META",
                    ttl=self._now() + LOOKUP_TTL_SECONDS,
                )
            )
        except ClientError as exc:
            raise _unavailable("write-lookup", exc) from exc

    # ------------------------------------------------------------- reading

    def _read(self, pk: str) -> dict[str, Any] | None:
        try:
            item: dict[str, Any] | None = self.table.get_item(
                Key={"pk": pk, "sk": "META"}, ConsistentRead=True
            ).get("Item")
        except ClientError as exc:
            raise _unavailable("read-item", exc) from exc
        return item

    def _fresh(self, item: dict[str, Any]) -> bool:
        """Expiry is decided here, never by whether a read came back empty.

        DynamoDB deletes expired items asynchronously and keeps returning them
        until it does, which the contract states for group access and which
        `groups.py` already honours for place records.
        """
        ttl = item.get("ttl")
        return ttl is None or int(ttl) > self._now()

    # ------------------------------------------------------------- stations

    def _pinned_station(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """The station as pinned for this key, re-measured from the place."""
        pinned = self._pin(candidate["station"])
        metres = round(
            haversine_metres(
                candidate["lat"], candidate["lng"], pinned["lat"], pinned["lng"]
            )
        )
        return {
            "stationKey": pinned["stationKey"],
            "codes": pinned["codes"],
            "name": pinned["name"],
            "lat": pinned["lat"],
            "lng": pinned["lng"],
            "snapMetres": metres,
            "snapWarning": metres > SNAP_WARNING_METRES,
        }

    def _pin(self, station: dict[str, Any]) -> dict[str, Any]:
        """Create the station record, or return the winning one unchanged."""
        key = str(station["stationKey"])
        codes = sorted({str(code) for code in station["codes"]})
        candidate = {
            "stationKey": key,
            "codes": codes,
            "name": str(station["name"]),
            "lat": float(station["lat"]),
            "lng": float(station["lng"]),
        }
        item = dict(
            _storable(candidate),
            pk=f"STATION#{key}",
            sk="META",
            pinnedAt=self._clock().astimezone(UTC).isoformat(),
            # Optimistic lock for the alias list only. The coordinate is
            # immutable, so nothing else on this item needs versioning.
            codesRevision=0,
        )
        try:
            self.table.put_item(
                Item=item, ConditionExpression="attribute_not_exists(pk)"
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise _unavailable("pin-station", exc) from exc
            return self._merge_aliases(key, codes)
        return candidate

    def _merge_aliases(self, key: str, codes: list[str]) -> dict[str, Any]:
        """Reuse the pinned record, adding any line codes it does not have yet.

        The addition is a compare-and-swap on `codesRevision`, not a plain
        write. A read-modify-write here loses aliases: two lookups that resolve
        the same station concurrently both read `[CC1]`, one stores
        `[CC1, NS24]` and the other then stores `[CC1, NE6]`, dropping `NS24`
        while both lookups report success. @wkkuu reproduced exactly that on
        #65 with a controlled two-writer interleaving.

        The coordinate was never at risk — it is written once and never
        updated — but a silently shortened alias list is still wrong, and
        `codes` is what the contract calls the upstream aliases of one physical
        station.

        On a conflict the record is re-read and the union recomputed, so the
        loser of a race adds its own codes on top of the winner's. If every
        attempt conflicts the pinned record is returned as it stands: the
        coordinate is correct, aliases are informational, and the next cold
        lookup of this station merges again, so this self-heals rather than
        failing a user's search over a cosmetic field.
        """
        for attempt in range(ALIAS_MERGE_ATTEMPTS):
            existing = self._read(f"STATION#{key}")
            if existing is None:
                # Only reachable if the record were deleted between the two
                # calls. STATION# has no ttl, so this is a signal, not an
                # expected state.
                raise ApiError(
                    503,
                    "SERVICE_UNAVAILABLE",
                    "Destination search is unavailable. Try again shortly.",
                )
            pinned_codes = [str(code) for code in existing.get("codes") or []]
            merged = sorted(set(pinned_codes) | set(codes))
            if merged == pinned_codes:
                return self._station_record(key, pinned_codes, existing)

            revision = existing.get("codesRevision")
            values: dict[str, Any] = {":codes": merged}
            if revision is None:
                # A record written before this field existed.
                condition = (
                    "attribute_exists(pk) AND attribute_not_exists(codesRevision)"
                )
                values[":next"] = 1
            else:
                condition = "attribute_exists(pk) AND codesRevision = :current"
                values[":current"] = int(revision)
                values[":next"] = int(revision) + 1
            try:
                self.table.update_item(
                    Key={"pk": f"STATION#{key}", "sk": "META"},
                    UpdateExpression=("SET codes = :codes, codesRevision = :next"),
                    ConditionExpression=condition,
                    ExpressionAttributeValues=values,
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise _unavailable("merge-aliases", exc) from exc
                logger.info(
                    "Alias merge lost a race; retrying",
                    extra={"stationKey": key, "attempt": attempt + 1},
                )
                continue
            return self._station_record(key, merged, existing)

        logger.warning(
            "Alias merge gave up after repeated conflicts",
            extra={"stationKey": key, "attempts": ALIAS_MERGE_ATTEMPTS},
        )
        latest = self._read(f"STATION#{key}")
        if latest is None:
            raise ApiError(
                503,
                "SERVICE_UNAVAILABLE",
                "Destination search is unavailable. Try again shortly.",
            )
        return self._station_record(
            key, [str(code) for code in latest.get("codes") or []], latest
        )

    @staticmethod
    def _station_record(
        key: str, codes: list[str], item: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "stationKey": key,
            "codes": codes,
            "name": str(item["name"]),
            # The coordinate comes from the winning record, never from this
            # lookup. This is the whole point of the pin.
            "lat": float(item["lat"]),
            "lng": float(item["lng"]),
        }

    # ---------------------------------------------------------------- places

    def _write_place(self, candidate: dict[str, Any], station: dict[str, Any]) -> None:
        item = _storable(
            {
                "label": candidate["label"],
                "address": candidate["address"],
                "lat": float(candidate["lat"]),
                "lng": float(candidate["lng"]),
                "station": station,
            }
        )
        try:
            self.table.put_item(
                Item=dict(
                    item,
                    pk=f"PLACE#{candidate['placeId']}",
                    sk="META",
                    ttl=self._now() + PLACE_TTL_SECONDS,
                )
            )
        except ClientError as exc:
            raise _unavailable("write-place", exc) from exc
