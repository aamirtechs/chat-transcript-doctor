# chat-transcript-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/chat-transcript-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/chat-transcript-doctor/issues)

A zero-dependency Python CLI that audits a LiveChat or support
chat transcript CSV export for the patterns that point at a
service problem: chats that never got an agent reply, first
responses slower than the team's target, chats closed without a
resolution, long chats that still ended unresolved, chats with no
CSAT rating, and messages that use negative language.

LiveChat's own analytics live inside the platform, and the usual
answer for a transcript audit is manual spreadsheet work. This
tool is the offline audit: it reads the exported CSV, prints a
per-agent summary table, and flags every problem with a rule name
and a severity. It never touches your LiveChat account.

First response time is the number customers feel first.
LiveChat's platform data puts the average first response at 35
seconds after pickup with a 4 minute 18 second queue wait, and
27.4 percent of customers leave the queue before an agent picks
up. Forrester found 53 percent of customers abandon a live chat
with no reply within 3 minutes. The default 120 second target
matches the common under-2-minutes expectation; lower it with
`--max-first-response` when your team promises faster.

## Install

Requires Python 3.10 or newer. No dependencies beyond the standard
library.

```bash
pip install chat-transcript-doctor
```

Or run it straight from the source checkout:

```bash
python3 chat_transcript_doctor.py examples/chats.csv
```

## Input format

A CSV export with a header row. Columns used: `chat_id`,
`agent`, `started_at`, `first_response_seconds`,
`duration_seconds`, `messages`, `rating`, `tags`, `resolved`,
`transcript`. Extra columns are ignored, so a full LiveChat
export works as-is. Timestamps accept ISO form
(2026-11-10 09:15:00, 2026-11-10T09:15:00Z) and day-first form
(10/11/2026 09:15). Ratings are 1 to 5. The resolved flag
accepts yes, true, 1, y, or resolved for resolved, and no,
false, 0, n, or unresolved for unresolved. A UTF-8 BOM header
is handled. Rows with a different field count than the header
are reported as malformed instead of silently dropped.

```csv
chat_id,agent,started_at,first_response_seconds,duration_seconds,messages,rating,tags,resolved,transcript
C-1001,Sara,2026-11-10 09:02:00,45,420,12,5,billing,yes,"Thanks, that fixed it. Great help."
C-1002,Omar,2026-11-10 09:15:00,240,900,8,4,shipping,yes,"It took a while but the order arrived."
C-1003,Lina,2026-11-10 09:30:00,,60,0,,,no,"Customer opened the chat and left."
```

## What it checks

Errors, the ones that cost customers or break the books:

* `no-agent-reply`: no first response time recorded, so no agent
  reply is on record for this chat.
* `slow-first-response`: first response took longer than
  `--max-first-response` seconds (default 120).
* `slow-agent`: an agent's average first response is above the
  target, over 3 or more chats with a recorded response.
* `closed-unresolved`: the chat is closed without a resolution.
* `long-unresolved`: the chat ran `--min-duration` seconds or
  more (default 900) with no resolution.
* `duplicate-chat-id`: the same chat ID twice.
* `malformed-row`: the row has a different field count than the
  header.
* `invalid-timestamp`, `future-timestamp`: started_at is
  unparseable or in the future.
* `invalid-first-response`, `invalid-duration`,
  `invalid-messages`, `invalid-rating`, `invalid-resolved`:
  unparseable, negative, or out-of-range values.
* `missing-chat-id`: empty chat ID.

Warnings, patterns worth investigating:

* `negative-keyword`: the transcript uses negative language. The
  finding lists every matched word, so the reviewer can see what
  the customer actually said.
* `no-csat-rating`: no CSAT rating recorded for this chat.
* `missing-resolved`: the resolved flag is empty, so the chat
  counts as unresolved.
* `missing-agent`: empty agent, so per-agent checks cannot see
  this chat.

The report also prints a per-agent summary table after the
findings: chats, average first response, slow chats, unresolved
chats, and chats with no rating. Negative keywords are matched
as whole words, so "refundable" does not match "refund". The
full list: angry, furious, terrible, horrible, awful, useless,
worst, disappointed, frustrated, frustrating, cancel, refund,
complaint, scam, never again, unacceptable, pathetic, ridiculous,
disgusting, hate, broken, rude, incompetent, lawsuit.

## Usage

```bash
python3 chat_transcript_doctor.py examples/chats.csv --as-of 2026-11-14
```

Captured output:

```
ERROR [slow-first-response] C-1002: first response took 240 seconds, above the 120 second target
ERROR [no-agent-reply] C-1003: no first response time recorded, so no agent reply is on record for this chat
WARNING [no-csat-rating] C-1003: no CSAT rating recorded for this chat
ERROR [closed-unresolved] C-1003: chat is closed without a resolution
WARNING [no-csat-rating] C-1004: no CSAT rating recorded for this chat
ERROR [closed-unresolved] C-1004: chat is closed without a resolution
ERROR [long-unresolved] C-1004: chat ran 1800 seconds with no resolution
WARNING [negative-keyword] C-1004: transcript uses negative language: terrible, refund, worst
WARNING [negative-keyword] C-1005: transcript uses negative language: broken, useless
ERROR [slow-first-response] C-1006: first response took 600 seconds, above the 120 second target
ERROR [closed-unresolved] C-1006: chat is closed without a resolution
ERROR [long-unresolved] C-1006: chat ran 2400 seconds with no resolution
WARNING [negative-keyword] C-1006: transcript uses negative language: furious, unacceptable, cancel
ERROR [slow-first-response] C-1008: first response took 150 seconds, above the 120 second target
WARNING [no-csat-rating] C-1010: no CSAT rating recorded for this chat
ERROR [duplicate-chat-id] C-1001: chat_id duplicates the chat started at 2026-11-10 09:02:00
ERROR [invalid-first-response] C-1012: chat C-1012: first_response_seconds is not a whole number: 'abc'
ERROR [invalid-timestamp] C-1013: chat C-1013: started_at is not a timestamp: 'not-a-date'
ERROR [future-timestamp] C-1014: started_at 2027-01-15 09:00:00 is in the future
ERROR [invalid-rating] C-1015: chat C-1015: rating 6 is outside 1 to 5
WARNING [missing-agent] C-1016: agent is empty, so per-agent checks cannot see this chat
ERROR [malformed-row] C-1017: row has 11 fields, expected 10
ERROR [slow-agent] Omar: average first response 238.8 seconds over 4 chats, above the 120 second target

Per-agent summary:
  agent        chats  avg reply  slow unresolved unrated
  Sara             5      35.0s     0          1       1
  Lina             4      85.0s     1          1       2
  Omar             4     238.8s     2          1       1
  Bilal            3      61.7s     0          0       0
  (no agent)       1      50.0s     0          0       0

Chats: 18, findings: 23, errors: 16, warnings: 7
Average first response: 102.3s (median 45.0s)
Chats with no reply: 1, unresolved: 3
Average CSAT rating: 3.92 out of 5
```

The sample has 18 chats and 23 findings. The story it tells:
Omar averages 238.8 seconds to first response over 4 chats,
C-1003 never got a reply, C-1004 and C-1006 ran 30 and 40
minutes with no resolution, and C-1006's customer was furious
enough to ask for a cancellation. The export itself is shaky
too: a duplicate chat ID, a future timestamp, and a malformed
row.

Use it as a CI gate: `--check` exits 1 when any error is found,
and 0 otherwise. On the sample above it exits 1:

```bash
python3 chat_transcript_doctor.py examples/chats.csv --as-of 2026-11-14 --check
```

On `examples/clean.csv`, five clean chats, it exits 0:

```
Per-agent summary:
  agent        chats  avg reply  slow unresolved unrated
  Sara             2      35.0s     0          0       0
  Bilal            1      90.0s     0          0       0
  Lina             1      30.0s     0          0       0
  Omar             1      60.0s     0          0       0

Chats: 5, findings: 0, errors: 0, warnings: 0
Average first response: 50.0s (median 45.0s)
Chats with no reply: 0, unresolved: 0
Average CSAT rating: 4.60 out of 5
All chats clean.
```

With `--strict`, `--check` also fails on warnings: a file with
two warnings (one chat with no rating, one with a negative
keyword) exits 0 under `--check` and 1 under
`--check --strict`. `--json` emits the summary, per-agent
table, and findings as JSON, and `--out` writes the report to
a file. `--as-of 2026-11-14` checks future timestamps against
that date instead of now, so the same export gives the same
verdict every run. Raising the threshold changes the verdict:
`--max-first-response 300` on the sample drops the two slow
chats and the slow-agent finding and leaves 20 findings, 13
errors and 7 warnings.

## Options

| Flag | Meaning |
| --- | --- |
| `--max-first-response` | Flag first responses slower than this many seconds (default: 120) |
| `--min-duration` | Flag unresolved chats lasting at least this many seconds (default: 900) |
| `--as-of` | Check future timestamps against this date (YYYY-MM-DD), defaults to now |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

## Edge cases

* A first response at exactly `--max-first-response` seconds is
  not flagged; it must be strictly above it.
* An unresolved chat at exactly `--min-duration` seconds is
  flagged; the duration must be at least the threshold.
* A slow-agent finding needs at least 3 chats with a recorded
  first response; fewer is noise.
* An unparseable first response is a data error, not a missing
  reply, so it does not also raise `no-agent-reply`.
* A blank resolved flag is a warning and counts the chat as
  unresolved; an explicit "no" is an error.
* A chat with a future timestamp is an error, and the timestamp
  is checked against now unless `--as-of` is given.
* Rows with an invalid first response are excluded from the
  average and median first response, but still count in the
  per-agent chat counts.
* A malformed row is counted as a chat and reported, but skipped
  from the per-agent table.
* Negative keywords match whole words only, and each matched
  word is listed once, in the order it appears.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

74 tests, all passing: every rule, error and warning severities,
timestamp, rating and resolved parsing, negative keyword
matching, the per-agent table, slow-agent thresholds, summary
counts, JSON output shape, and `--check` and `--strict` exit
codes.

## License

MIT. See [LICENSE](LICENSE).
