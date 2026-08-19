# Phase 7 — Coverage scorecard & confidence/provenance reporting

Status: **done**. Source: `IMPLEMENTATION_PLAN.md` Phase 7; idea #32
research entry #80's open question about modeling partial/lagging coverage
honestly. Scorecard logic and tests: `civicconnector/scorecard.py`,
`tests/test_scorecard.py`. Reproducible run: `scripts/phase7_scorecard_run.py`.

## What the plan asked for

Per jurisdiction: % of meetings detected before they occur, median lag from
meeting to structured action, % of items with a decision, % with named
votes; and a kill/scope call — if `civic-scraper` + the two native APIs
cover ≥90% of documents across the three pilot cities, stop building new
connectors and invest further effort in the extraction/diff layer instead
of a fourth platform.

## Result, run 2026-08-19 against pinned fixtures

```
$ python scripts/phase7_scorecard_run.py
```

| jurisdiction | n_items | document_coverage | pct_items_with_decision | pct_items_with_named_votes | pct_meetings_detected_early | median_lag_to_structured_action |
|---|---|---|---|---|---|---|
| olympia-legistar | 4 | true | **0.0** | **0.0** | not measured | not measured |
| lacey-civicclerk | 0 | true | n/a (no items) | n/a (no items) | not measured | not measured |
| tumwater-municode | 0 | true | n/a (no items) | n/a (no items) | not measured | not measured |

### Two measures could not be run for real (and are reported as such, not guessed)

`pct_meetings_detected_early` and `median_lag_to_structured_action` are
both defined relative to *when* something was first observed, which needs
two or more polls of the same jurisdiction over time to compute. This
toolkit has no storage layer of its own (an explicit design choice carried
from Phase 6's `diff.py`: callers supply and persist poll history however
they like) and Phases 2–4's live verifications were each single
point-in-time pulls, so there is no real poll history to run these two
functions against yet. `civicconnector/scorecard.py` implements both
(`pct_meetings_detected_early`, `median_lag_to_structured_action`) against
a caller-supplied `(poll_timestamp, snapshot)` sequence, exercised in
`tests/test_scorecard.py` with synthetic poll histories, so idea #30/#4 (or
a future storage layer in this toolkit) can call them for real once poll
history exists. Reporting `None`/"not measured" here rather than a
one-off number follows the "return what you don't know, never guess" rule
this toolkit has used since Phase 1.

### `pct_items_with_decision` == 0.0 for Olympia (Legistar) is a real, if surprising, finding

Of the 4 pinned items for event 7259, one (`EventItemId` 101457) has
`EventItemActionName = "completed"` — i.e. Phase 2's `action_source ==
API` / `items_with_action` measure (research entry #80's table) counts it
— but **none** of the 4 items has a non-null `EventItemPassedFlag`. "Has an
action recorded" and "has a pass/fail decision recorded" are different
signals in Legistar's data and this scorecard's `pct_items_with_decision`
deliberately measures the latter (`AgendaItem.passed is not None`), per the
plan's literal wording ("% of items with a decision"). Confidence/
provenance is already surfaced per-item via `action_source`/`confidence`
(Phase 1); this scorecard aggregates across items rather than adding a new
per-item field.

### `pct_items_with_named_votes` == 0.0 (or n/a) everywhere

No connector currently populates the `Vote` model at all, for any of the
three jurisdictions:

- **Legistar**: `legistar_votes.json` is a pinned fixture and the votes
  endpoint is confirmed reachable, but `LegistarConnector` doesn't parse it
  into `Vote` records yet — `AgendaItem.roll_call` (a flag that a roll-call
  vote occurred) is the only vote-adjacent signal wired up so far.
- **CivicClerk**: Phase 3 found `GetMeetingItemMinutesVotes` unreachable
  for Lacey (empty for all 7 meetings tried, no way to enumerate valid item
  ids) — `CivicClerkConnector.get_items()` returns `[]`, and
  `coverage_table()` already reports `items_with_votes: 0` for this reason.
- **Municode**: `get_items()` is out of scope for Phase 4 and returns `[]`.

This is a real (if unsurprising) 0% across the board, not a bug in the
measure — see `civicconnector/scorecard.py::pct_items_with_named_votes`'s
docstring.

## Kill/scope decision

**Stop building new connectors; invest further effort in the
extraction/diff layer instead of a fourth platform.**

`document_coverage` is `true` for all three pilot jurisdictions —
Legistar's agenda/minutes URLs from the API (Phase 2), CivicClerk's
`GetMeetingFileStream` plain text (Phase 3), and Municode's downloaded/
hashed agenda PDFs (Phase 4) were all live-verified. That is 3/3 = 100%,
above the plan's 90% threshold
(`civicconnector.scorecard.kill_scope_decision`), even though Phase 5
established that `civic-scraper` itself contributes none of that coverage
(it only "works" for Legistar, and there as a strict downgrade — see
`PHASE5_DECISION.md`). The relevant fact for this criterion is that
*this toolkit's own three connectors* already retrieve a primary document
for every pilot jurisdiction; a fourth platform is not needed to hit the
threshold.

This does **not** mean the toolkit's job is done — `pct_items_with_decision`
and `pct_items_with_named_votes` being 0%/n/a show item- and vote-level
extraction is still thin for two of three platforms, and CivicClerk/
Municode have no `get_items()` coverage at all. Per the plan's Phase 8 and
non-goals section, follow-up effort should go to:

1. Wiring Legistar's pinned votes fixture/endpoint into actual `Vote`
   records (the one platform where the data is confirmed reachable).
2. Tier-3 (HTML+PDF) extraction for CivicClerk/Municode item-level data,
   per the plan's non-goal note that LLM extraction is scoped to that tier
   only, with citations, never overwriting an API-provided value.
3. Not a fourth connector (BoardDocs/PrimeGov or otherwise) until this
   extraction work is done and re-scored.

## Exit criteria

**Met**: scorecard implemented and tested (`civicconnector/scorecard.py`,
`tests/test_scorecard.py`) with a real (not synthetic-only) run against
pinned fixtures reproduced in this document and `scripts/
phase7_scorecard_run.py`; kill/scope decision recorded above.
