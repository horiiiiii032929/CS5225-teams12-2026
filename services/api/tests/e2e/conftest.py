"""Black-box API clients for the #29 group-to-results journey.

The same journey runs two ways:

- Default (`pnpm test`, CI): requests go through the Lambda `handler` as API
  Gateway v2 events, with DynamoDB mocked by Moto, one place and a synthetic
  rent snapshot seeded, and commute jobs captured instead of sent. There is no
  worker locally, so `LambdaApi.complete_routes` writes results the way #15's
  worker will. Results from this mode are fixture-backed, never real data.
- `FLATSPLIT_API_URL` set (e.g. `https://<site>/api` or `http://127.0.0.1:8000`):
  real HTTP to that API with no local state. Destinations come from
  `GET /places` (preference saves need #14's persisted places), or from
  `FLATSPLIT_E2E_PLACE_ID` when a known place already exists. Searches need
  published rent (#10) and a running worker (#15); without them the search
  steps skip with that reason.
"""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

import boto3
import pytest
from moto import mock_aws

import flatsplit_api.handlers.http as http
from flatsplit_api.commute_jobs import CommuteJobs
from flatsplit_api.groups import GroupStore
from flatsplit_api.search_data import SearchDataReader
from flatsplit_api.searches import SearchStore

API_URL = os.environ.get("FLATSPLIT_API_URL", "").strip().rstrip("/")
#: A place known to exist on the target API skips the OneMap lookup.
PLACE_ID = os.environ.get("FLATSPLIT_E2E_PLACE_ID", "").strip()
#: Destination looked up on a deployed API; any selectable candidate will do.
PLACE_QUERY = os.environ.get("FLATSPLIT_E2E_PLACE_QUERY", "Kent Ridge MRT Station")
#: How long a remote search may stay pending before the steps skip as "no worker".
SEARCH_TIMEOUT_SECONDS = float(os.environ.get("FLATSPLIT_E2E_SEARCH_TIMEOUT", "120"))


@dataclass(frozen=True)
class Reply:
    status: int
    headers: dict[str, str]
    body: dict[str, Any]


class Api(Protocol):
    remote: bool

    def call(
        self, method: str, path: str, body: Any = None, token: str | None = None
    ) -> Reply: ...


def _headers(body: Any, token: str | None) -> dict[str, str]:
    headers = {"content-type": "application/json"} if body is not None else {}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return headers


@dataclass(frozen=True)
class _Context:
    function_name: str = "flatsplit-api-e2e"
    memory_limit_in_mb: int = 256
    invoked_function_arn: str = (
        "arn:aws:lambda:ap-southeast-1:000000000000:function:flatsplit-api-e2e"
    )
    aws_request_id: str = "e2e-request"


class LambdaApi:
    """Invokes the deployed handler code in-process, as API Gateway would."""

    remote = False

    def __init__(self, table: Any, jobs: list[dict[str, Any]]) -> None:
        self.table = table
        self.jobs = jobs

    def complete_routes(self, minutes: Mapping[str, float], default: float) -> None:
        """Finish every captured job as #15's worker will: a fenced update.

        The condition matches the worker contract (same job, still pending), so
        a test cannot overwrite a result the API itself already resolved.
        """
        for job in self.jobs:
            self.table.update_item(
                Key={
                    "pk": f"COMMUTE#{job['stationKey']}",
                    "sk": f"TOWN#{job['town']}",
                },
                UpdateExpression="SET #status = :ok, minutes = :minutes",
                ConditionExpression="jobId = :job AND #status = :pending",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":ok": "ok",
                    ":minutes": Decimal(str(minutes.get(job["town"], default))),
                    ":job": job["jobId"],
                    ":pending": "pending",
                },
            )

    def call(
        self, method: str, path: str, body: Any = None, token: str | None = None
    ) -> Reply:
        parsed = urllib.parse.urlsplit(path)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        event: dict[str, Any] = {
            "version": "2.0",
            "routeKey": "$default",
            "rawPath": parsed.path,
            "rawQueryString": parsed.query,
            "queryStringParameters": query or None,
            "headers": _headers(body, token),
            "requestContext": {
                "http": {
                    "method": method,
                    "path": parsed.path,
                    "sourceIp": "127.0.0.1",
                },
                "requestId": "e2e-request",
                "stage": "$default",
            },
            "isBase64Encoded": body is not None,
        }
        if body is not None:
            event["body"] = base64.b64encode(json.dumps(body).encode()).decode()
        response = http.handler(event, _Context())  # type: ignore[arg-type]
        return Reply(
            response["statusCode"],
            {k.lower(): v for k, v in (response.get("headers") or {}).items()},
            json.loads(response["body"]),
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        # Treat every redirect as a failed contract response. In particular,
        # urllib must not carry a member/invite bearer token to another origin.
        return None


class HttpApi:
    """Real HTTP against a running or deployed API."""

    remote = True

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._opener = urllib.request.build_opener(_NoRedirect())

    def call(
        self, method: str, path: str, body: Any = None, token: str | None = None
    ) -> Reply:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=_headers(body, token),
            method=method,
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                status, headers, raw = (
                    response.status,
                    response.headers,
                    response.read(),
                )
        except urllib.error.HTTPError as error:
            with error:
                status, headers = error.code, error.headers
                raw = b"" if 300 <= status < 400 else error.read()
        return Reply(
            status,
            {k.lower(): v for k, v in headers.items()},
            json.loads(raw) if raw and not 300 <= status < 400 else {},
        )


SEEDED_PLACE = "pl_e2e_kent_ridge"

#: Synthetic whole-flat medians per town, chosen so the journey exercises each
#: rule: a feasible town at the exact budget (QUEENSTOWN), one over budget
#: (BISHAN) and, with `SEEDED_MINUTES`, one over the commute limit. Towns with
#: no entry have no summary and are excluded as RENT_UNAVAILABLE. Not HDB data.
SEEDED_RENT: dict[str, dict[str, int]] = {
    "3-ROOM": {
        "CLEMENTI": 2200,
        "QUEENSTOWN": 2400,
        "BUKIT MERAH": 2300,
        "JURONG EAST": 2000,
        "BISHAN": 2600,
    },
    "5-ROOM": {
        "CLEMENTI": 5200,
        "QUEENSTOWN": 6000,
        "BUKIT MERAH": 5500,
        "JURONG EAST": 4800,
        "BISHAN": 6200,
    },
}
#: Injected commute minutes; fractional and exactly-at-limit values on purpose.
SEEDED_MINUTES = {
    "CLEMENTI": 18,
    "QUEENSTOWN": 25.5,
    "BUKIT MERAH": 30,
    "JURONG EAST": 35,
}
DEFAULT_MINUTES = 20.0


def _seed_rent(table: Any) -> None:
    snapshot = "e2e-synthetic"
    table.put_item(
        Item={
            "pk": "RENT",
            "sk": "CURRENT",
            "schemaVersion": 1,
            "snapshotId": snapshot,
            "period": "2025-10/2026-09",
        }
    )
    for flat_type, medians in SEEDED_RENT.items():
        for town, median in medians.items():
            table.put_item(
                Item={
                    "pk": f"RENT#{snapshot}",
                    "sk": f"TOWN#{town}#{flat_type}",
                    "schemaVersion": 1,
                    "town": town,
                    "flatType": flat_type,
                    "median": median,
                    "p25": median - 100,
                    "p75": median + 100,
                    "medianCi95Low": median - 50,
                    "medianCi95High": median + 50,
                    "count": 200,
                    "qualityStatus": "USABLE",
                }
            )


def _seed_place(table: Any) -> None:
    table.put_item(
        Item={
            "pk": f"PLACE#{SEEDED_PLACE}",
            "sk": "META",
            "label": "Kent Ridge MRT Station",
            "address": "Kent Ridge MRT Station, Singapore",
            "station": {
                "stationKey": "KENT_RIDGE",
                "codes": ["CC24"],
                "name": "Kent Ridge",
                "lat": Decimal("1.29330347372"),
                "lng": Decimal("103.784516185"),
                "snapMetres": 0,
                "snapWarning": False,
            },
            "ttl": int(datetime.now(UTC).timestamp()) + 86400,
        }
    )


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    if API_URL:
        yield HttpApi(API_URL)
        return
    with mock_aws():
        table = boto3.resource("dynamodb", region_name="ap-southeast-1").create_table(
            TableName="flatsplit-e2e",
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
        _seed_place(table)
        _seed_rent(table)
        store = GroupStore(table)
        jobs: list[dict[str, Any]] = []
        searches = SearchStore(
            table, store, SearchDataReader(table), CommuteJobs(table, jobs.append)
        )
        monkeypatch.setattr(http, "group_store", lambda: store)
        monkeypatch.setattr(http, "search_store", lambda _groups: searches)
        yield LambdaApi(table, jobs)


@pytest.fixture
def place_id(api: Api) -> str:
    if not api.remote:
        return SEEDED_PLACE
    if PLACE_ID:
        return PLACE_ID
    query = urllib.parse.quote(PLACE_QUERY)
    reply = api.call("GET", f"/places?q={query}")
    assert reply.status == 200, reply.body
    if not reply.body["places"]:
        pytest.fail(f"No selectable place for {PLACE_QUERY!r}: {reply.body}")
    place: str = reply.body["places"][0]["placeId"]
    return place
