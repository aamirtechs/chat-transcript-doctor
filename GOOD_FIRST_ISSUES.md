# Good first issues

Seeded issues for new contributors. File each one on GitHub with the
`good first issue` and `help wanted` labels.

## 1. Add a per-agent median first response column

Title: Show each agent's median first response, not just the average

Description: The per-agent table shows the average first response,
which one very slow chat can drag up. Add a median column next to
it, so a manager can see the typical wait alongside the average.
The summary already reports a median for the whole file, so the
same helper can be reused.

Difficulty: Easy

Acceptance criteria: the per-agent table in text output shows a
median column; JSON agent rows gain a median_first_response field;
a test checks the median for the sample file (Omar 157.5s); README
documents the column.

## 2. Add a custom negative-keyword file

Title: Let teams define their own negative keywords

Description: Add an optional --keywords flag that takes a JSON
file with a list of words and phrases, replacing the built-in
negative keyword list. Teams phrase complaints differently, so
their own words (for example "escalate" or "manager please")
should be usable without editing the code.

Difficulty: Medium

Acceptance criteria: a custom keywords file flags the sample
transcripts under the new words; the built-in list still applies
without the flag; invalid JSON exits 2 with a clear error; a test
covers both cases; README documents the flag.

## 3. Add a chats-per-day trend

Title: Show chats per day in the summary

Description: Add a small table after the per-agent summary showing
chats per day (by started_at), with count, average first response,
and unresolved count, so a manager can see whether bad days
cluster on particular dates.

Difficulty: Easy

Acceptance criteria: the table appears in text output with the
correct days for the sample file; JSON output gains a days field;
a test checks the rows; README documents the table.

## 4. Flag low CSAT ratings

Title: Flag chats rated 1 or 2 as low-CSAT findings

Description: A rating of 1 or 2 is a detractor, but the tool
currently only flags a missing rating. Add a low-csat finding
(warning) for ratings at or below a --low-rating threshold
(default 2), naming the rating in the message, so unhappy
customers surface even when the transcript has no negative words.

Difficulty: Easy

Acceptance criteria: the sample file gains low-csat warnings for
C-1005 (rating 2) and C-1006 (rating 1); --low-rating 1 flags
only C-1006; a test covers the threshold; README documents the
rule.
