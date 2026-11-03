import importlib.util
import unittest
from datetime import UTC, datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "issue34_usage_capture.py"
SPEC = importlib.util.spec_from_file_location("issue34_usage_capture", SCRIPT)
assert SPEC and SPEC.loader
CAPTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPTURE)


class Issue34UsageCaptureTests(unittest.TestCase):
    def test_parse_time_requires_timezone_and_normalizes_to_utc(self) -> None:
        self.assertEqual(
            CAPTURE.parse_time("2026-11-03T12:00:00+08:00"),
            datetime(2026, 11, 3, 4, tzinfo=UTC),
        )

        with self.assertRaisesRegex(ValueError, "timezone"):
            CAPTURE.parse_time("2026-11-03T12:00:00")

    def test_decode_attribute_preserves_integer_and_decimal_numbers(self) -> None:
        self.assertEqual(CAPTURE.decode_attribute({"N": "129"}), 129)
        self.assertEqual(CAPTURE.decode_attribute({"N": "4071.5"}), 4071.5)

    def test_aggregate_does_not_turn_missing_metric_into_zero(self) -> None:
        self.assertIsNone(CAPTURE.aggregate({"Values": []}, "Sum"))
        self.assertEqual(CAPTURE.aggregate({"Values": [1.5, 2.5]}, "Sum"), 4.0)
        self.assertEqual(CAPTURE.aggregate({"Values": [1.5, 2.5]}, "Maximum"), 2.5)

    def test_distribution_uses_linear_quartiles(self) -> None:
        self.assertEqual(
            CAPTURE.distribution([1, 2, 3, 4]),
            {"min": 1, "p25": 1.75, "median": 2.5, "p75": 3.25, "max": 4},
        )
        self.assertEqual(
            CAPTURE.distribution([]),
            {"min": None, "p25": None, "median": None, "p75": None, "max": None},
        )

    def test_low_confidence_reason_uses_both_quality_rules(self) -> None:
        self.assertEqual(
            CAPTURE.low_confidence_reason(
                {
                    "qualityStatus": "LOW_CONFIDENCE",
                    "blockCount": 1,
                    "medianCi95RelativeWidth": 0.05,
                }
            ),
            "INSUFFICIENT_BLOCKS_ONLY",
        )
        self.assertEqual(
            CAPTURE.low_confidence_reason(
                {
                    "qualityStatus": "LOW_CONFIDENCE",
                    "blockCount": 2,
                    "medianCi95RelativeWidth": 0.11,
                }
            ),
            "WIDE_CI_ONLY",
        )
        self.assertEqual(
            CAPTURE.low_confidence_reason(
                {
                    "qualityStatus": "LOW_CONFIDENCE",
                    "blockCount": 1,
                    "medianCi95RelativeWidth": 0.11,
                }
            ),
            "INSUFFICIENT_BLOCKS_AND_WIDE_CI",
        )
        self.assertIsNone(
            CAPTURE.low_confidence_reason(
                {
                    "qualityStatus": "USABLE",
                    "blockCount": 2,
                    "medianCi95RelativeWidth": 0.10,
                }
            )
        )

    def test_worker_sessions_split_bursts_and_count_outcomes(self) -> None:
        events = [
            {"timestamp": 1_000, "message": "START RequestId: first"},
            {
                "timestamp": 2_000,
                "message": (
                    '{"message":"Commute pair resolved","stationKey":"BEDOK",'
                    '"town":"BEDOK"}'
                ),
            },
            {"timestamp": 3_000, "message": "REPORT RequestId: first"},
            {"timestamp": 70_000, "message": "START RequestId: second"},
            {
                "timestamp": 71_000,
                "message": (
                    '{"message":"Commute pair closed without a route",'
                    '"stationKey":"EXPO","town":"TAMPINES"}'
                ),
            },
            {"timestamp": 72_000, "message": "REPORT RequestId: second"},
        ]

        sessions = CAPTURE.worker_sessions(events)

        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]["invocations"], 1)
        self.assertEqual(sessions[0]["resolved"], 1)
        self.assertEqual(sessions[0]["distinctPairCount"], 1)
        self.assertEqual(sessions[0]["townCount"], 1)
        self.assertEqual(sessions[0]["stations"], ["BEDOK"])
        self.assertEqual(sessions[1]["unavailable"], 1)
        self.assertEqual(sessions[1]["stations"], ["EXPO"])


if __name__ == "__main__":
    unittest.main()
