#!/usr/bin/env python3
"""Capture a read-only E8 audit receipt from the deployed DynamoDB table."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


def aws(profile: str, region: str, *arguments: str) -> dict[str, Any]:
    command = [
        "aws",
        "--profile",
        profile,
        "--region",
        region,
        *arguments,
        "--output",
        "json",
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


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
    if "L" in attribute:
        return [decode_attribute(value) for value in attribute["L"]]
    if "M" in attribute:
        return {key: decode_attribute(value) for key, value in attribute["M"].items()}
    raise ValueError(f"Unsupported DynamoDB attribute: {attribute}")


def decode_item(item: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {key: decode_attribute(value) for key, value in item.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="flatsplit")
    parser.add_argument("--region", default="ap-southeast-1")
    parser.add_argument("--stack", default="FlatSplit-dev")
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    identity = aws(args.profile, args.region, "sts", "get-caller-identity")
    stack = aws(
        args.profile,
        args.region,
        "cloudformation",
        "describe-stacks",
        "--stack-name",
        args.stack,
    )["Stacks"][0]
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
    table_name = outputs["TableName"]

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
    snapshot_id = pointer["snapshotId"]
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
            json.dumps({":pk": {"S": f"RENT#{snapshot_id}"}}),
        )["Items"]
    ]
    rent_by_key = {(item["town"], item["flatType"]): item for item in rent_items}
    rent_samples = [
        rent_by_key.get((town, flat_type))
        for town, flat_type in (
            ("ANG MO KIO", "3-ROOM"),
            ("QUEENSTOWN", "4-ROOM"),
            ("TENGAH", "3-ROOM"),
            ("TENGAH", "4-ROOM"),
            ("TENGAH", "5-ROOM"),
        )
    ]

    commute_response = aws(
        args.profile,
        args.region,
        "dynamodb",
        "scan",
        "--table-name",
        table_name,
        "--consistent-read",
        "--filter-expression",
        "begins_with(pk, :prefix)",
        "--expression-attribute-values",
        json.dumps({":prefix": {"S": "COMMUTE#"}}),
    )
    commute_items = [decode_item(item) for item in commute_response["Items"]]
    successful = [item for item in commute_items if item.get("status") == "ok"]
    unavailable = [
        item for item in commute_items if item.get("status") == "unavailable"
    ]

    receipt = {
        "capturedAt": datetime.now(UTC).isoformat(),
        "environment": {
            "accountId": identity["Account"],
            "region": args.region,
            "stack": args.stack,
            "tableName": table_name,
            "access": "read-only, strongly consistent DynamoDB reads",
        },
        "rent": {
            "pointer": pointer,
            "observedSummaryCount": len(rent_items),
            "qualityCounts": {
                status: sum(item.get("qualityStatus") == status for item in rent_items)
                for status in ("USABLE", "LOW_CONFIDENCE")
            },
            "samples": rent_samples,
        },
        "commute": {
            "scannedTableItemCount": commute_response["ScannedCount"],
            "observedRecordCount": len(commute_items),
            "stationKeys": sorted({item["pk"] for item in commute_items}),
            "routingProfileVersions": sorted(
                {item["routingProfileVersion"] for item in commute_items}
            ),
            "statusCounts": {
                "ok": len(successful),
                "unavailable": len(unavailable),
            },
            "fastest": min(successful, key=lambda item: item["minutes"]),
            "slowest": max(successful, key=lambda item: item["minutes"]),
            "unavailable": unavailable,
            "records": sorted(commute_items, key=lambda item: item["sk"]),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {args.output}: {len(rent_items)} rent summaries and "
        f"{len(commute_items)} commute records"
    )


if __name__ == "__main__":
    main()
