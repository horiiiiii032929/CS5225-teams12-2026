"""OneMap integration behind `GET /places` (#14).

This follows the live measurements recorded in #3 rather than OneMap's
documentation, because the two disagree in ways that change the code:

- One lookup costs **two** calls: text search, then nearest-station snapping.
  Quota planning has to assume double the obvious number.
- `/common/elastic/search` is in a grace period. A missing, invalid or expired
  token still returns HTTP 200 with full results and sets only an `error`
  field, so a successful response does not prove the token is healthy. That
  field is surfaced as a token warning instead of being ignored.
- A 429 body is JSON when a token is sent and HTML when it is not, and no
  observed 429 carried a `Retry-After` header. Bodies are therefore never
  parsed blindly and the backoff schedule is ours.
- 403 is the WAF and also returns HTML.

The reconciled #6 baseline uses canonical physical-station keys, explicit
unsupported results and a 1,000 m selection bound. This module stays
transport-only: persistence of the place record and the pinned station
coordinate lives in `places.py`, which the HTTP layer applies to this result.
"""

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from aws_lambda_powertools import Logger

logger = Logger(child=True)
_secret_provider: Any = None

BASE_URL = "https://www.onemap.gov.sg"
SEARCH_PATH = "/api/common/elastic/search"
NEAREST_PATH = "/api/public/nearbysvc/getNearestMrtStops"

TIMEOUT_SECONDS = 4.0
#: OneMap caps this at 5000 m (SLA workshop, slide 16).
SNAP_RADIUS_METRES = 2000
MAX_SNAP_METRES = 1000
SNAP_WARNING_METRES = 800
LOOKUP_BUDGET_SECONDS = 8.0
#: The contract returns at most five candidates and never auto-picks one.
MAX_RESULTS = 5

_STATION_SUFFIX = re.compile(r"\s+MRT\s+STATION\b.*$", re.IGNORECASE)
_PARENTHESISED = re.compile(r"\s*\([^)]*\)")
_WHITESPACE = re.compile(r"\s+")
_EARTH_RADIUS_METRES = 6371000.0


class OneMapError(Exception):
    """An upstream failure that `/places` turns into 429 or 503."""


class OneMapRateLimited(OneMapError):
    """OneMap throttled us. #3 found no `Retry-After` on any 429."""


class OneMapUnavailable(OneMapError):
    """Any other upstream or transport failure."""


class Transport(Protocol):
    """Seam for tests: one GET against OneMap, returning decoded JSON."""

    def __call__(self, path: str, params: dict[str, Any]) -> Any: ...


def normalise_query(raw: str) -> str:
    """Trim and collapse whitespace. Case is preserved for display."""
    return _WHITESPACE.sub(" ", raw.strip())


def haversine_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_METRES * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def resolve_token() -> str:
    """`ONEMAP_TOKEN` for local development, else Secrets Manager.

    The token never reaches the browser: `/places` is a server-side proxy
    (docs/backend-design.md). It is a three-day JWT with no automatic renewal,
    so the secret has to be rotated by hand until a refresh path exists.
    """
    inline = os.environ.get("ONEMAP_TOKEN", "").strip()
    if inline:
        return inline

    secret_name = os.environ.get("ONEMAP_SECRET_NAME", "").strip()
    if not secret_name:
        raise OneMapUnavailable("No OneMap credential is configured.")

    # Keep provider initialization lazy so inline local tokens need no AWS client.
    global _secret_provider
    try:
        from aws_lambda_powertools.utilities import parameters
        from botocore.config import Config

        if _secret_provider is None:
            _secret_provider = parameters.SecretsProvider(
                boto_config=Config(
                    connect_timeout=1,
                    read_timeout=1,
                    retries={"total_max_attempts": 1},
                )
            )
        secret = _secret_provider.get(secret_name, max_age=900)
    except Exception as exc:
        # Local missing SDKs, access denial and secret-read failures use the
        # public upstream error; never expose credentials or provider details.
        raise OneMapUnavailable("The OneMap credential could not be loaded.") from exc
    if isinstance(secret, bytes):
        secret = secret.decode("utf-8")
    if not isinstance(secret, str) or not secret.strip():
        raise OneMapUnavailable("The OneMap secret is empty.")
    return secret.strip()


def _decode(raw: bytes) -> Any:
    """Parse JSON defensively: 429 and 403 bodies are sometimes HTML (#3)."""
    text = raw.decode("utf-8", "replace").lstrip()
    if not text.startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _message_from(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("error", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return fallback


def http_get(
    path: str, params: dict[str, Any], *, timeout: float = TIMEOUT_SECONDS
) -> Any:
    """Single GET against OneMap. No retry: `/places` is a user-facing read."""
    started = time.monotonic()
    token = resolve_token()
    timeout -= time.monotonic() - started
    if timeout <= 0:
        raise OneMapUnavailable("Credential loading exceeded the request budget.")
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"Authorization": token, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _decode(response.read())
    except urllib.error.HTTPError as exc:
        payload = _decode(exc.read())
        message = _message_from(payload, f"OneMap returned HTTP {exc.code}.")
        if exc.code == 429:
            raise OneMapRateLimited(message) from exc
        raise OneMapUnavailable(message) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OneMapUnavailable(f"OneMap is unreachable: {exc}") from exc


def _place_id(result: dict[str, Any]) -> str:
    """Deterministic id for a OneMap hit.

    The contract's example (`pl_nus_kent_ridge`) is readable but cannot be
    reproduced from OneMap's payload, so the id is a stable digest of the
    fields that identify a hit. Worth settling in #6 if the readable form is
    wanted in the response.
    """
    seed = "|".join(
        str(result.get(key, ""))
        for key in ("SEARCHVAL", "POSTAL", "LATITUDE", "LONGITUDE")
    )
    return "pl_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _address_of(result: dict[str, Any]) -> str:
    address = str(result.get("ADDRESS", "")).strip()
    if address:
        return address
    parts = [
        str(result.get("BLK_NO", "")).strip(),
        str(result.get("ROAD_NAME", "")).strip(),
    ]
    street = " ".join(part for part in parts if part)
    postal = str(result.get("POSTAL", "")).strip()
    if street and postal and postal.upper() != "NIL":
        return f"{street}, Singapore {postal}"
    return street or str(result.get("SEARCHVAL", "")).strip()


def station_display_name(raw_name: str) -> str:
    """`KENT RIDGE MRT STATION (CC24)` becomes `Kent Ridge`."""
    without_codes = _PARENTHESISED.sub("", raw_name)
    stem = _STATION_SUFFIX.sub("", without_codes).strip()
    return stem.title() or raw_name.strip()


def canonical_station_key(name: str) -> str:
    stem = _STATION_SUFFIX.sub("", _PARENTHESISED.sub("", name.upper()))
    return re.sub(r"[^A-Z0-9]+", "_", stem).strip("_")


def _station_codes(entry: dict[str, Any]) -> list[str]:
    raw = str(entry.get("id", "")).strip().upper()
    # Jurong East's raw id is literally the string "EW24 / NS1" (#3).
    return [part.strip() for part in raw.split("/") if part.strip()]


def _coordinate(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def find_places(query: str, transport: Transport | None = None) -> dict[str, Any]:
    """Up to five candidates for a free-text query, each snapped to a station.

    Candidates are returned in OneMap's relevance order and never collapsed to
    one. #3 showed why: taking the first hit silently selected PASIR RIS EAST,
    PUNGGOL COAST and TAMPINES EAST instead of the intended stations, so
    choosing between similar hits belongs to the person, not the server.
    """
    deadline = time.monotonic() + LOOKUP_BUDGET_SECONDS

    def get(path: str, params: dict[str, Any]) -> Any:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OneMapUnavailable("Destination lookup exceeded its request budget.")
        if transport is not None:
            return transport(path, params)
        return http_get(path, params, timeout=min(TIMEOUT_SECONDS, remaining))

    payload = get(
        SEARCH_PATH,
        {
            "searchVal": query,
            "returnGeom": "Y",
            "getAddrDetails": "Y",
            "pageNum": 1,
        },
    )
    if not isinstance(payload, dict):
        raise OneMapUnavailable("OneMap search returned an unreadable body.")

    warning = payload.get("error")
    if isinstance(warning, str) and warning:
        # Grace period: results still arrive, so this is the only signal that
        # the token is unhealthy. #27 wires it to a CloudWatch alarm.
        logger.warning("OneMap token warning", extra={"onemapTokenWarning": True})

    results = payload.get("results")
    if not isinstance(results, list):
        raise OneMapUnavailable("OneMap search returned malformed candidates.")

    places: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        if len(places) + len(unsupported) >= MAX_RESULTS:
            break
        if not isinstance(result, dict):
            continue
        lat = _coordinate(result.get("LATITUDE"))
        lon = _coordinate(result.get("LONGITUDE"))
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
            raise OneMapUnavailable("OneMap returned invalid place coordinates.")

        candidate_id = _place_id(result)
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        station = nearest_station(lat, lon, get)
        if station is None or station["snapMetres"] > MAX_SNAP_METRES:
            unsupported.append(
                {
                    "label": str(result.get("SEARCHVAL", "")).strip(),
                    "address": _address_of(result),
                    "code": "NO_STATION" if station is None else "STATION_TOO_FAR",
                    "message": "Choose a nearby MRT station or a more precise address.",
                    "snapMetres": None
                    if station is None
                    else round(station["snapMetres"]),
                }
            )
            continue
        station["snapMetres"] = round(station["snapMetres"])
        places.append(
            {
                "placeId": candidate_id,
                "label": str(result.get("SEARCHVAL", "")).strip(),
                "address": _address_of(result),
                # The contract response has no place coordinate, but #14 stores
                # it and re-measures the snap against the pinned station
                # coordinate. PlacesResponse ignores these two extra keys.
                "lat": lat,
                "lng": lon,
                "station": station,
            }
        )
    return {"places": places, "unsupported": unsupported, "ambiguous": len(places) > 1}


def nearest_station(lat: float, lon: float, get: Transport) -> dict[str, Any] | None:
    """Closest MRT station to a coordinate, with the straight-line walk."""
    payload = get(
        NEAREST_PATH,
        {
            "latitude": lat,
            "longitude": lon,
            "radius_in_meters": SNAP_RADIUS_METRES,
        },
    )
    if not isinstance(payload, list):
        raise OneMapUnavailable("OneMap station search returned a malformed body.")
    entries = payload

    best: dict[str, Any] | None = None
    best_distance = float("inf")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        station_lat = _coordinate(entry.get("lat") or entry.get("latitude"))
        station_lon = _coordinate(entry.get("lon") or entry.get("longitude"))
        name = str(entry.get("name", "")).strip()
        if (
            station_lat is None
            or station_lon is None
            or not name
            or abs(station_lat) > 90
            or abs(station_lon) > 180
        ):
            continue
        distance = haversine_metres(lat, lon, station_lat, station_lon)
        if distance >= best_distance:
            continue
        codes = _station_codes(entry)
        best_distance = distance
        best = {
            "stationKey": canonical_station_key(name),
            "codes": codes,
            "lat": station_lat,
            "lng": station_lon,
            "name": station_display_name(name),
            "snapMetres": distance,
            "snapWarning": distance > SNAP_WARNING_METRES,
        }
    if best is not None:
        # Merge interchange aliases without treating each line as a station.
        aliases = {
            code
            for entry in entries
            if isinstance(entry, dict)
            and canonical_station_key(str(entry.get("name", ""))) == best["stationKey"]
            for code in _station_codes(entry)
        }
        best["codes"] = sorted(aliases)
        # Preserve the exact distance for the hard-bound decision. Response models
        # receive rounded metres only after the candidate has passed that decision.
    return best
