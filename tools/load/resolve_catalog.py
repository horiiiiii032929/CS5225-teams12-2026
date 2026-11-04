#!/usr/bin/env python3
"""Resolve the reviewed destinations on one target into a load catalog.

Usage: resolve_catalog.py --base-url URL --target LABEL --reviewer NAME
       --revision REV [--destinations PATH] --output PATH

`destinations.json` pins each destination's reviewed label, address and
station. Exactly one `/places` candidate must match all three, or the script
stops without writing: a changed or ambiguous selection needs a person, not a
guess. The catalog's `place_ids` are target-local.

Place IDs expire 24 hours after the lookup that created them, and a cached
lookup returns the same IDs without extending them (`places.py`). Resolve only
on a target with no earlier lookup of these queries, such as a fresh stack or
24 hours after the previous resolution, then finish setup and measurement
before the deadline this prints.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
#: One hour short of the 24-hour place expiry, for setup still in flight.
VALID_HOURS = 23
SGT = timezone(timedelta(hours=8))

Lookup = Callable[[str], list[dict[str, Any]]]


class SelectionError(Exception):
    """A destination no longer selects exactly one reviewed candidate."""


def select(destination: dict[str, Any], places: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        place
        for place in places
        if place.get("label") == destination["label"]
        and place.get("address") == destination["address"]
        and (place.get("station") or {}).get("stationKey") == destination["stationKey"]
    ]
    if len(matches) != 1:
        raise SelectionError(
            f"{destination['alias']}: {len(matches)} candidates match the reviewed "
            "label, address and station."
        )
    return matches[0]


def build_catalog(
    reviewed: dict[str, Any],
    lookup: Lookup,
    *,
    target: str,
    reviewer: str,
    revision: str,
    pause: float = 1.0,
) -> dict[str, Any]:
    destinations = []
    for destination in reviewed["destinations"]:
        place = select(destination, lookup(destination["query"]))
        station = place["station"]
        destinations.append(
            {
                "alias": destination["alias"],
                "weight": destination["weight"],
                "selection_receipt": destination["receipt"],
                "station": {
                    "stationKey": station["stationKey"],
                    "lat": station["lat"],
                    "lng": station["lng"],
                },
                "place_ids": {target: place["placeId"]},
            }
        )
        time.sleep(pause)
    return {
        "version": 1,
        "kind": "reviewed-public",
        "review": {
            "reviewer": reviewer,
            "revision": revision,
            "weight_basis": reviewed["weight_basis"],
        },
        "destinations": destinations,
    }


def http_lookup(base_url: str) -> Lookup:
    base = base_url.rstrip("/")

    def lookup(query: str) -> list[dict[str, Any]]:
        url = f"{base}/places?" + urllib.parse.urlencode({"q": query})
        with urllib.request.urlopen(url, timeout=25) as response:
            places: list[dict[str, Any]] = json.loads(response.read())["places"]
        return places

    return lookup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="API base, ending in /api")
    parser.add_argument("--target", required=True, help="place_ids label, e.g. eval")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--destinations", type=Path, default=HERE / "destinations.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"{args.output} exists; use a fresh path for each resolution")
    started = datetime.now(UTC)
    try:
        catalog = build_catalog(
            json.loads(args.destinations.read_text()),
            http_lookup(args.base_url),
            target=args.target,
            reviewer=args.reviewer,
            revision=args.revision,
        )
    except SelectionError as exc:
        print(f"{exc} Review destinations.json; nothing was written.", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(catalog, indent=1) + "\n")
    deadline = (started + timedelta(hours=VALID_HOURS)).astimezone(SGT)
    print(
        f"Resolved {len(catalog['destinations'])} destinations into {args.output}. "
        f"Finish setup and measurement before {deadline:%d %b %H:%M} SGT, unless any "
        "query had been looked up on this target in the previous 24 hours.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
