"""Serve the real Lambda resolver over HTTP on this machine, with Moto as AWS.

`acceptance.py` is meant to run against a deployed API, but deployment access
is not available to every contributor and #43/#44 have been blocked on
`real-table/dev acceptance remains` for days. Without this harness the
acceptance script would first execute on deployment day, which is the worst
possible moment to debug it, because the deployment is being debugged at the
same time.

So this starts a "fake AWS, real code" environment: the ASGI app in
`services/api/src/flatsplit_api/local.py` translates requests into API Gateway
v2 events and hands them to the same resolver in `handlers/http.py` that runs
in Lambda. Only DynamoDB and SQS are replaced, by Moto, inside this process.

    python3 tools/acceptance/serve_local.py

Then, in another terminal:

    python3 tools/acceptance/acceptance.py

This is local verification, not a deployment. Moto creates no AWS resource and
costs nothing, and it cannot be used to claim deployed acceptance: real table
contention, IAM and cold starts are not exercised here. The evidence file from
`acceptance.py` records `mode` as `local-moto` or `deployed` so the two are
never confused.

Needs the `dev` dependency group (Moto) and the API's `local` extra (uvicorn):

    uv sync --locked --all-packages --group dev
    uv run --package flatsplit-api --extra local \
        python tools/acceptance/serve_local.py
"""

import argparse
import os
import sys
from decimal import Decimal
from typing import Any

#: Synthetic rental summaries. #10 (publishing real summaries) does not exist
#: yet and `POST /searches` returns 503 without a `RENT/CURRENT` pointer, so a
#: full local journey has to seed its own. The magnitudes come from
#: `docs/hdb-rental-data-profile.md`, but these are made-up numbers: every item
#: is tagged `syntheticLocalFixture` and must never be read as real rent.
SYNTHETIC_RENT = {
    "ANG MO KIO": {
        "3-ROOM": (2500, 2300, 2800, 180),
        "4-ROOM": (3000, 2800, 3300, 210),
    },
    "TAMPINES": {"3-ROOM": (2600, 2400, 2850, 240), "4-ROOM": (3100, 2900, 3400, 260)},
    "JURONG WEST": {
        "3-ROOM": (2450, 2250, 2700, 220),
        "4-ROOM": (2900, 2700, 3150, 230),
    },
    "BEDOK": {"3-ROOM": (2550, 2350, 2800, 200), "4-ROOM": (3050, 2850, 3300, 190)},
    "WOODLANDS": {"3-ROOM": (2400, 2200, 2650, 210), "4-ROOM": (2850, 2650, 3100, 220)},
}
SYNTHETIC_SNAPSHOT = "synthetic-local-v1"
SYNTHETIC_PERIOD = "2025-10/2026-09"

DEFAULT_TABLE = "flatsplit-local"
DEFAULT_QUEUE = "flatsplit-commute-local"
DEFAULT_PORT = 8000
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def seed_rent(table: Any) -> None:
    """Seed `RENT/CURRENT` and one summary per town so `POST /searches` runs.

    `search_data.py` validates these records: five positive amounts,
    `p25 <= median <= p75`, a positive integer `count`, and a `qualityStatus`
    of `USABLE` or `LOW_CONFIDENCE`. This seeds the smallest set it accepts, so
    if that validation gets stricter the harness breaks loudly instead of
    quietly passing.
    """
    table.put_item(
        Item={
            "pk": "RENT",
            "sk": "CURRENT",
            "schemaVersion": 1,
            "snapshotId": SYNTHETIC_SNAPSHOT,
            "period": SYNTHETIC_PERIOD,
            "sourceMonthTo": SYNTHETIC_PERIOD.split("/")[1],
            "validatedAt": "2026-10-20T00:00:00Z",
            "syntheticLocalFixture": True,
        }
    )
    rows = 0
    for town, by_type in SYNTHETIC_RENT.items():
        for flat_type, (median, p25, p75, half_width) in by_type.items():
            table.put_item(
                Item={
                    "pk": f"RENT#{SYNTHETIC_SNAPSHOT}",
                    "sk": f"TOWN#{town}#{flat_type}",
                    "schemaVersion": 1,
                    "town": town,
                    "flatType": flat_type,
                    "currency": "SGD",
                    "unit": "month",
                    "statistic": "median",
                    "period": SYNTHETIC_PERIOD,
                    "median": Decimal(str(median)),
                    "p25": Decimal(str(p25)),
                    "p75": Decimal(str(p75)),
                    "medianCi95Low": Decimal(str(median - half_width)),
                    "medianCi95High": Decimal(str(median + half_width)),
                    "count": 120,
                    "blockCount": 40,
                    "qualityStatus": "USABLE",
                    "syntheticLocalFixture": True,
                }
            )
            rows += 1
    print(
        f"[seed] {rows} synthetic rent rows ({len(SYNTHETIC_RENT)} towns) "
        f"snapshot={SYNTHETIC_SNAPSHOT} - SYNTHETIC, not real rent"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=REPO_ROOT, help="repository root")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--onemap-token",
        default=None,
        help="OneMap token; defaults to the ONEMAP_TOKEN environment variable",
    )
    parser.add_argument(
        "--no-seed-rent",
        action="store_true",
        help="skip the synthetic rent seed (searches then 503, because #10 is open)",
    )
    args = parser.parse_args()

    src = os.path.join(os.path.abspath(args.repo), "services", "api", "src")
    if not os.path.isdir(src):
        sys.exit(f"{src} not found; pass --repo <repository root>")
    sys.path.insert(0, src)

    token = args.onemap_token or os.environ.get("ONEMAP_TOKEN", "").strip()
    if token:
        os.environ["ONEMAP_TOKEN"] = token
        print("[token] loaded; /places will call live OneMap and spend quota")
    else:
        print("[token] no ONEMAP_TOKEN; /places returns 503, other routes still work")

    os.environ["TABLE_NAME"] = DEFAULT_TABLE
    os.environ["AWS_DEFAULT_REGION"] = "ap-southeast-1"
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("POWERTOOLS_SERVICE_NAME", "flatsplit-local")
    os.environ.setdefault("POWERTOOLS_LOG_LEVEL", "WARNING")

    import boto3
    import uvicorn
    from moto import mock_aws

    # Moto patches botocore process-wide, so the context has to be entered
    # before the app is imported, and uvicorn has to stay in this process
    # (no --reload, no workers).
    with mock_aws():
        boto3.resource("dynamodb").create_table(
            TableName=DEFAULT_TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        queue = boto3.client("sqs").create_queue(QueueName=DEFAULT_QUEUE)
        os.environ["COMMUTE_QUEUE_URL"] = queue["QueueUrl"]
        print(f"[moto] table={DEFAULT_TABLE}  queue={DEFAULT_QUEUE}")

        if not args.no_seed_rent:
            seed_rent(boto3.resource("dynamodb").Table(DEFAULT_TABLE))

        from flatsplit_api.local import app

        # Deliberately no SQS depth watcher here: Moto's queue state only
        # exists in this process, and a thread reporting it said 0 while the
        # API's own progress reported 50 pairs still waiting. A diagnostic that
        # lies is worse than none. `acceptance.py` derives the waiting count
        # from the API's progress (`total - resolved - unavailable`), which
        # also holds after deployment.
        print(f"[serve] http://127.0.0.1:{args.port}  (docs: /docs)")
        print("[serve] in another terminal: python3 tools/acceptance/acceptance.py")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
