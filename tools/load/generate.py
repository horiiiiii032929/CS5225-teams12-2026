#!/usr/bin/env python3
"""Generate offline, deterministic open-arrival W1/W2 plans; never contact a service."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import struct
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
PLACE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
STATION = re.compile(r"[A-Z0-9_]+\Z")
PLAN_KEYS = {
    "version",
    "workload",
    "seed",
    "scale",
    "standard",
    "vus",
    "duration_ms",
    "trace_sha256",
    "catalog_sha256",
    "catalog",
    "arrivals",
}


class ValidationError(ValueError):
    """A static field name, never an input value, is safe to report."""


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValidationError("arguments")


def require(condition, field):
    if not condition:
        raise ValidationError(field)


def exact(value, keys, field):
    require(isinstance(value, dict) and set(value) == set(keys), field)


def number(value, field, *, positive=False):
    require(type(value) in (int, float), field)
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    require(finite and (not positive or value > 0), field)
    return value


def integer(value, field, *, minimum=None):
    require(type(value) is int and (minimum is None or value >= minimum), field)
    return value


def text(value, field, *, limit=1024):
    require(
        isinstance(value, str) and 0 < len(value) <= limit and value.strip() == value,
        field,
    )
    require(
        all(ord(char) >= 32 and not 0xD800 <= ord(char) <= 0xDFFF for char in value),
        field,
    )
    return value


def alias(value, field):
    require(isinstance(value, str) and ALIAS.fullmatch(value) is not None, field)
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "json.keys")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValidationError("json.number")


def parse_json(source):
    try:
        return json.loads(
            source, object_pairs_hook=_pairs, parse_constant=_reject_constant
        )
    except (ValueError, RecursionError, OverflowError) as error:
        raise ValidationError("json") from error


def load_json(path):
    return parse_json(Path(path).read_text(encoding="utf-8"))


def canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def hash_projection(value):
    """Hash numbers as big-endian float64 hex, independent of JSON number spelling."""
    if type(value) in (int, float):
        number(value, "json.number")
        return struct.pack(">d", 0.0 if value == 0 else float(value)).hex()
    if isinstance(value, list):
        return [hash_projection(item) for item in value]
    if isinstance(value, dict):
        return {key: hash_projection(item) for key, item in value.items()}
    return value


def digest(value):
    return hashlib.sha256(
        canonical_json(hash_projection(value)).encode("utf-8")
    ).hexdigest()


def validate_public_receipt(receipt):
    try:
        url = urlsplit(receipt)
        host = (url.hostname or "").rstrip(".")
        require(
            url.scheme == "https"
            and bool(host)
            and url.username is None
            and url.password is None
            and "@" not in url.netloc,
            "catalog.selection_receipt",
        )
        require(
            not any(char.isspace() for char in receipt)
            and not any(char in receipt for char in ("?", "#", "\\")),
            "catalog.selection_receipt",
        )
        require(url.port is None or 1 <= url.port <= 65535, "catalog.selection_receipt")
        require(host.isascii() and "%" not in host, "catalog.selection_receipt")
        labels = host.split(".")
        require(
            len(labels) >= 2 and len(host) <= 253 and not labels[-1].isdigit(),
            "catalog.selection_receipt",
        )
        require(
            all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                is not None
                for label in labels
            ),
            "catalog.selection_receipt",
        )
        require(
            not host.endswith(
                (".local", ".internal", ".localhost", ".invalid", ".test")
            ),
            "catalog.selection_receipt",
        )
    except (ValueError, TypeError) as error:
        raise ValidationError("catalog.selection_receipt") from error


def validate_catalog(catalog):
    exact(catalog, {"version", "kind", "review", "destinations"}, "catalog")
    require(
        type(catalog["version"]) is int and catalog["version"] == 1, "catalog.version"
    )
    require(catalog["kind"] in ("synthetic-local", "reviewed-public"), "catalog.kind")
    exact(catalog["review"], {"reviewer", "revision", "weight_basis"}, "catalog.review")
    for value in catalog["review"].values():
        text(value, "catalog.review")
    destinations = catalog["destinations"]
    require(
        isinstance(destinations, list) and len(destinations) > 0, "catalog.destinations"
    )
    if catalog["kind"] == "reviewed-public":
        require(len(destinations) == 30, "catalog.destinations")
    aliases, receipts = set(), set()
    for destination in destinations:
        exact(
            destination,
            {"alias", "weight", "selection_receipt", "station", "place_ids"},
            "catalog.destination",
        )
        name = alias(destination["alias"], "catalog.alias")
        require(name not in aliases, "catalog.alias")
        aliases.add(name)
        number(destination["weight"], "catalog.weight", positive=True)
        receipt = text(
            destination["selection_receipt"], "catalog.selection_receipt", limit=2048
        )
        require(receipt not in receipts, "catalog.selection_receipt")
        receipts.add(receipt)
        if catalog["kind"] == "synthetic-local":
            require(receipt == "synthetic://" + name, "catalog.selection_receipt")
        else:
            validate_public_receipt(receipt)
        station = destination["station"]
        exact(station, {"stationKey", "lat", "lng"}, "catalog.station")
        require(
            isinstance(station["stationKey"], str)
            and STATION.fullmatch(station["stationKey"]) is not None,
            "catalog.stationKey",
        )
        require(-90 <= number(station["lat"], "catalog.lat") <= 90, "catalog.lat")
        require(-180 <= number(station["lng"], "catalog.lng") <= 180, "catalog.lng")
        places = destination["place_ids"]
        require(isinstance(places, dict) and len(places) > 0, "catalog.place_ids")
        for target, place in places.items():
            alias(target, "catalog.target")
            require(
                isinstance(place, str) and PLACE_ID.fullmatch(place) is not None,
                "catalog.place_id",
            )
    number(
        sum(entry["weight"] for entry in destinations), "catalog.weight", positive=True
    )
    return catalog


def build_plan(workload, seed=522530, vus=16, scale=1, catalog=None):
    require(workload in ("W1", "W2"), "workload")
    integer(seed, "seed")
    require(abs(seed) <= 2**53 - 1, "seed")
    integer(vus, "vus", minimum=1)
    require(vus <= 2**31 - 1, "vus")
    number(scale, "scale", positive=True)
    require(math.isfinite(600000 * scale), "scale")
    if catalog is not None:
        validate_catalog(catalog)
    total = (
        math.floor(1200 * scale)
        if workload == "W1"
        else math.floor(16530 * scale / 10) * 10
    )
    require(total > 0, "scale.arrivals")
    duration = (600000 if workload == "W1" else 360000) * scale
    operations = random.Random(seed)
    destinations = random.Random(str(seed) + ":destinations")
    block = [
        "create",
        "join",
        "join",
        "save",
        "save",
        "save",
        "save",
        "read",
        "read",
        "read",
    ]
    choices = catalog["destinations"] if catalog is not None else []
    maximum_weight = max((entry["weight"] for entry in choices), default=1)
    weights = [entry["weight"] / maximum_weight for entry in choices]
    arrivals = []
    for ordinal in range(total):
        midpoint = ordinal + 0.5
        if workload == "W1":
            at_seconds, phase, op = midpoint / 2, "steady", "read"
        else:
            if ordinal % 10 == 0:
                shuffled = block.copy()
                operations.shuffle(shuffled)
            op = shuffled[ordinal % 10]
            ramp_mass = 1530 * scale
            if midpoint < ramp_mass:
                slope = 49 / (60 * scale)
                at_seconds = 2 * midpoint / (1 + math.sqrt(1 + 2 * slope * midpoint))
                phase = "ramp"
            else:
                at_seconds = 60 * scale + (midpoint - ramp_mass) / 50
                phase = "hold"
        at_ms = round(at_seconds * 1000, 9)
        require(
            0 <= at_ms < duration and (not arrivals or at_ms > arrivals[-1]["at_ms"]),
            "scale.arrivals",
        )
        destination = (
            destinations.choices(choices, weights=weights, k=1)[0]["alias"]
            if choices
            else None
        )
        arrivals.append(
            {
                "ordinal": ordinal,
                "at_ms": at_ms,
                "phase": phase,
                "op": op,
                "destination": destination,
            }
        )
    return {
        "version": 1,
        "workload": workload,
        "seed": seed,
        "scale": scale,
        "standard": scale == 1,
        "vus": vus,
        "duration_ms": duration,
        "trace_sha256": digest(arrivals),
        "catalog_sha256": digest(catalog) if catalog is not None else None,
        "catalog": catalog,
        "arrivals": arrivals,
    }


def validate_plan(plan):
    exact(plan, PLAN_KEYS, "plan")
    require(type(plan["version"]) is int and plan["version"] == 1, "plan.version")
    require(type(plan["standard"]) is bool, "plan.standard")
    expected = build_plan(
        plan["workload"], plan["seed"], plan["vus"], plan["scale"], plan["catalog"]
    )
    require(canonical_json(plan) == canonical_json(expected), "plan.trace")
    return plan


def write_json_atomic(path, value, *, protected=()):
    path = Path(path)
    require(
        all(
            path.resolve() != Path(item).resolve()
            for item in protected
            if item is not None
        ),
        "output.path",
    )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".load-",
            suffix=".json",
            delete=False,
        ) as output:
            temporary = output.name
            output.write(canonical_json(value) + "\n")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)


def main(argv=None):
    try:
        parser = SafeArgumentParser(description=__doc__)
        parser.add_argument("--workload", required=True)
        parser.add_argument("--seed", type=int, default=522530)
        parser.add_argument("--vus", type=int, default=16)
        parser.add_argument("--scale", type=float, default=1)
        parser.add_argument("--catalog", type=Path)
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args(argv)
        catalog = load_json(args.catalog) if args.catalog is not None else None
        plan = build_plan(args.workload, args.seed, args.vus, args.scale, catalog)
        write_json_atomic(args.output, plan, protected=(args.catalog,))
        return 0
    except ValidationError as error:
        print("load generator: invalid " + str(error), file=sys.stderr)
        return 2
    except (
        OSError,
        UnicodeError,
        ValueError,
        OverflowError,
        RecursionError,
        TypeError,
    ):
        print("load generator: invalid input or output", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
