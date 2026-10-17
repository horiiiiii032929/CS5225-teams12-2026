"""Claim station-to-station jobs without coupling searches to a routing provider.

Defaults are a 15-minute recoverable lease, monthly ``pt-v1:YYYY-MM`` profiles,
and the next Singapore weekday at 08:30. Permanently non-routable town points are
resolved locally, never sent to the queue. The worker owns routing and retries.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from boto3.dynamodb.conditions import Attr, ConditionBase

from flatsplit_api.errors import ApiError
from flatsplit_api.models import Station

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

_SINGAPORE = ZoneInfo("Asia/Singapore")
_PROFILE = re.compile(r"pt-v1:[0-9]{4}-(?:0[1-9]|1[0-2])")
_ROUTING_TIME = "08:30:00"
# No finite retry delay makes an unsupported reference point routable. This is
# the last whole UTC second representable by datetime, not a retry schedule.
_NON_ROUTABLE_RETRY_AFTER = 253402300799


def routing_profile(now: datetime) -> str:
    """Return the routing baseline's Singapore calendar-month version."""
    return f"pt-v1:{now.astimezone(_SINGAPORE):%Y-%m}"


def _routing_date(now: datetime) -> str:
    day = now.astimezone(_SINGAPORE).date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


class CommuteJobs:
    def __init__(
        self,
        table: Table,
        send: Callable[[dict[str, Any]], None],
        *,
        clock: Callable[[], datetime] | None = None,
        lease_seconds: int = 900,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.table = table
        self._send = send
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lease_seconds = lease_seconds

    def ensure(
        self,
        station: Station,
        town: str,
        point: Mapping[str, Any],
        profile: str,
        existing: dict[str, Any] | None,
        *,
        retry_unavailable: bool = False,
    ) -> dict[str, Any]:
        """Return the current cache item, enqueueing only a won eligible claim.

        Reads may reclaim missing/expired jobs; only an explicit repeat may
        retry an unavailable result after its retryAfter. A newer profile is
        protected even from an old request reclaiming an expired lease.
        """
        if _PROFILE.fullmatch(profile) is None:
            raise ValueError("routing profile must match pt-v1:YYYY-MM")
        now = self._clock().astimezone(UTC)
        now_epoch = int(now.timestamp())
        if existing is not None:
            cached_profile = existing.get("routingProfileVersion", "")
            if cached_profile > profile:
                return existing
            if cached_profile == profile:
                status = existing["status"]
                if status == "ok":
                    return existing
                if (
                    status == "pending"
                    and existing.get("leaseExpiresAt", 0) > now_epoch
                ):
                    return existing
                if status == "unavailable" and (
                    not retry_unavailable
                    or existing.get("retryAfter", _NON_ROUTABLE_RETRY_AFTER) > now_epoch
                    or point.get("routable") is False
                ):
                    return existing

        key = {"pk": f"COMMUTE#{station.stationKey}", "sk": f"TOWN#{town}"}
        job_id = str(uuid4())
        routing_date = _routing_date(now)
        item: dict[str, Any] = {
            **key,
            "status": "pending",
            "jobId": job_id,
            "routingProfileVersion": profile,
            "routingDate": routing_date,
            "routingTime": _ROUTING_TIME,
            "attempts": 0,
        }
        if point.get("routable") is False:
            item.update(
                status="unavailable",
                computedAt=now.isoformat(),
                error="NON_ROUTABLE_TOWN",
                retryAfter=_NON_ROUTABLE_RETRY_AFTER,
            )
        else:
            item["leaseExpiresAt"] = now_epoch + self._lease_seconds

        expired = Attr("status").eq("pending") & (
            Attr("leaseExpiresAt").not_exists() | Attr("leaseExpiresAt").lte(now_epoch)
        )
        eligible: ConditionBase = expired
        if retry_unavailable and point.get("routable") is not False:
            eligible |= Attr("status").eq("unavailable") & Attr("retryAfter").lte(
                now_epoch
            )
        condition = (
            Attr("pk").not_exists()
            | Attr("routingProfileVersion").not_exists()
            | Attr("routingProfileVersion").lt(profile)
            | (Attr("routingProfileVersion").eq(profile) & eligible)
        )
        try:
            self.table.put_item(Item=item, ConditionExpression=condition)
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            winner = self.table.get_item(Key=key, ConsistentRead=True).get("Item")
            if winner is None:
                raise ApiError(
                    409, "CONFLICT", "Commute claim changed. Retry the search."
                ) from None
            return winner

        if item["status"] == "unavailable":
            return item

        payload = {
            "schemaVersion": 1,
            "jobId": job_id,
            "stationKey": station.stationKey,
            "town": town,
            "origin": {"lat": float(point["lat"]), "lng": float(point["lon"])},
            "destination": {"lat": station.lat, "lng": station.lng},
            "routingProfileVersion": profile,
            "routingDate": routing_date,
            "routingTime": _ROUTING_TIME,
            "leaseExpiresAt": item["leaseExpiresAt"],
        }
        try:
            self._send(payload)
        except Exception:
            try:
                self.table.delete_item(
                    Key=key,
                    ConditionExpression=Attr("jobId").eq(job_id)
                    & Attr("status").eq("pending"),
                )
            except Exception:
                # The lease also recovers a crash or failed cleanup. Never mask
                # the send failure or delete another claimant's/result's item.
                pass
            raise
        return item
