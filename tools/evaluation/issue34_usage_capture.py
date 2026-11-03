#!/usr/bin/env python3
"""Capture read-only deployed data-quality and AWS usage evidence for issue #34."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MIN_BLOCKS_FOR_USABLE = 2
MAX_CI_RELATIVE_WIDTH_FOR_USABLE = 0.10


def aws(profile: str, region: str, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "aws",
            "--profile",
            profile,
            "--region",
            region,
            *arguments,
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone: {value}")
    return parsed.astimezone(UTC)


def decode_number(value: str) -> int | float:
    number = Decimal(value)
    return int(number) if number == number.to_integral_value() else float(number)


def decode_attribute(attribute: dict[str, Any]) -> Any:
    if "S" in attribute:
        return attribute["S"]
    if "N" in attribute:
        return decode_number(attribute["N"])
    if "BOOL" in attribute:
        return attribute["BOOL"]
    if "NULL" in attribute:
        return None
    raise ValueError(f"Unsupported DynamoDB attribute: {attribute}")


def decode_item(item: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {key: decode_attribute(value) for key, value in item.items()}


def physical_id(
    resources: list[dict[str, Any]], logical_prefix: str, resource_type: str
) -> str:
    matches = [
        resource["PhysicalResourceId"]
        for resource in resources
        if resource["LogicalResourceId"].startswith(logical_prefix)
        and resource["ResourceType"] == resource_type
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one {resource_type} for {logical_prefix}, found {len(matches)}"
        )
    return matches[0]


def metric_query(
    query_id: str,
    namespace: str,
    metric_name: str,
    dimensions: dict[str, str],
    stat: str,
    period: int,
) -> dict[str, Any]:
    return {
        "Id": query_id,
        "MetricStat": {
            "Metric": {
                "Namespace": namespace,
                "MetricName": metric_name,
                "Dimensions": [
                    {"Name": name, "Value": value} for name, value in dimensions.items()
                ],
            },
            "Period": period,
            "Stat": stat,
        },
        "ReturnData": True,
    }


def metric_results(
    profile: str,
    region: str,
    start: datetime,
    end: datetime,
    queries: list[dict[str, Any]],
) -> dict[str, Any]:
    response = aws(
        profile,
        region,
        "cloudwatch",
        "get-metric-data",
        "--start-time",
        start.isoformat(),
        "--end-time",
        end.isoformat(),
        "--scan-by",
        "TimestampAscending",
        "--metric-data-queries",
        json.dumps(queries),
    )
    return {result["Id"]: result for result in response["MetricDataResults"]}


def aggregate(result: dict[str, Any], stat: str) -> float | None:
    values = result.get("Values", [])
    if not values:
        return None
    if stat in {"Sum", "SampleCount"}:
        return float(sum(values))
    if stat == "Maximum":
        return float(max(values))
    raise ValueError(f"Unsupported aggregation statistic: {stat}")


def linear_quantile(values: list[int | float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def distribution(values: list[int | float]) -> dict[str, int | float | None]:
    return {
        "min": min(values) if values else None,
        "p25": linear_quantile(values, 0.25),
        "median": linear_quantile(values, 0.5),
        "p75": linear_quantile(values, 0.75),
        "max": max(values) if values else None,
    }


def low_confidence_reason(item: dict[str, Any]) -> str | None:
    if item.get("qualityStatus") != "LOW_CONFIDENCE":
        return None
    insufficient_blocks = item["blockCount"] < MIN_BLOCKS_FOR_USABLE
    wide_interval = item["medianCi95RelativeWidth"] > MAX_CI_RELATIVE_WIDTH_FOR_USABLE
    if insufficient_blocks and wide_interval:
        return "INSUFFICIENT_BLOCKS_AND_WIDE_CI"
    if insufficient_blocks:
        return "INSUFFICIENT_BLOCKS_ONLY"
    if wide_interval:
        return "WIDE_CI_ONLY"
    return "UNEXPLAINED"


_START = re.compile(r"^START RequestId:")
_REPORT = re.compile(r"^REPORT RequestId:")
_COMPLETIONS = {
    "Commute pair resolved",
    "Commute pair closed without a route",
}


def worker_sessions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relevant: list[dict[str, Any]] = []
    for event in events:
        message = event["message"]
        kind: str | None = None
        fields: dict[str, Any] = {}
        if _START.match(message):
            kind = "start"
        elif _REPORT.match(message):
            kind = "report"
        elif message.startswith("{"):
            try:
                fields = json.loads(message)
            except json.JSONDecodeError:
                continue
            if fields.get("message") in _COMPLETIONS:
                kind = "completion"
        if kind is not None:
            relevant.append(
                {"timestampMs": int(event["timestamp"]), "kind": kind, **fields}
            )

    sessions: list[list[dict[str, Any]]] = []
    for event in sorted(relevant, key=lambda item: item["timestampMs"]):
        if (
            not sessions
            or event["timestampMs"] - sessions[-1][-1]["timestampMs"] > 60_000
        ):
            sessions.append([])
        sessions[-1].append(event)

    output: list[dict[str, Any]] = []
    for session in sessions:
        starts = [event for event in session if event["kind"] == "start"]
        reports = [event for event in session if event["kind"] == "report"]
        completions = [event for event in session if event["kind"] == "completion"]
        if not starts:
            continue
        started_ms = starts[0]["timestampMs"]
        ended_ms = max(
            event["timestampMs"] for event in (reports or completions or starts)
        )
        duration_seconds = max((ended_ms - started_ms) / 1000, 0.001)
        pairs = {
            (event["stationKey"], event["town"])
            for event in completions
            if isinstance(event.get("stationKey"), str)
            and isinstance(event.get("town"), str)
        }
        output.append(
            {
                "startedAt": datetime.fromtimestamp(started_ms / 1000, UTC).isoformat(),
                "endedAt": datetime.fromtimestamp(ended_ms / 1000, UTC).isoformat(),
                "durationSeconds": round(duration_seconds, 3),
                "invocations": len(starts),
                "completionLogs": len(completions),
                "resolved": sum(
                    event.get("message") == "Commute pair resolved"
                    for event in completions
                ),
                "unavailable": sum(
                    event.get("message") == "Commute pair closed without a route"
                    for event in completions
                ),
                "distinctPairCount": len(pairs),
                "townCount": len({town for _station, town in pairs}),
                "stations": sorted(
                    {
                        event["stationKey"]
                        for event in completions
                        if isinstance(event.get("stationKey"), str)
                    }
                ),
                "invocationsPerMinute": round(len(starts) * 60 / duration_seconds, 1),
            }
        )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="flatsplit")
    parser.add_argument("--region", default="ap-southeast-1")
    parser.add_argument("--stack", default="FlatSplit-dev")
    parser.add_argument("--start", required=True, type=parse_time)
    parser.add_argument("--end", required=True, type=parse_time)
    parser.add_argument("--period", default=3600, type=int)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.start >= args.end:
        raise ValueError("--start must be before --end")
    if args.period < 60 or args.period % 60:
        raise ValueError("--period must be a multiple of 60 seconds")

    identity = aws(args.profile, args.region, "sts", "get-caller-identity")
    stack = aws(
        args.profile,
        args.region,
        "cloudformation",
        "describe-stacks",
        "--stack-name",
        args.stack,
    )["Stacks"][0]
    resources = aws(
        args.profile,
        args.region,
        "cloudformation",
        "list-stack-resources",
        "--stack-name",
        args.stack,
    )["StackResourceSummaries"]
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}

    functions = {
        "http": physical_id(resources, "ApiHttpHandler", "AWS::Lambda::Function"),
        "worker": physical_id(resources, "ApiCommuteWorker", "AWS::Lambda::Function"),
        "rentIngestion": physical_id(
            resources, "RentIngestionHandler", "AWS::Lambda::Function"
        ),
        "tokenRefresh": physical_id(
            resources, "ApiOneMapTokenRefresh", "AWS::Lambda::Function"
        ),
    }
    log_groups = {
        "http": physical_id(resources, "ApiHttpHandlerLogs", "AWS::Logs::LogGroup"),
        "worker": physical_id(resources, "ApiCommuteWorkerLogs", "AWS::Logs::LogGroup"),
        "rentIngestion": physical_id(
            resources, "RentIngestionHandlerLogs", "AWS::Logs::LogGroup"
        ),
        "tokenRefresh": physical_id(
            resources, "ApiOneMapTokenRefreshLogs", "AWS::Logs::LogGroup"
        ),
    }
    queues = {
        "jobs": urlparse(
            physical_id(resources, "ApiCommuteJobs", "AWS::SQS::Queue")
        ).path.rsplit("/", 1)[-1],
        "dlq": urlparse(
            physical_id(resources, "ApiCommuteDlq", "AWS::SQS::Queue")
        ).path.rsplit("/", 1)[-1],
    }
    api_id = physical_id(resources, "ApiHttpApi", "AWS::ApiGatewayV2::Api")
    table_name = outputs["TableName"]

    queries: list[dict[str, Any]] = []
    stats: dict[str, str] = {}

    def add(
        query_id: str,
        namespace: str,
        metric_name: str,
        dimensions: dict[str, str],
        stat: str = "Sum",
    ) -> None:
        queries.append(
            metric_query(
                query_id,
                namespace,
                metric_name,
                dimensions,
                stat,
                args.period,
            )
        )
        stats[query_id] = stat

    for name, function_name in functions.items():
        dimensions = {"FunctionName": function_name}
        prefix = f"lambda_{name.lower()}"
        for metric_name in ("Invocations", "Errors", "Throttles"):
            add(
                f"{prefix}_{metric_name.lower()}", "AWS/Lambda", metric_name, dimensions
            )
        add(f"{prefix}_duration_sum", "AWS/Lambda", "Duration", dimensions)
        add(
            f"{prefix}_duration_samples",
            "AWS/Lambda",
            "Duration",
            dimensions,
            "SampleCount",
        )

    api_dimensions = {"ApiId": api_id, "Stage": "$default"}
    for metric_name in ("Count", "4xx", "5xx"):
        add(f"api_{metric_name.lower()}", "AWS/ApiGateway", metric_name, api_dimensions)

    for queue_label, queue_name in queues.items():
        dimensions = {"QueueName": queue_name}
        for metric_name in (
            "NumberOfMessagesSent",
            "NumberOfMessagesReceived",
            "NumberOfMessagesDeleted",
            "NumberOfEmptyReceives",
        ):
            add(
                f"sqs_{queue_label}_{metric_name.lower()}",
                "AWS/SQS",
                metric_name,
                dimensions,
            )
        add(
            f"sqs_{queue_label}_max_age",
            "AWS/SQS",
            "ApproximateAgeOfOldestMessage",
            dimensions,
            "Maximum",
        )

    table_dimensions = {"TableName": table_name}
    for metric_name in (
        "ConsumedReadCapacityUnits",
        "ConsumedWriteCapacityUnits",
        "ReadThrottleEvents",
        "WriteThrottleEvents",
        "SystemErrors",
        "UserErrors",
    ):
        add(f"ddb_{metric_name.lower()}", "AWS/DynamoDB", metric_name, table_dimensions)

    for label, log_group in log_groups.items():
        for metric_name in ("IncomingBytes", "IncomingLogEvents"):
            add(
                f"logs_{label.lower()}_{metric_name.lower()}",
                "AWS/Logs",
                metric_name,
                {"LogGroupName": log_group},
            )

    results = metric_results(args.profile, args.region, args.start, args.end, queries)
    metrics = {
        query_id: {
            "stat": stats[query_id],
            "aggregate": aggregate(result, stats[query_id]),
            "status": result["StatusCode"],
            "points": [
                {"timestamp": timestamp, "value": value}
                for timestamp, value in zip(
                    result.get("Timestamps", []), result.get("Values", []), strict=True
                )
            ],
        }
        for query_id, result in results.items()
    }

    lambda_summary: dict[str, Any] = {}
    for name in functions:
        prefix = f"lambda_{name.lower()}"
        duration_sum = metrics[f"{prefix}_duration_sum"]["aggregate"]
        duration_samples = metrics[f"{prefix}_duration_samples"]["aggregate"]
        lambda_summary[name] = {
            "invocations": metrics[f"{prefix}_invocations"]["aggregate"],
            "errors": metrics[f"{prefix}_errors"]["aggregate"],
            "throttles": metrics[f"{prefix}_throttles"]["aggregate"],
            "meanDurationMs": (
                round(duration_sum / duration_samples, 3)
                if duration_sum is not None and duration_samples
                else None
            ),
        }

    pointer = decode_item(
        aws(
            args.profile,
            args.region,
            "dynamodb",
            "get-item",
            "--table-name",
            table_name,
            "--consistent-read",
            "--key",
            json.dumps({"pk": {"S": "RENT"}, "sk": {"S": "CURRENT"}}),
        )["Item"]
    )
    rent_items = [
        decode_item(item)
        for item in aws(
            args.profile,
            args.region,
            "dynamodb",
            "query",
            "--table-name",
            table_name,
            "--consistent-read",
            "--key-condition-expression",
            "pk = :pk",
            "--expression-attribute-values",
            json.dumps({":pk": {"S": f"RENT#{pointer['snapshotId']}"}}),
        )["Items"]
    ]
    table = aws(
        args.profile,
        args.region,
        "dynamodb",
        "describe-table",
        "--table-name",
        table_name,
    )["Table"]

    custom_metrics = aws(
        args.profile,
        args.region,
        "cloudwatch",
        "list-metrics",
        "--namespace",
        "FlatSplit/dev",
    )["Metrics"]
    alarm_count = sum(
        resource["ResourceType"] == "AWS::CloudWatch::Alarm" for resource in resources
    )
    worker_logs = aws(
        args.profile,
        args.region,
        "logs",
        "filter-log-events",
        "--log-group-name",
        log_groups["worker"],
        "--start-time",
        str(int(args.start.timestamp() * 1000)),
        "--end-time",
        str(int(args.end.timestamp() * 1000)),
    )["events"]

    quality_counts = Counter(
        item.get("qualityStatus", "UNKNOWN") for item in rent_items
    )
    towns = sorted({item["town"] for item in rent_items})
    flat_types = sorted({item["flatType"] for item in rent_items})
    observed_pairs = {(item["town"], item["flatType"]) for item in rent_items}
    missing_pairs = [
        {"town": town, "flatType": flat_type}
        for town in towns
        for flat_type in flat_types
        if (town, flat_type) not in observed_pairs
    ]
    low_confidence_reasons: Counter[str] = Counter()
    low_confidence_summaries: list[dict[str, Any]] = []
    for item in rent_items:
        reason = low_confidence_reason(item)
        if reason is None:
            continue
        low_confidence_reasons[reason] += 1
        low_confidence_summaries.append(
            {
                "town": item["town"],
                "flatType": item["flatType"],
                "count": item["count"],
                "blockCount": item["blockCount"],
                "medianCi95RelativeWidth": item["medianCi95RelativeWidth"],
                "reason": reason,
            }
        )

    receipt = {
        "capturedAt": datetime.now(UTC).isoformat(),
        "window": {
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "periodSeconds": args.period,
            "classification": "observed shared-dev activity; not a controlled load run",
        },
        "environment": {
            "accountId": identity["Account"],
            "region": args.region,
            "stack": args.stack,
            "stackLastUpdatedAt": stack.get("LastUpdatedTime"),
            "deployedRevision": None,
            "deployedRevisionReason": (
                "The stack has no source-revision output; its update time does not "
                "identify a Git commit."
            ),
            "resources": {
                "functions": functions,
                "logGroups": log_groups,
                "queues": queues,
                "apiId": api_id,
                "tableName": table_name,
            },
            "access": "read-only CloudFormation, CloudWatch, Logs and DynamoDB reads",
        },
        "dataQuality": {
            "rentPointer": pointer,
            "observedSummaryCount": len(rent_items),
            "sourceDatasetIds": sorted(
                {
                    item["sourceDatasetId"]
                    for item in rent_items
                    if isinstance(item.get("sourceDatasetId"), str)
                }
            ),
            "schemaVersions": sorted(
                {
                    item["schemaVersion"]
                    for item in rent_items
                    if item.get("schemaVersion") is not None
                }
            ),
            "statistics": sorted(
                {
                    item["statistic"]
                    for item in rent_items
                    if isinstance(item.get("statistic"), str)
                }
            ),
            "townCount": len(towns),
            "towns": towns,
            "flatTypes": flat_types,
            "possibleTownFlatTypePairs": len(towns) * len(flat_types),
            "missingPairCount": len(missing_pairs),
            "missingPairs": missing_pairs,
            "missingPairCountsByFlatType": dict(
                sorted(Counter(item["flatType"] for item in missing_pairs).items())
            ),
            "qualityCounts": dict(sorted(quality_counts.items())),
            "qualityRules": {
                "minimumIndependentBlocks": MIN_BLOCKS_FOR_USABLE,
                "maximumMedianCi95RelativeWidth": (MAX_CI_RELATIVE_WIDTH_FOR_USABLE),
            },
            "lowConfidenceReasonCounts": dict(sorted(low_confidence_reasons.items())),
            "lowConfidenceSummaries": sorted(
                low_confidence_summaries,
                key=lambda item: (item["town"], item["flatType"]),
            ),
            "sampleCountDistribution": distribution(
                [item["count"] for item in rent_items]
            ),
            "blockCountDistribution": distribution(
                [item["blockCount"] for item in rent_items]
            ),
            "sampleCountDistributionByQuality": {
                quality: distribution(
                    [
                        item["count"]
                        for item in rent_items
                        if item.get("qualityStatus") == quality
                    ]
                )
                for quality in sorted(quality_counts)
            },
            "sourceUpdatedAt": next(
                (
                    item["sourceUpdatedAt"]
                    for item in rent_items
                    if item.get("sourceUpdatedAt")
                ),
                None,
            ),
        },
        "usage": {
            "lambda": lambda_summary,
            "api": {
                "requests": metrics["api_count"]["aggregate"],
                "clientErrors4xx": metrics["api_4xx"]["aggregate"],
                "serverErrors5xx": metrics["api_5xx"]["aggregate"],
            },
            "queue": {
                label: {
                    "messagesSent": metrics[f"sqs_{label}_numberofmessagessent"][
                        "aggregate"
                    ],
                    "messagesReceived": metrics[
                        f"sqs_{label}_numberofmessagesreceived"
                    ]["aggregate"],
                    "messagesDeleted": metrics[f"sqs_{label}_numberofmessagesdeleted"][
                        "aggregate"
                    ],
                    "emptyReceives": metrics[f"sqs_{label}_numberofemptyreceives"][
                        "aggregate"
                    ],
                    "maxOldestMessageAgeSeconds": metrics[f"sqs_{label}_max_age"][
                        "aggregate"
                    ],
                }
                for label in queues
            },
            "dynamodb": {
                "tableSizeBytes": table["TableSizeBytes"],
                "itemCountApproximate": table["ItemCount"],
                "consumedReadCapacityUnits": metrics["ddb_consumedreadcapacityunits"][
                    "aggregate"
                ],
                "consumedWriteCapacityUnits": metrics["ddb_consumedwritecapacityunits"][
                    "aggregate"
                ],
                "readThrottleEvents": metrics["ddb_readthrottleevents"]["aggregate"],
                "writeThrottleEvents": metrics["ddb_writethrottleevents"]["aggregate"],
                "systemErrors": metrics["ddb_systemerrors"]["aggregate"],
                "userErrors": metrics["ddb_usererrors"]["aggregate"],
            },
            "logs": {
                label: {
                    "incomingBytes": metrics[f"logs_{label.lower()}_incomingbytes"][
                        "aggregate"
                    ],
                    "incomingEvents": metrics[
                        f"logs_{label.lower()}_incominglogevents"
                    ]["aggregate"],
                }
                for label in log_groups
            },
            "workerSessions": worker_sessions(worker_logs),
            "customMetricCountObserved": len(custom_metrics),
            "customMetrics": sorted(
                {
                    metric["MetricName"]
                    for metric in custom_metrics
                    if isinstance(metric.get("MetricName"), str)
                }
            ),
            "alarmCountDeployed": alarm_count,
        },
        "metricSeries": metrics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {args.output}: {receipt['usage']['api']['requests']} API requests, "
        f"{receipt['usage']['lambda']['worker']['invocations']} worker invocations"
    )


if __name__ == "__main__":
    main()
