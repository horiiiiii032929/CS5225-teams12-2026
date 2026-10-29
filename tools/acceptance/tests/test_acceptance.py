"""Regressions for the eight findings in @wkkuu's #67 reviews.

The gate is the thing that decides whether a deployment passed, so a bug in
it is worse than a bug it fails to catch: it reports success. Each test here
is a case the earlier version accepted.
"""

import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from acceptance import (  # noqa: E402
    FAIL,
    REDACTED,
    Report,
    credential_fields,
    detail_of,
    finite,
    pending_pairs,
    redact,
    same_point,
    saved_mismatches,
    shown,
    station_pinned,
)


class PendingPairs(unittest.TestCase):
    """`resolved` already counts the unavailable pairs."""

    def test_nothing_resolved_leaves_every_pair_pending(self) -> None:
        progress = {"total": 54, "resolved": 2, "unavailable": 2}
        # The old arithmetic subtracted both and reported 50.
        self.assertEqual(pending_pairs(progress), 52)

    def test_all_routes_unavailable_is_zero_pending_not_negative(self) -> None:
        progress = {"total": 54, "resolved": 54, "unavailable": 54}
        # The old arithmetic reported -54.
        self.assertEqual(pending_pairs(progress), 0)

    def test_a_finished_search_has_no_pending_pairs(self) -> None:
        self.assertEqual(pending_pairs({"total": 54, "resolved": 54}), 0)

    def test_an_unusable_progress_block_is_unknown_not_zero(self) -> None:
        self.assertIsNone(pending_pairs(None))
        self.assertIsNone(pending_pairs({"total": "many", "resolved": 1}))
        self.assertIsNone(pending_pairs({"resolved": 1}))


class StationPinned(unittest.TestCase):
    """Checking latitude alone accepted a candidate with no longitude."""

    def station(self, **overrides: object) -> dict[str, object]:
        station = {"stationKey": "KENT_RIDGE", "lat": 1.29455, "lng": 103.78}
        station.update(overrides)
        return {"placeId": "p1", "station": station}

    def test_a_pinned_candidate_passes(self) -> None:
        self.assertTrue(station_pinned(self.station()))

    def test_a_missing_longitude_fails(self) -> None:
        place = self.station()
        del place["station"]["lng"]  # type: ignore[index]
        self.assertFalse(station_pinned(place))

    def test_a_missing_station_key_fails(self) -> None:
        self.assertFalse(station_pinned(self.station(stationKey="")))

    def test_a_zero_coordinate_is_a_coordinate(self) -> None:
        self.assertTrue(station_pinned(self.station(lat=0.0)))

    def test_a_non_numeric_coordinate_fails(self) -> None:
        self.assertFalse(station_pinned(self.station(lng="103.78")))
        self.assertFalse(station_pinned(self.station(lat=float("nan"))))

    def test_no_station_at_all_fails(self) -> None:
        self.assertFalse(station_pinned({"placeId": "p1"}))
        self.assertFalse(station_pinned({"placeId": "p1", "station": None}))
        self.assertFalse(station_pinned("not a place"))

    def test_finite_rejects_booleans(self) -> None:
        self.assertFalse(finite(True))
        self.assertTrue(finite(0))


class SavedPreferences(unittest.TestCase):
    """Finite coordinates are not preserved coordinates."""

    def want(self) -> dict[str, object]:
        return {
            "name": "Member B",
            "place": {
                "placeId": "plc_b",
                "station": {
                    "stationKey": "RAFFLES_PLACE",
                    "lat": 1.284,
                    "lng": 103.8515,
                },
            },
            "budget": 1400,
            "maxCommute": 45,
        }

    def member(self, **station: object) -> dict[str, object]:
        pin = {"stationKey": "RAFFLES_PLACE", "lat": 1.284, "lng": 103.8515}
        pin.update(station)
        return {
            "memberId": "m2",
            "budget": 1400,
            "maxCommute": 45,
            "destination": {"placeId": "plc_b", "station": pin},
        }

    def test_the_saved_preference_reloads_unchanged(self) -> None:
        self.assertEqual(saved_mismatches(self.member(), self.want()), [])

    def test_another_finite_pin_is_a_mismatch(self) -> None:
        """The case that passed: placeId and stationKey kept, pin replaced."""
        moved = self.member(lat=8.12345, lng=111.12345)
        self.assertEqual(
            saved_mismatches(moved, self.want()), ["station lat", "station lng"]
        )

    def test_one_moved_coordinate_is_named(self) -> None:
        self.assertEqual(
            saved_mismatches(self.member(lng=111.1), self.want()), ["station lng"]
        )

    def test_a_storage_round_trip_is_not_a_mismatch(self) -> None:
        """The pin comes back as a float converted from a stored Decimal."""
        from decimal import Decimal

        rounded = self.member(
            lat=float(Decimal("1.284")), lng=float(Decimal("103.8515"))
        )
        self.assertEqual(saved_mismatches(rounded, self.want()), [])

    def test_the_earlier_findings_stay_closed(self) -> None:
        swapped = self.member()
        swapped["destination"] = {"placeId": "plc_a", "station": {}}  # Member A's
        self.assertIn("placeId", saved_mismatches(swapped, self.want()))
        dropped = self.member()
        del dropped["destination"]["station"]["lng"]  # type: ignore[index]
        self.assertIn("station lng", saved_mismatches(dropped, self.want()))
        for field, value in (("budget", 900), ("maxCommute", 30)):
            changed = self.member()
            changed[field] = value
            self.assertIn(field, saved_mismatches(changed, self.want()))

    def test_a_missing_member_is_every_mismatch_not_a_crash(self) -> None:
        self.assertEqual(len(saved_mismatches({}, self.want())), 6)
        self.assertEqual(len(saved_mismatches(None, self.want())), 6)

    def test_same_point_rejects_the_unusable(self) -> None:
        self.assertFalse(same_point(None, 1.284))
        self.assertFalse(same_point(1.284, None))
        self.assertFalse(same_point(float("nan"), float("nan")))
        self.assertFalse(same_point(True, 1.0))
        self.assertTrue(same_point(0, 0.0))


class SearchViewPrivacy(unittest.TestCase):
    """A credential in a response the gate formatted, and never checked."""

    def view(self) -> dict[str, object]:
        return {
            "searchId": "srch_1",
            "status": "pending",
            "progress": {
                "total": 54,
                "resolved": 2,
                "unavailable": 2,
                "memberToken": "mem_secret_value",
            },
        }

    def check(self, body: object) -> tuple[bool, Report, str]:
        """Run the gate's privacy check, capturing what it would print."""
        report = Report()
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            ok = report.no_credentials("search", "no credential in the view", body)
        return ok, report, printed.getvalue()

    def test_a_nested_token_in_progress_fails_the_run(self) -> None:
        ok, report, _ = self.check(self.view())
        self.assertFalse(ok)
        self.assertEqual(len(report.failed), 1)
        self.assertEqual(report.checks[-1]["result"], FAIL)
        self.assertIn("progress.memberToken", str(report.checks[-1]["detail"]))

    def test_neither_stdout_nor_evidence_carries_the_value(self) -> None:
        _, report, printed = self.check(self.view())
        self.assertNotIn("mem_secret_value", str(report.checks[-1]))
        self.assertNotIn("mem_secret_value", printed)

    def test_the_status_detail_is_redacted_before_it_is_formatted(self) -> None:
        """`detail_of` is the only way raw progress reaches a detail line."""
        detail = f"status=pending progress={detail_of(self.view()['progress'], 200)}"
        self.assertNotIn("mem_secret_value", detail)
        self.assertIn(REDACTED, detail)
        self.assertIn('"total": 54', detail)

    def test_a_clean_view_passes_and_records_no_detail(self) -> None:
        clean = self.view()
        del clean["progress"]["memberToken"]  # type: ignore[index]
        ok, report, _ = self.check(clean)
        self.assertTrue(ok)
        self.assertEqual(report.failed, [])
        self.assertEqual(report.checks[-1]["detail"], "")


class CountDetails(unittest.TestCase):
    """A count slot can hold an object, and f-strings do not redact."""

    MARKER = "WK67_SYNTHETIC_PRIVATE_MARKER"

    def test_a_scalar_prints_as_itself(self) -> None:
        for value in (0, 0.0, 54, -1, 1.5, "pending", True, None, "?"):
            self.assertEqual(shown(value), str(value))

    def test_a_nested_credential_in_a_count_slot_is_redacted(self) -> None:
        """The counter probe: progress.unavailable is a dict with a token."""
        progress = {
            "total": 54,
            "resolved": 2,
            "unavailable": {"memberToken": self.MARKER},
        }
        counts = (
            f"total={shown(progress.get('total', '?'))}"
            f" resolved={shown(progress.get('resolved', '?'))}"
            f" unavailable={shown(progress.get('unavailable', '?'))}"
        )
        self.assertNotIn(self.MARKER, counts)
        self.assertIn(REDACTED, counts)
        self.assertIn("total=54", counts)

    def test_a_credential_at_any_depth_of_a_detail_value_is_redacted(self) -> None:
        nested = {"codes": [{"detail": {"invite_token": self.MARKER}}]}
        self.assertNotIn(self.MARKER, shown(nested, limit=400))

    def test_a_long_object_in_a_count_slot_is_truncated(self) -> None:
        self.assertEqual(len(shown({"x": "y" * 500}, limit=40)), 40)


class Credentials(unittest.TestCase):
    """Two top-level keys were checked; a nested token is just as leaked."""

    def test_a_nested_member_token_is_found(self) -> None:
        body = {"group": {"members": [{"memberId": "m1", "memberToken": "mem_x"}]}}
        self.assertEqual(credential_fields(body), ["group.members[0].memberToken"])

    def test_a_renamed_key_is_still_a_credential(self) -> None:
        self.assertEqual(credential_fields({"member_token": "x"}), ["member_token"])
        self.assertEqual(credential_fields({"Invite-Token": "x"}), ["Invite-Token"])

    def test_a_clean_body_has_none(self) -> None:
        body = {"group": {"members": [{"memberId": "m1", "budget": 1400}]}}
        self.assertEqual(credential_fields(body), [])

    def test_redaction_keeps_the_shape_and_drops_the_value(self) -> None:
        body = {"group": {"members": [{"memberId": "m1", "memberToken": "mem_x"}]}}
        safe = redact(body)
        self.assertEqual(
            safe,
            {"group": {"members": [{"memberId": "m1", "memberToken": REDACTED}]}},
        )
        self.assertNotIn("mem_x", str(safe))

    def test_a_failing_response_does_not_print_its_token(self) -> None:
        """A 500 creation response still carries the tokens it issued."""
        created = {
            "error": {"code": "INTERNAL", "message": "write failed"},
            "memberToken": "mem_secret_value",
            "group": {"inviteToken": "inv_secret_value"},
        }
        detail = detail_of(created, limit=400)
        self.assertNotIn("mem_secret_value", detail)
        self.assertNotIn("inv_secret_value", detail)
        self.assertIn("write failed", detail)

    def test_a_long_detail_is_still_truncated(self) -> None:
        self.assertEqual(len(detail_of({"m": "x" * 500}, limit=40)), 40)


if __name__ == "__main__":
    unittest.main()
