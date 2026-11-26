"""Chat transcript audit CLI.

Reads a LiveChat or support chat transcript CSV export and audits
every chat for the patterns that point at a service problem: chats
that never got an agent reply, first responses slower than the
team's target, chats closed without a resolution, long chats that
still ended unresolved, chats with no CSAT rating, messages that
use negative language, agents whose first responses run slow, and
the data problems that make the export itself untrustworthy:
duplicate chat IDs, malformed rows, and invalid or future
timestamps.

Each problem is a finding with a code, a rule name, a severity
(error or warning), and a message. Errors are the ones that cost
customers or break the books; warnings are patterns worth
investigating. --check exits 1 when any error is found, and
--strict also fails on warnings.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 chat_transcript_doctor.py examples/chats.csv
    python3 chat_transcript_doctor.py chats.csv --json --check
"""

import argparse
import csv
import re
import sys
from datetime import datetime, timezone

__version__ = "1.0.0"

DEFAULT_MAX_FIRST_RESPONSE = 120
DEFAULT_MIN_DURATION = 900
AGENT_MIN_CHATS = 3
RATING_MIN = 1
RATING_MAX = 5

REQUIRED_COLUMNS = ("chat_id", "started_at")

# Negative language in the transcript, checked as whole words or
# phrases, case-insensitive. The finding lists every word that
# matched, so the reviewer can see what the customer actually said.
NEGATIVE_KEYWORDS = (
    "angry", "furious", "terrible", "horrible", "awful", "useless",
    "worst", "disappointed", "frustrated", "frustrating", "cancel",
    "refund", "complaint", "scam", "never again", "unacceptable",
    "pathetic", "ridiculous", "disgusting", "hate", "broken",
    "rude", "incompetent", "lawsuit",
)

_NEGATIVE_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in NEGATIVE_KEYWORDS)
    + r")\b",
    re.IGNORECASE,
)

RESOLVED_TRUE = ("yes", "true", "1", "y", "resolved")
RESOLVED_FALSE = ("no", "false", "0", "n", "unresolved")

# Timestamp formats accepted, tried in order.
TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)


class Finding:
    """One audit finding for one chat, agent, or pattern."""

    def __init__(self, code, rule, severity, message):
        self.code = code
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"code": self.code, "rule": self.rule,
                "severity": self.severity, "message": self.message}

    def __str__(self):
        return "%s [%s] %s: %s" % (self.severity.upper(), self.rule,
                                   self.code, self.message)


def parse_timestamp(value, code):
    """Parse a timestamp string, or return None when blank.

    Accepts ISO form (2026-11-10 09:15:00, 2026-11-10T09:15:00Z)
    and day-first form (10/11/2026 09:15). Raises ValueError on
    anything else. Naive timestamps are read as UTC.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = text[:-1] + "+00:00" if text.endswith(("Z", "z")) \
        else text
    for fmt in TIMESTAMP_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    raise ValueError("chat %s: started_at is not a timestamp: %r"
                     % (code, value))


def parse_int(value, code, field):
    """Parse an integer field, or return None when blank.

    Raises ValueError on anything else.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        raise ValueError("chat %s: %s is not a whole number: %r"
                         % (code, field, value))


def parse_rating(value, code):
    """Parse a CSAT rating from 1 to 5, or return None when blank.

    Raises ValueError on unparseable or out-of-range values.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        rating = float(text)
    except ValueError:
        raise ValueError("chat %s: rating is not a number: %r"
                         % (code, value))
    if rating < RATING_MIN or rating > RATING_MAX:
        raise ValueError("chat %s: rating %s is outside 1 to 5"
                         % (code, text))
    return rating


def parse_resolved(value, code):
    """Parse the resolved flag, or return None when blank.

    Returns True or False. Raises ValueError on unrecognized
    values.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in RESOLVED_TRUE:
        return True
    if text in RESOLVED_FALSE:
        return False
    raise ValueError("chat %s: resolved is not yes or no: %r"
                     % (code, value))


def matched_negative_words(transcript):
    """Return the negative keywords found in a transcript, in order.

    Each keyword is listed once, in the order it appears in the
    text.
    """
    text = transcript or ""
    found = []
    for match in _NEGATIVE_PATTERN.finditer(text):
        word = match.group(0).lower()
        if word not in found:
            found.append(word)
    return found


def audit_row(row, seen_chat_ids, max_first_response, min_duration,
              now):
    """Audit one CSV row. Returns a list of Finding objects."""
    findings = []
    chat_id = str(row.get("chat_id") or "").strip()
    display = chat_id if chat_id else "(missing chat id)"

    if not chat_id:
        findings.append(Finding(display, "missing-chat-id", "error",
                                "chat_id is empty"))
    else:
        if chat_id in seen_chat_ids:
            findings.append(Finding(
                chat_id, "duplicate-chat-id", "error",
                "chat_id duplicates the chat started at %s"
                % seen_chat_ids[chat_id]))
        else:
            seen_chat_ids[chat_id] = str(
                row.get("started_at") or "").strip()

    agent = str(row.get("agent") or "").strip()
    if not agent:
        findings.append(Finding(display, "missing-agent", "warning",
                                "agent is empty, so per-agent "
                                "checks cannot see this chat"))

    try:
        started_at = parse_timestamp(row.get("started_at"), display)
    except ValueError as exc:
        findings.append(Finding(display, "invalid-timestamp",
                                "error", str(exc)))
        started_at = None
    if started_at is not None and started_at > now:
        findings.append(Finding(
            display, "future-timestamp", "error",
            "started_at %s is in the future"
            % started_at.strftime("%Y-%m-%d %H:%M:%S")))

    try:
        first_response = parse_int(
            row.get("first_response_seconds"), display,
            "first_response_seconds")
    except ValueError as exc:
        findings.append(Finding(display, "invalid-first-response",
                                "error", str(exc)))
        first_response = None
    if first_response is not None and first_response < 0:
        findings.append(Finding(
            display, "invalid-first-response", "error",
            "first_response_seconds %d is negative"
            % first_response))
        first_response = None

    if first_response is None and not any(
            f.rule == "invalid-first-response" for f in findings):
        findings.append(Finding(
            display, "no-agent-reply", "error",
            "no first response time recorded, so no agent reply "
            "is on record for this chat"))
    elif first_response is not None \
            and first_response > max_first_response:
        findings.append(Finding(
            display, "slow-first-response", "error",
            "first response took %d seconds, above the %d second "
            "target" % (first_response, max_first_response)))

    try:
        duration = parse_int(row.get("duration_seconds"), display,
                             "duration_seconds")
    except ValueError as exc:
        findings.append(Finding(display, "invalid-duration",
                                "error", str(exc)))
        duration = None
    if duration is not None and duration < 0:
        findings.append(Finding(
            display, "invalid-duration", "error",
            "duration_seconds %d is negative" % duration))
        duration = None

    try:
        messages = parse_int(row.get("messages"), display,
                             "messages")
    except ValueError as exc:
        findings.append(Finding(display, "invalid-messages",
                                "error", str(exc)))
        messages = None
    if messages is not None and messages < 0:
        findings.append(Finding(
            display, "invalid-messages", "error",
            "messages %d is negative" % messages))
        messages = None

    try:
        rating = parse_rating(row.get("rating"), display)
    except ValueError as exc:
        findings.append(Finding(display, "invalid-rating", "error",
                                str(exc)))
        rating = None
    if rating is None and not any(
            f.rule == "invalid-rating" for f in findings):
        findings.append(Finding(display, "no-csat-rating", "warning",
                                "no CSAT rating recorded for this "
                                "chat"))

    try:
        resolved = parse_resolved(row.get("resolved"), display)
    except ValueError as exc:
        findings.append(Finding(display, "invalid-resolved",
                                "error", str(exc)))
        resolved = None
    if resolved is None and not any(
            f.rule == "invalid-resolved" for f in findings):
        findings.append(Finding(display, "missing-resolved",
                                "warning",
                                "resolved flag is empty, so this "
                                "chat counts as unresolved"))
    if resolved is False:
        findings.append(Finding(display, "closed-unresolved",
                                "error",
                                "chat is closed without a "
                                "resolution"))
    if resolved is not True and duration is not None \
            and duration >= min_duration:
        findings.append(Finding(
            display, "long-unresolved", "error",
            "chat ran %d seconds with no resolution"
            % duration))

    transcript = str(row.get("transcript") or "")
    words = matched_negative_words(transcript)
    if words:
        findings.append(Finding(
            display, "negative-keyword", "warning",
            "transcript uses negative language: %s"
            % ", ".join(words)))

    return findings


def _median(values):
    """Return the median of a list of numbers, or None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _mean(values):
    """Return the mean of a list of numbers, or None when empty."""
    if not values:
        return None
    return sum(values) / len(values)


def audit(rows, max_first_response, min_duration, now):
    """Audit all CSV rows.

    Returns (findings, report) where report holds the per-agent
    table and the chat totals.
    """
    findings = []
    seen_chat_ids = {}
    chats_seen = 0
    first_responses = []
    ratings = []
    no_reply = 0
    unresolved = 0
    agents = {}

    for row in rows:
        if row.pop("_malformed", None):
            chats_seen += 1
            findings.append(Finding(
                str(row.get("chat_id") or "").strip()
                or "(missing chat id)",
                "malformed-row", "error",
                "row has %s fields, expected %s"
                % (row.pop("_field_count"), row.pop("_expected"))))
            continue
        chats_seen += 1
        findings.extend(audit_row(row, seen_chat_ids,
                                  max_first_response, min_duration,
                                  now))

        agent = str(row.get("agent") or "").strip() or "(no agent)"
        entry = agents.setdefault(agent, {
            "chats": 0, "first_responses": [], "slow": 0,
            "unresolved": 0, "unrated": 0})
        entry["chats"] += 1

        raw_first = str(
            row.get("first_response_seconds") or "").strip()
        try:
            first_response = parse_int(
                row.get("first_response_seconds"), "",
                "first_response_seconds")
        except ValueError:
            first_response = None
        if first_response is not None and first_response >= 0:
            first_responses.append(first_response)
            entry["first_responses"].append(first_response)
            if first_response > max_first_response:
                entry["slow"] += 1
        elif not raw_first:
            # Blank means no reply is on record; an unparseable
            # value is a data error, not a missing reply.
            no_reply += 1

        try:
            resolved = parse_resolved(row.get("resolved"), "")
        except ValueError:
            resolved = None
        if resolved is not True:
            unresolved += 1
            entry["unresolved"] += 1

        try:
            rating = parse_rating(row.get("rating"), "")
        except ValueError:
            rating = None
        if rating is not None:
            ratings.append(rating)
        else:
            entry["unrated"] += 1

    # Agents whose average first response is above the target.
    # Fewer than 3 chats with a recorded response is noise, so
    # those agents are not flagged.
    for agent in sorted(agents):
        entry = agents[agent]
        average = _mean(entry["first_responses"])
        if average is not None \
                and len(entry["first_responses"]) >= AGENT_MIN_CHATS \
                and average > max_first_response:
            findings.append(Finding(
                agent, "slow-agent", "error",
                "average first response %.1f seconds over %d chats, "
                "above the %d second target"
                % (average, len(entry["first_responses"]),
                   max_first_response)))

    agent_rows = [{
        "agent": agent,
        "chats": agents[agent]["chats"],
        "avg_first_response": (
            round(_mean(agents[agent]["first_responses"]), 1)
            if agents[agent]["first_responses"] else None),
        "slow": agents[agent]["slow"],
        "unresolved": agents[agent]["unresolved"],
        "unrated": agents[agent]["unrated"],
    } for agent in sorted(
        agents, key=lambda a: (-agents[a]["chats"], a))]

    report = {
        "chats": chats_seen,
        "avg_first_response": (
            round(_mean(first_responses), 1)
            if first_responses else None),
        "median_first_response": (
            round(_median(first_responses), 1)
            if first_responses else None),
        "no_reply": no_reply,
        "unresolved": unresolved,
        "avg_rating": (
            round(_mean(ratings), 2) if ratings else None),
        "agents": agent_rows,
    }
    return findings, report


def summarize(findings, report):
    """Count findings by severity."""
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    return {"chats": report["chats"],
            "avg_first_response": report["avg_first_response"],
            "median_first_response":
                report["median_first_response"],
            "no_reply": report["no_reply"],
            "unresolved": report["unresolved"],
            "avg_rating": report["avg_rating"],
            "findings": len(findings), "errors": errors,
            "warnings": warnings}


def _seconds_text(value):
    """Format an average in seconds, or a dash when there is none."""
    if value is None:
        return "-"
    return "%.1fs" % value


def format_text(findings, report, summary):
    """Render findings, the per-agent table, and the summary."""
    lines = [str(f) for f in findings]
    lines.append("")
    lines.append("Per-agent summary:")
    lines.append("  %-12s %5s %10s %5s %10s %7s"
                 % ("agent", "chats", "avg reply", "slow",
                    "unresolved", "unrated"))
    for row in report["agents"]:
        lines.append("  %-12s %5d %10s %5d %10d %7d"
                     % (row["agent"][:12], row["chats"],
                        _seconds_text(row["avg_first_response"]),
                        row["slow"], row["unresolved"],
                        row["unrated"]))
    lines.append("")
    lines.append("Chats: %d, findings: %d, errors: %d, warnings: %d"
                 % (summary["chats"], summary["findings"],
                    summary["errors"], summary["warnings"]))
    lines.append("Average first response: %s (median %s)"
                 % (_seconds_text(summary["avg_first_response"]),
                    _seconds_text(summary["median_first_response"])))
    lines.append("Chats with no reply: %d, unresolved: %d"
                 % (summary["no_reply"], summary["unresolved"]))
    if summary["avg_rating"] is None:
        lines.append("Average CSAT rating: no ratings recorded")
    else:
        lines.append("Average CSAT rating: %.2f out of 5"
                     % summary["avg_rating"])
    if summary["errors"] == 0 and summary["warnings"] == 0:
        lines.append("All chats clean.")
    return "\n".join(lines) + "\n"


def read_csv(path):
    """Read a chat transcript CSV export. Returns row dicts.

    Rows with a different field count than the header are kept
    and marked malformed, so the audit can report them instead of
    silently dropping them. Blank lines are skipped.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("%s has no header row" % path)
        header = [name.strip() for name in header]
        missing = [col for col in REQUIRED_COLUMNS
                   if col not in header]
        if missing:
            raise ValueError(
                "%s is missing required columns: %s"
                % (path, ", ".join(missing)))
        rows = []
        for fields in reader:
            if not fields or all(not f.strip() for f in fields):
                continue
            row = dict(zip(header, fields))
            if len(fields) != len(header):
                row["_malformed"] = True
                row["_field_count"] = len(fields)
                row["_expected"] = len(header)
            rows.append(row)
        return rows


def parse_args(argv):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Audit a LiveChat or support chat transcript "
        "CSV export.")
    parser.add_argument("input", help="chat transcript CSV export")
    parser.add_argument("--max-first-response", type=int,
                        default=DEFAULT_MAX_FIRST_RESPONSE,
                        help="flag first responses slower than this "
                        "many seconds (default: 120)")
    parser.add_argument("--min-duration", type=int,
                        default=DEFAULT_MIN_DURATION,
                        help="flag unresolved chats lasting at "
                        "least this many seconds (default: 900)")
    parser.add_argument("--as-of", default=None,
                        help="check future timestamps against this "
                        "date (YYYY-MM-DD), defaults to now")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", default=None,
                        help="write the report to a file")
    return parser.parse_args(argv)


def main(argv=None):
    """Entry point."""
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.max_first_response < 0:
        print("ERROR: --max-first-response must be 0 or more, got %r"
              % args.max_first_response, file=sys.stderr)
        return 2
    if args.min_duration < 0:
        print("ERROR: --min-duration must be 0 or more, got %r"
              % args.min_duration, file=sys.stderr)
        return 2
    if args.as_of:
        try:
            now = datetime.strptime(args.as_of, "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
        except ValueError:
            print("ERROR: --as-of must be YYYY-MM-DD, got %r"
                  % args.as_of, file=sys.stderr)
            return 2
    else:
        now = datetime.now(timezone.utc)
    try:
        rows = read_csv(args.input)
    except OSError as exc:
        print("ERROR: cannot read %s: %s" % (args.input, exc),
              file=sys.stderr)
        return 2
    except ValueError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    findings, report = audit(rows, args.max_first_response,
                             args.min_duration, now)
    summary = summarize(findings, report)
    if args.json:
        import json
        text = json.dumps(
            {"summary": summary, "agents": report["agents"],
             "findings": [f.as_dict() for f in findings]},
            indent=2)
    else:
        text = format_text(findings, report, summary)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as exc:
            print("ERROR: cannot write %s: %s" % (args.out, exc),
                  file=sys.stderr)
            return 2
    else:
        sys.stdout.write(text)
    if args.check and (summary["errors"]
                       or (args.strict and summary["warnings"])):
        return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
