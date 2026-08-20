# Using CivicConnector (Phase 8 quickstart)

This is the downstream-consumer entry point Phase 8 exists to produce, per
`IMPLEMENTATION_PLAN.md`'s exit criteria: pull structured
`Meeting`/`AgendaItem`/`Vote`/`Document` records for Olympia, Lacey, and
Tumwater without reading the phased build plan. For design rationale and
history, see `IMPLEMENTATION_PLAN.md`, `PHASE5_DECISION.md`, and
`PHASE7_SCORECARD.md`.

## Install

```
pip install -e .[dev]   # editable install; drop [dev] for a non-test consumer
```

## The canonical schema

Every connector emits the same four record types
(`civicconnector.models`): `Meeting`, `AgendaItem`, `Vote`, `Document` (plus
`Jurisdiction`/`Body` for the governing-body hierarchy). Fields are `None`
when a platform genuinely doesn't expose that data — a connector never
guesses. See `civicconnector/models.py` for the full field list, and
`civicconnector/connectors/base.py` for the four-method interface
(`list_bodies`, `list_meetings`, `get_items`, `get_documents`) every
connector implements identically.

## Pulling data: one connector per jurisdiction

```python
from civicconnector.connectors.legistar import LegistarConnector
from civicconnector.connectors.civicclerk import CivicClerkConnector
from civicconnector.connectors.municode import MunicodeConnector

olympia = LegistarConnector(client="olympia")
lacey = CivicClerkConnector(tenant="laceywa")
tumwater = MunicodeConnector()  # defaults to tumwater-wa-municode

for connector in (olympia, lacey, tumwater):
    for meeting in connector.list_meetings():
        items = connector.get_items(meeting)      # [] where the platform has no item API (CivicClerk, Municode)
        documents = connector.get_documents(meeting)
```

Each connector's constructor takes `fetch_json`/`fetch_html`/`fetch_bytes`
callables with `requests`-backed defaults, so tests (and downstream
callers who want caching/retries) can inject a fake — see any
`tests/test_*_connector.py` for the pattern.

## What each connector actually delivers today (Phase 7 scorecard)

Per `PHASE7_SCORECARD.md`, snapshot 2026-08-19:

| Jurisdiction | Platform   | Document coverage | Item/vote coverage |
|--------------|------------|--------------------|---------------------|
| Olympia      | Legistar   | 100%               | Items yes, votes n/a below threshold |
| Lacey        | CivicClerk | 100%               | 0% — `get_items()` returns `[]` (API unreachable, see connector docstring) |
| Tumwater     | Municode   | 100%               | 0% — no item-level API exists on this platform |

**Do not build a fourth connector expecting item/vote coverage to
improve by adding platforms** — the kill/scope decision from Phase 7 is
that document acquisition is solved (3/3 jurisdictions) and the real gap
is item/vote-level extraction on the two platforms that already return
documents but not items. See "Open follow-ups" below.

## Change detection across polls

`civicconnector/diff.py` is stateless: the toolkit holds no storage layer,
so a caller persists the hash map returned by one poll and passes it back
on the next.

```python
from civicconnector.diff import (
    hashes_from_meetings, detect_meeting_changes,
    hashes_from_items, detect_agenda_changes,
)

# First poll
meetings_1 = connector.list_meetings()
previous_hashes = hashes_from_meetings(meetings_1)  # caller persists this

# Second poll (e.g. next day)
meetings_2 = connector.list_meetings()
changes = detect_meeting_changes(meetings_2, previous_hashes)
# -> [MeetingChange(native_id=..., status="new"|"changed"|"unchanged"), ...]
```

`detect_agenda_changes` / `hashes_from_items` do the same at the
`AgendaItem` level (`added` / `amended` / `unchanged` / `pulled`), for
connectors that populate items (Legistar only, today).

## Coverage scorecard

`civicconnector/scorecard.py` computes the same measures used for the
Phase 7 kill/scope decision, so a caller can re-run it against fresh
pulls: `jurisdiction_scorecard(jurisdiction_id, items, votes)` and
`kill_scope_decision(rows)`. `scripts/phase7_scorecard_run.py` is a
runnable, reproducible example against the pinned fixtures.

## Open follow-ups (not started; explicitly out of scope for this toolkit today)

- **BoardDocs/PrimeGov connectors** for school-district coverage
  (e.g. Olympia SD, North Thurston) — no work started; see idea #32's
  suggested children.
- **Legistar Vote-record wiring**: `civicconnector/models.py`'s `Vote`
  type exists and Legistar's `eventitems` fixture already carries
  roll-call flags, but no connector method populates real `Vote` records
  yet — the Phase 7 scorecard's `pct_items_with_named_votes` is the
  measure to watch as this closes.
- **CivicClerk/Municode item-level extraction**: both platforms return
  documents but not items today (`get_items()` returns `[]` by design,
  not by bug — see each connector's module docstring for the live
  verification trail). Per Phase 7's decision, this — not a new
  connector — is the toolkit's next real gap.
- **CI is not wired up**: `.github/workflows/ci.yml` cannot be added by
  an agent (build-token `workflow` OAuth scope + this session's GitHub
  MCP write-tool permission are both blocked; see research entry #311).
  All merges to date, including this one, relied on local `pytest -q`
  runs. A human needs to resolve this directly (grant the token scope,
  add the workflow file manually via the GitHub UI, or grant MCP
  write-tool permission interactively) before further phases land with
  CI gating.
