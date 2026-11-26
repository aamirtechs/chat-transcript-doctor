"""Tests for chat_transcript_doctor."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import chat_transcript_doctor as ctd

NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)

HEADER = ("chat_id,agent,started_at,first_response_seconds,"
          "duration_seconds,messages,rating,tags,resolved,"
          "transcript\n")


def make_row(**overrides):
    """Build one row dict with clean defaults."""
    row = {
        "chat_id": "C-1",
        "agent": "Sara",
        "started_at": "2026-11-10 09:00:00",
        "first_response_seconds": "45",
        "duration_seconds": "300",
        "messages": "8",
        "rating": "5",
        "tags": "billing",
        "resolved": "yes",
        "transcript": "Thanks, all sorted.",
    }
    row.update(overrides)
    return row


def audit_rows(rows, **kwargs):
    """Audit rows with the sample defaults."""
    return ctd.audit(rows, kwargs.get("max_first_response", 120),
                     kwargs.get("min_duration", 900), NOW)


def rules(findings):
    """Return the set of rule names in a findings list."""
    return {f.rule for f in findings}


def by_rule(findings, rule):
    """Return the findings for one rule."""
    return [f for f in findings if f.rule == rule]


class TestParsing(unittest.TestCase):
    def test_timestamp_iso_datetime(self):
        parsed = ctd.parse_timestamp("2026-11-10 09:15:00", "C-1")
        self.assertEqual((parsed.year, parsed.month, parsed.day,
                          parsed.hour, parsed.minute),
                         (2026, 11, 10, 9, 15))

    def test_timestamp_iso_with_z(self):
        parsed = ctd.parse_timestamp("2026-11-10T09:15:00Z", "C-1")
        self.assertEqual(parsed.hour, 9)

    def test_timestamp_date_only(self):
        parsed = ctd.parse_timestamp("2026-11-10", "C-1")
        self.assertEqual((parsed.hour, parsed.minute), (0, 0))

    def test_timestamp_day_first(self):
        parsed = ctd.parse_timestamp("10/11/2026 09:15", "C-1")
        self.assertEqual((parsed.day, parsed.month), (10, 11))

    def test_timestamp_blank_is_none(self):
        self.assertIsNone(ctd.parse_timestamp("", "C-1"))
        self.assertIsNone(ctd.parse_timestamp(None, "C-1"))

    def test_timestamp_invalid_raises(self):
        with self.assertRaises(ValueError):
            ctd.parse_timestamp("not-a-date", "C-1")

    def test_parse_int_blank_is_none(self):
        self.assertIsNone(ctd.parse_int("", "C-1", "messages"))

    def test_parse_int_invalid_raises(self):
        with self.assertRaises(ValueError):
            ctd.parse_int("abc", "C-1", "messages")

    def test_parse_rating_valid(self):
        self.assertEqual(ctd.parse_rating("4", "C-1"), 4.0)
        self.assertEqual(ctd.parse_rating("4.5", "C-1"), 4.5)

    def test_parse_rating_out_of_range(self):
        with self.assertRaises(ValueError):
            ctd.parse_rating("6", "C-1")
        with self.assertRaises(ValueError):
            ctd.parse_rating("0", "C-1")

    def test_parse_rating_invalid(self):
        with self.assertRaises(ValueError):
            ctd.parse_rating("great", "C-1")

    def test_parse_resolved_forms(self):
        self.assertTrue(ctd.parse_resolved("yes", "C-1"))
        self.assertTrue(ctd.parse_resolved("TRUE", "C-1"))
        self.assertTrue(ctd.parse_resolved("1", "C-1"))
        self.assertFalse(ctd.parse_resolved("no", "C-1"))
        self.assertFalse(ctd.parse_resolved("false", "C-1"))
        self.assertFalse(ctd.parse_resolved("unresolved", "C-1"))
        self.assertIsNone(ctd.parse_resolved("", "C-1"))

    def test_parse_resolved_invalid(self):
        with self.assertRaises(ValueError):
            ctd.parse_resolved("maybe", "C-1")


class TestNegativeKeywords(unittest.TestCase):
    def test_no_match(self):
        self.assertEqual(ctd.matched_negative_words(
            "Thanks, all sorted."), [])

    def test_matches_listed_in_order(self):
        words = ctd.matched_negative_words(
            "This is terrible, worst service, I want a refund.")
        self.assertEqual(words, ["terrible", "worst", "refund"])

    def test_case_insensitive(self):
        self.assertEqual(ctd.matched_negative_words(
            "I am FURIOUS."), ["furious"])

    def test_each_word_once(self):
        self.assertEqual(ctd.matched_negative_words(
            "terrible, terrible, terrible"), ["terrible"])

    def test_phrase_match(self):
        self.assertEqual(ctd.matched_negative_words(
            "I will never again use this."), ["never again"])

    def test_no_partial_word_match(self):
        # "refundable" must not match "refund".
        self.assertEqual(ctd.matched_negative_words(
            "The item is refundable."), [])


class TestRowRules(unittest.TestCase):
    def test_clean_row_has_no_findings(self):
        findings, _ = audit_rows([make_row()])
        self.assertEqual(findings, [])

    def test_no_agent_reply(self):
        findings, _ = audit_rows(
            [make_row(first_response_seconds="")])
        self.assertEqual(rules(findings), {"no-agent-reply"})
        self.assertEqual(findings[0].severity, "error")

    def test_slow_first_response(self):
        findings, _ = audit_rows(
            [make_row(first_response_seconds="240")])
        self.assertEqual(rules(findings), {"slow-first-response"})

    def test_first_response_at_threshold_not_flagged(self):
        findings, _ = audit_rows(
            [make_row(first_response_seconds="120")])
        self.assertEqual(findings, [])

    def test_first_response_one_over_threshold_flagged(self):
        findings, _ = audit_rows(
            [make_row(first_response_seconds="121")])
        self.assertEqual(rules(findings), {"slow-first-response"})

    def test_invalid_first_response(self):
        findings, _ = audit_rows(
            [make_row(first_response_seconds="abc")])
        self.assertEqual(rules(findings), {"invalid-first-response"})
        # An unparseable value is a data error, not a missing reply.
        self.assertNotIn("no-agent-reply", rules(findings))

    def test_negative_first_response(self):
        findings, _ = audit_rows(
            [make_row(first_response_seconds="-5")])
        self.assertEqual(rules(findings), {"invalid-first-response"})

    def test_closed_unresolved(self):
        findings, _ = audit_rows([make_row(resolved="no")])
        self.assertEqual(rules(findings), {"closed-unresolved"})

    def test_long_unresolved(self):
        findings, _ = audit_rows(
            [make_row(resolved="no", duration_seconds="1800")])
        self.assertEqual(rules(findings),
                         {"closed-unresolved", "long-unresolved"})

    def test_long_resolved_not_flagged(self):
        findings, _ = audit_rows(
            [make_row(duration_seconds="1800")])
        self.assertEqual(findings, [])

    def test_duration_at_min_duration_flagged(self):
        findings, _ = audit_rows(
            [make_row(resolved="no", duration_seconds="900")])
        self.assertIn("long-unresolved", rules(findings))

    def test_duration_below_min_duration_not_flagged(self):
        findings, _ = audit_rows(
            [make_row(resolved="no", duration_seconds="899")])
        self.assertEqual(rules(findings), {"closed-unresolved"})

    def test_no_csat_rating(self):
        findings, _ = audit_rows([make_row(rating="")])
        self.assertEqual(rules(findings), {"no-csat-rating"})
        self.assertEqual(findings[0].severity, "warning")

    def test_invalid_rating(self):
        findings, _ = audit_rows([make_row(rating="6")])
        self.assertEqual(rules(findings), {"invalid-rating"})
        self.assertNotIn("no-csat-rating", rules(findings))

    def test_missing_resolved(self):
        findings, _ = audit_rows([make_row(resolved="")])
        self.assertEqual(rules(findings), {"missing-resolved"})

    def test_invalid_resolved(self):
        findings, _ = audit_rows([make_row(resolved="maybe")])
        self.assertEqual(rules(findings), {"invalid-resolved"})

    def test_negative_keyword_lists_words(self):
        findings, _ = audit_rows([make_row(
            transcript="This is terrible, worst service.")])
        found = by_rule(findings, "negative-keyword")
        self.assertEqual(len(found), 1)
        self.assertIn("terrible", found[0].message)
        self.assertIn("worst", found[0].message)
        self.assertEqual(found[0].severity, "warning")

    def test_missing_agent(self):
        findings, _ = audit_rows([make_row(agent="")])
        self.assertEqual(rules(findings), {"missing-agent"})

    def test_missing_chat_id(self):
        findings, _ = audit_rows([make_row(chat_id="")])
        self.assertEqual(rules(findings), {"missing-chat-id"})

    def test_duplicate_chat_id(self):
        rows = [make_row(chat_id="C-9"),
                make_row(chat_id="C-9",
                         started_at="2026-11-10 10:00:00")]
        findings, _ = audit_rows(rows)
        found = by_rule(findings, "duplicate-chat-id")
        self.assertEqual(len(found), 1)
        self.assertIn("2026-11-10 09:00:00", found[0].message)

    def test_invalid_timestamp(self):
        findings, _ = audit_rows(
            [make_row(started_at="not-a-date")])
        self.assertEqual(rules(findings), {"invalid-timestamp"})

    def test_future_timestamp(self):
        findings, _ = audit_rows(
            [make_row(started_at="2027-01-15 09:00:00")])
        self.assertEqual(rules(findings), {"future-timestamp"})

    def test_timestamp_at_now_not_future(self):
        findings, _ = audit_rows(
            [make_row(started_at="2026-11-14 00:00:00")])
        self.assertEqual(findings, [])

    def test_invalid_duration(self):
        findings, _ = audit_rows(
            [make_row(duration_seconds="soon")])
        self.assertEqual(rules(findings), {"invalid-duration"})

    def test_negative_duration(self):
        findings, _ = audit_rows(
            [make_row(duration_seconds="-10")])
        self.assertEqual(rules(findings), {"invalid-duration"})

    def test_invalid_messages(self):
        findings, _ = audit_rows([make_row(messages="many")])
        self.assertEqual(rules(findings), {"invalid-messages"})


class TestAggregateRules(unittest.TestCase):
    def test_slow_agent(self):
        rows = [make_row(chat_id="C-%d" % i, agent="Omar",
                         first_response_seconds="300")
                for i in range(3)]
        findings, report = audit_rows(rows)
        found = by_rule(findings, "slow-agent")
        self.assertEqual(len(found), 1)
        self.assertIn("Omar", found[0].code)
        self.assertIn("300.0", found[0].message)

    def test_slow_agent_needs_three_chats(self):
        rows = [make_row(chat_id="C-%d" % i, agent="Omar",
                         first_response_seconds="300")
                for i in range(2)]
        findings, _ = audit_rows(rows)
        self.assertNotIn("slow-agent", rules(findings))

    def test_fast_agent_not_flagged(self):
        rows = [make_row(chat_id="C-%d" % i, agent="Omar",
                         first_response_seconds="30")
                for i in range(3)]
        findings, _ = audit_rows(rows)
        self.assertNotIn("slow-agent", rules(findings))

    def test_agent_average_uses_recorded_responses_only(self):
        rows = [make_row(chat_id="C-1", agent="Omar",
                         first_response_seconds="300"),
                make_row(chat_id="C-2", agent="Omar",
                         first_response_seconds=""),
                make_row(chat_id="C-3", agent="Omar",
                         first_response_seconds="300")]
        findings, _ = audit_rows(rows)
        # Only 2 recorded responses, below the 3-chat minimum.
        self.assertNotIn("slow-agent", rules(findings))


class TestReport(unittest.TestCase):
    def test_per_agent_table(self):
        rows = [make_row(chat_id="C-1", agent="Sara",
                         first_response_seconds="60"),
                make_row(chat_id="C-2", agent="Sara",
                         first_response_seconds="30",
                         resolved="no", rating=""),
                make_row(chat_id="C-3", agent="Omar",
                         first_response_seconds="240")]
        _, report = audit_rows(rows)
        by_agent = {r["agent"]: r for r in report["agents"]}
        self.assertEqual(by_agent["Sara"]["chats"], 2)
        self.assertEqual(by_agent["Sara"]["avg_first_response"], 45.0)
        self.assertEqual(by_agent["Sara"]["unresolved"], 1)
        self.assertEqual(by_agent["Sara"]["unrated"], 1)
        self.assertEqual(by_agent["Omar"]["slow"], 1)

    def test_blank_agent_grouped(self):
        rows = [make_row(agent="")]
        _, report = audit_rows(rows)
        self.assertEqual(report["agents"][0]["agent"], "(no agent)")

    def test_summary_counts(self):
        rows = [make_row(chat_id="C-1", first_response_seconds=""),
                make_row(chat_id="C-2", resolved="no")]
        findings, report = audit_rows(rows)
        summary = ctd.summarize(findings, report)
        self.assertEqual(summary["chats"], 2)
        self.assertEqual(summary["no_reply"], 1)
        self.assertEqual(summary["unresolved"], 1)
        self.assertEqual(summary["errors"], 2)
        self.assertEqual(summary["warnings"], 0)

    def test_avg_and_median_first_response(self):
        rows = [make_row(chat_id="C-1",
                         first_response_seconds="10"),
                make_row(chat_id="C-2",
                         first_response_seconds="20"),
                make_row(chat_id="C-3",
                         first_response_seconds="30")]
        _, report = audit_rows(rows)
        self.assertEqual(report["avg_first_response"], 20.0)
        self.assertEqual(report["median_first_response"], 20.0)

    def test_median_even_count(self):
        rows = [make_row(chat_id="C-1",
                         first_response_seconds="10"),
                make_row(chat_id="C-2",
                         first_response_seconds="30")]
        _, report = audit_rows(rows)
        self.assertEqual(report["median_first_response"], 20.0)

    def test_avg_rating(self):
        rows = [make_row(chat_id="C-1", rating="5"),
                make_row(chat_id="C-2", rating="3")]
        _, report = audit_rows(rows)
        self.assertEqual(report["avg_rating"], 4.0)

    def test_no_ratings_is_none(self):
        rows = [make_row(rating="")]
        _, report = audit_rows(rows)
        self.assertIsNone(report["avg_rating"])

    def test_sample_file_numbers(self):
        path = os.path.join(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))),
            "examples", "chats.csv")
        rows = ctd.read_csv(path)
        findings, report = ctd.audit(rows, 120, 900, NOW)
        summary = ctd.summarize(findings, report)
        self.assertEqual(summary["chats"], 18)
        self.assertEqual(summary["findings"], 23)
        self.assertEqual(summary["errors"], 16)
        self.assertEqual(summary["warnings"], 7)
        self.assertEqual(summary["avg_first_response"], 102.3)
        self.assertEqual(summary["median_first_response"], 45.0)
        self.assertEqual(summary["no_reply"], 1)
        self.assertEqual(summary["unresolved"], 3)
        self.assertEqual(summary["avg_rating"], 3.92)

    def test_clean_file_is_clean(self):
        path = os.path.join(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))),
            "examples", "clean.csv")
        rows = ctd.read_csv(path)
        findings, report = ctd.audit(rows, 120, 900, NOW)
        summary = ctd.summarize(findings, report)
        self.assertEqual(summary["findings"], 0)
        self.assertEqual(summary["chats"], 5)

    def test_warnings_file_only_warnings(self):
        path = os.path.join(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))),
            "examples", "warnings.csv")
        rows = ctd.read_csv(path)
        findings, report = ctd.audit(rows, 120, 900, NOW)
        summary = ctd.summarize(findings, report)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["warnings"], 2)


class TestCsvReading(unittest.TestCase):
    def test_malformed_row_flagged(self):
        text = HEADER + ("C-1,Sara,2026-11-10 09:00:00,45,300,8,5,"
                         "billing,yes,\"Thanks.\",EXTRA\n")
        with tempfile.NamedTemporaryFile(
                "w", suffix=".csv", delete=False) as handle:
            handle.write(text)
            path = handle.name
        try:
            rows = ctd.read_csv(path)
            findings, _ = audit_rows(rows)
            self.assertEqual(rules(findings), {"malformed-row"})
            self.assertIn("11 fields", findings[0].message)
        finally:
            os.unlink(path)

    def test_short_row_flagged(self):
        text = HEADER + "C-1,Sara,2026-11-10 09:00:00,45\n"
        with tempfile.NamedTemporaryFile(
                "w", suffix=".csv", delete=False) as handle:
            handle.write(text)
            path = handle.name
        try:
            rows = ctd.read_csv(path)
            findings, _ = audit_rows(rows)
            self.assertEqual(rules(findings), {"malformed-row"})
        finally:
            os.unlink(path)

    def test_missing_required_column(self):
        text = "agent,started_at\nSara,2026-11-10 09:00:00\n"
        with tempfile.NamedTemporaryFile(
                "w", suffix=".csv", delete=False) as handle:
            handle.write(text)
            path = handle.name
        try:
            with self.assertRaises(ValueError):
                ctd.read_csv(path)
        finally:
            os.unlink(path)

    def test_blank_lines_skipped(self):
        text = HEADER + "\n" + (
            "C-1,Sara,2026-11-10 09:00:00,45,300,8,5,billing,yes,"
            "\"Thanks.\"\n\n")
        with tempfile.NamedTemporaryFile(
                "w", suffix=".csv", delete=False) as handle:
            handle.write(text)
            path = handle.name
        try:
            rows = ctd.read_csv(path)
            self.assertEqual(len(rows), 1)
        finally:
            os.unlink(path)

    def test_bom_header_handled(self):
        text = "\ufeff" + HEADER + (
            "C-1,Sara,2026-11-10 09:00:00,45,300,8,5,billing,yes,"
            "\"Thanks.\"\n")
        with tempfile.NamedTemporaryFile(
                "w", suffix=".csv", delete=False,
                encoding="utf-8") as handle:
            handle.write(text)
            path = handle.name
        try:
            rows = ctd.read_csv(path)
            findings, _ = audit_rows(rows)
            self.assertEqual(findings, [])
        finally:
            os.unlink(path)


class TestCli(unittest.TestCase):
    def run_cli(self, argv):
        module = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "chat_transcript_doctor.py")
        result = subprocess.run(
            [sys.executable, module] + argv,
            capture_output=True, text=True)
        return result

    def test_check_exits_1_on_sample(self):
        result = self.run_cli(["examples/chats.csv", "--as-of",
                               "2026-11-14", "--check"])
        self.assertEqual(result.returncode, 1)

    def test_check_exits_0_on_clean(self):
        result = self.run_cli(["examples/clean.csv", "--as-of",
                               "2026-11-14", "--check"])
        self.assertEqual(result.returncode, 0)

    def test_strict_fails_on_warnings(self):
        plain = self.run_cli(["examples/warnings.csv", "--as-of",
                              "2026-11-14", "--check"])
        strict = self.run_cli(["examples/warnings.csv", "--as-of",
                               "2026-11-14", "--check", "--strict"])
        self.assertEqual(plain.returncode, 0)
        self.assertEqual(strict.returncode, 1)

    def test_json_output_shape(self):
        result = self.run_cli(["examples/clean.csv", "--as-of",
                               "2026-11-14", "--json"])
        data = json.loads(result.stdout)
        self.assertEqual(data["summary"]["chats"], 5)
        self.assertEqual(data["summary"]["findings"], 0)
        self.assertEqual(len(data["agents"]), 4)
        self.assertEqual(data["findings"], [])

    def test_out_writes_file(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False) as handle:
            out_path = handle.name
        try:
            result = self.run_cli(["examples/clean.csv", "--as-of",
                                   "2026-11-14", "--out", out_path])
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            with open(out_path, encoding="utf-8") as handle:
                self.assertIn("All chats clean.", handle.read())
        finally:
            os.unlink(out_path)

    def test_missing_file_exits_2(self):
        result = self.run_cli(["no-such-file.csv"])
        self.assertEqual(result.returncode, 2)

    def test_bad_as_of_exits_2(self):
        result = self.run_cli(["examples/clean.csv", "--as-of",
                               "tomorrow"])
        self.assertEqual(result.returncode, 2)

    def test_negative_max_first_response_exits_2(self):
        result = self.run_cli(["examples/clean.csv",
                               "--max-first-response", "-1"])
        self.assertEqual(result.returncode, 2)

    def test_max_first_response_changes_verdict(self):
        strict = self.run_cli(["examples/chats.csv", "--as-of",
                               "2026-11-14", "--check"])
        loose = self.run_cli(["examples/chats.csv", "--as-of",
                              "2026-11-14", "--check",
                              "--max-first-response", "300"])
        self.assertIn("findings: 23", strict.stdout)
        self.assertIn("findings: 20", loose.stdout)

    def test_min_duration_changes_verdict(self):
        result = self.run_cli(["examples/chats.csv", "--as-of",
                               "2026-11-14", "--check",
                               "--min-duration", "3600"])
        self.assertIn("findings: 21", result.stdout)


if __name__ == "__main__":
    unittest.main()
