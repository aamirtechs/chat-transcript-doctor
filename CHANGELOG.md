# Changelog

## 1.0.0 - 2026-11-14

Initial release.

* Chat transcript audit over a LiveChat or support chat CSV
  export: chats with no agent reply, first response over a
  threshold, chats closed unresolved, long chats with no
  resolution, chats with no CSAT rating, negative-keyword
  messages with the matched words listed, agents with slow first
  response, and a per-agent summary table.
* Data checks: duplicate chat IDs, malformed rows, invalid or
  future timestamps, invalid or negative numbers, invalid
  ratings, invalid resolved flags, and missing chat IDs and
  agents.
* Findings carry a code, rule name, severity (error or warning),
  and message; errors and warnings are counted in the summary.
* Text and --json output, --out file output, --max-first-response
  and --min-duration thresholds, --as-of for reproducible future
  timestamp checks, and a --check CI gate that exits 1 on errors
  (and on warnings with --strict).
* Zero dependencies, Python 3.10 or newer.
