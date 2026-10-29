"""Synthetic HTTP/Moto stack for local UI QA only; never real AWS or OneMap.

Run from the repository root with uv run --package flatsplit-api --extra local
python tools/qa/local_stack.py. Routes and persistence use the real resolver;
only lookup inputs and pending commute completions are synthetic. No production
routes, files, credentials or AWS resources are modified.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import threading
import time
from decimal import Decimal
from pathlib import Path

import boto3
import uvicorn
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/api/tests/e2e"))
import conftest as fixtures  # noqa: E402

import flatsplit_api.handlers.http as http  # noqa: E402
from flatsplit_api.commute_jobs import CommuteJobs  # noqa: E402
from flatsplit_api.groups import GroupStore  # noqa: E402
from flatsplit_api.models import Place  # noqa: E402
from flatsplit_api.places import PlaceStore  # noqa: E402
from flatsplit_api.search_data import SearchDataReader  # noqa: E402
from flatsplit_api.searches import SearchStore  # noqa: E402


def main() -> None:
    # Keep the existing profile name, including the managed no-identity guard.
    # This temporary region-only config contains no credentials. Moto supplies
    # its own dummy credentials inside the mock; no real provider is contacted.
    profile = os.environ.get("AWS_PROFILE", "default")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", profile):
        raise SystemExit("Unsupported local QA profile name")
    with tempfile.TemporaryDirectory(prefix="flatsplit-qa-") as scratch:
        config = Path(scratch) / "config"
        section = "default" if profile == "default" else f"profile {profile}"
        config.write_text(f"[{section}]\nregion = ap-southeast-1\n")
        os.environ["AWS_CONFIG_FILE"] = str(config)
        with mock_aws():
            table = boto3.resource(
                "dynamodb", region_name="ap-southeast-1"
            ).create_table(
                TableName="flatsplit-synthetic-ui-qa",
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
            fixtures._seed_rent(table)
            fixtures._seed_place(table)
            groups = GroupStore(table)
            jobs: list[dict] = []
            searches = SearchStore(
                table, groups, SearchDataReader(table), CommuteJobs(table, jobs.append)
            )
            http.group_store = lambda: groups
            http.search_store = lambda _groups: searches
            http.place_store = lambda: PlaceStore(table)
            record = table.get_item(
                Key={"pk": f"PLACE#{fixtures.SEEDED_PLACE}", "sk": "META"}
            )["Item"]
            place = Place(
                **{key: record[key] for key in ("label", "address", "station")},
                placeId=fixtures.SEEDED_PLACE,
            )
            http.find_places = lambda _query: {
                "places": [
                    dict(
                        place.model_dump(), lat=place.station.lat, lng=place.station.lng
                    )
                ],
                "unsupported": [],
                "ambiguous": False,
            }

            def complete() -> None:
                while True:
                    # Leave pending visible for a deterministic async demo.
                    time.sleep(3)
                    while jobs:
                        job = jobs.pop(0)
                        try:
                            update = "SET #status = :ok, minutes = :minutes"
                            condition = "jobId = :job AND #status = :pending"
                            table.update_item(
                                Key={
                                    "pk": f"COMMUTE#{job['stationKey']}",
                                    "sk": f"TOWN#{job['town']}",
                                },
                                UpdateExpression=update,
                                ConditionExpression=condition,
                                ExpressionAttributeNames={"#status": "status"},
                                ExpressionAttributeValues={
                                    ":ok": "ok",
                                    ":minutes": Decimal("20.5"),
                                    ":job": job["jobId"],
                                    ":pending": "pending",
                                },
                            )
                        except (
                            table.meta.client.exceptions.ConditionalCheckFailedException
                        ):
                            pass

            threading.Thread(target=complete, daemon=True).start()
            print(
                "SYNTHETIC QA ONLY: Moto/place/rent fixtures and injected routes; "
                "no real provider or deployment.",
                flush=True,
            )
            uvicorn.run(
                "flatsplit_api.local:app", host="127.0.0.1", port=8010, access_log=False
            )


if __name__ == "__main__":
    main()
