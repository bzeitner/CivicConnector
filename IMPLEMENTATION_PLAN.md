# CivicConnector — Implementation Plan

Status: Phase 0, Phase 1, Phase 2 (Legistar connector, Olympia pilot),
Phase 3 (CivicClerk connector, Lacey pilot), Phase 4 (Municode connector,
Tumwater pilot), Phase 5 (`civic-scraper` build-vs-reuse evaluation;
see `PHASE5_DECISION.md`), and Phase 6 (change-detection/agenda-diff
service) are all complete and merged. Phase 7 (coverage scorecard &
confidence/provenance reporting) is next.
Source: IdeaFlow idea #32 ("Civic-source connector toolkit"), research entry
#80 (2026-08-10 live platform probe of Legistar/Granicus, CivicClerk, and
Municode for Olympia/Lacey/Tumwater, WA).

## Goal

A thin normalization layer over three different acquisition modes
(API-native, feed-native, HTML+PDF) that emits one canonical
`Meeting → AgendaItem → Vote → Document` record with provenance, honest
coverage/confidence reporting, and change detection across agenda
revisions — not a scraping framework. Do not write three independent
scrapers; reuse `civic-scraper` where it already covers acquisition.

## Non-goals (for this toolkit specifically)

- National-scale coverage (Curate/FiscalNote already own that market).
- LLM-based extraction as the default path — LLMs are used only for
  tier-3 (HTML+PDF) documents, and only to propose fields that carry a
  document offset/citation. An LLM never overwrites a value an API
  provided.
- Perfecting Municode ahead of validating demand; BoardDocs/PrimeGov
  connectors for school districts may be higher-value follow-ups but are
  out of scope until this plan's kill/scope criteria are evaluated.

## Canonical schema (target shape, refined during Phase 1)

```
Jurisdiction(id, name, platform, base_url, tz, poll_policy)
Body(jurisdiction_id, native_id, name, type)
Meeting(body_id, native_id, starts_at, status, agenda_url, minutes_url,
        video_url, first_seen_at, last_changed_at, content_hash)
AgendaItem(meeting_id, native_id, seq, number, title, matter_id,
           action_name, passed, roll_call, action_source, confidence)
Vote(agenda_item_id, person, vote_value, source)
Document(meeting_id, kind, url, retrieved_at, sha256, text_source)
```

Every connector implements exactly four methods:
`list_bodies()`, `list_meetings(since)`, `get_items(meeting)`,
`get_documents(meeting)`. Anything a platform can't do returns `None`,
never a guess.

## Phases

### Phase 0 — Repository & environment setup [done]
- Establish repo scaffolding (this change): README, license, `.gitignore`,
  this plan.
- Decide language/tooling: Python (matches `civic-scraper`,
  `python-legistar-scraper`, and `scrapers-us-municipal`, all of which are
  candidates for reuse or reference).
- Add `pyproject.toml`, package skeleton (`civicconnector/`), test runner
  (`pytest`), and CI (lint + test on push).
- Exit criteria: `pytest` runs green on an empty test suite in CI.

### Phase 1 — Canonical schema + contract tests [done]
- Implement the schema above as typed dataclasses/models.
- Capture and pin fixture JSON for Legistar and CivicClerk responses
  documented in research entry #80 (events, eventitems, votes, matter
  histories; CivicClerk `Events`, `GetMeetingFileStream`,
  `GetMeetingItemMinutesVotes`).
- Contract tests assert the connector interface against these fixtures so
  that upstream API drift on undocumented endpoints fails loudly instead
  of silently.
- Exit criteria: fixture-based contract test suite exists and passes
  against recorded (not live) responses.

### Phase 2 — Legistar connector (Olympia pilot) [done]
- Implement `list_bodies`, `list_meetings(since)`, `get_items(meeting)`,
  `get_documents(meeting)` against `webapi.legistar.com/v1/olympia`.
- Paginate under the documented 1000-record cap; handle `$filter`/
  `$orderby`.
- Populate `action_source` (`api` / `minutes_pdf` / `none`) per item, since
  research showed structured actions land on only ~0–40% of items and lag
  until minutes are processed.
- Ship the per-event coverage table (items vs. items-with-structured-
  action vs. roll-call-flagged) as a first-class connector output.
- Exit criteria: end-to-end pull for a sample of Olympia council/committee
  events matches or exceeds the manually verified figures in research
  entry #80. **Met**: a live pull against events 7259/7258/7257/7256/7255
  reproduced entry #80's coverage table exactly (items: 4/18/15/13/12;
  items_with_action: 1/7/5/0/0; roll_call_flagged: 1/2/1/1/1). See
  `civicconnector/connectors/legistar.py` and `tests/test_legistar_connector.py`.

### Phase 3 — CivicClerk connector (Lacey pilot) [done]
- Implemented `list_bodies` (via `EventCategories`), `list_meetings`,
  `get_items`, `get_documents` against `laceywa.api.civicclerk.com/v1`.
- `GetMeetingFileStream(fileId=..., plainText=true)` verified live
  end-to-end (event 1390, fileId 4059): HTTP 200, real agenda plain text,
  no PDF/OCR step needed. Exposed as `get_document_text()`.
- Resolved the highest-uncertainty item in the toolkit: whether
  `GetMeetingItemMinutesVotes` is actually populated for Lacey.
  **Finding: NO.** The bound function `Meetings/GetMeetingItemMinutesVotes(id=...)`
  responds HTTP 200 (proving it's callable per its `$metadata` signature)
  but returned an empty `value: []` for all 7 distinct Lacey meetings
  tried, using both event ids and agendaIds as `id`. No GET-accessible way
  to enumerate the item-level ids the parameter most likely expects was
  found: `Meetings(id)` 404s, `Meetings?$filter=id eq ...` 404s, and the
  `Sections` entity set (which models agenda structure) only accepts POST
  (405 on GET) — outside this API's discoverable read surface. Per the
  plan, "vote extraction" is dropped from CivicClerk's promise;
  `get_items()` returns `[]` rather than guessing, and no `Vote` records
  are ever produced by this connector. See
  `civicconnector/connectors/civicclerk.py`'s module docstring for the
  full trail and `tests/test_civicclerk_connector.py` for the pinned
  regression test asserting `items_with_votes == 0`.
- Exit criteria: **Met** (with a documented negative finding, not a
  positive one) — coverage table equivalent to Phase 2's shape
  (`coverage_table()`), plus the explicit yes/no finding above.

### Phase 4 — Municode connector (Tumwater pilot) [done]
- Enumerate `bc-*` body codes from the Drupal site's per-body views.
- Page `/meetings3?page=N`, honoring the site's `Crawl-delay: 15`
  `robots.txt` directive (no aggressive polling).
- Hash blob PDF agendas (`mccmeetings.blob.core.usgovcloudapi.net/
  tumwater-pubu/...`) to detect new/changed documents; download and
  snapshot raw PDFs for downstream extraction.
- This is the connector expected to break most often; isolate its
  HTML-parsing assumptions behind the shared connector interface so
  breakage doesn't propagate.
- Exit criteria: change detection correctly flags a new or updated agenda
  PDF for Tumwater without exceeding the crawl-delay budget. **Met**: live
  run 2026-08-16 against `tumwater-wa.municodemeetings.com` — `list_bodies()`
  found 9 `bc-*` bodies and `list_meetings()` 25 meetings from one polled
  page; a real agenda PDF (274,697 bytes) was downloaded and hashed with a
  ~14.5s gap after the prior request (crawl_delay=15s enforced by
  `MunicodeConnector._throttle`), and `detect_changes()` correctly
  classified it as `new` (no prior hash), `unchanged` (matching prior
  hash), and `changed` (stale prior hash) in three comparisons against the
  same real bytes. No API surface was found (confirming research entry
  #80); item-level agenda data (`get_items()`) is out of scope for this
  phase and returns `[]` rather than guessing. See
  `civicconnector/connectors/municode.py` and
  `tests/test_municode_connector.py`.
- Known site quirk (documented in code): the portal's WAF resets the
  connection for any `User-Agent` containing a `github.com` URL, regardless
  of a `Bot` product token; the connector's UA omits the repo URL.

### Phase 5 — `civic-scraper` evaluation and build-vs-reuse decision [done]
- Ran `biglocalnews/civic-scraper` (PyPI `civic-scraper==1.1.0`) against
  Olympia, Lacey, and Tumwater side by side with the Phase 2/4 connectors
  (Phase 3's CivicClerk connector, PR #4, not yet merged, so Lacey's
  CivicClerk API was probed directly for this comparison instead).
- Compared on document coverage and maintenance cost, not just raw field
  parity: Legistar (works, but document-links only — no items/actions/
  votes); CivicClerk (fails against the live Lacey portal — targets a
  retired ASP.NET UI); Municode (unsupported — no scraper matches
  `municodemeetings.com` at all).
- **Decision: diverge.** Keep this toolkit's own three native connectors
  as the acquisition layer for all three pilot jurisdictions; do not add
  `civic-scraper` as a dependency. Full rationale, live evidence, and the
  reproducible evaluation script: see `PHASE5_DECISION.md` and
  `scripts/phase5_civic_scraper_eval.py`.
- Exit criteria: written decision + rationale committed to this repo.
  **Met**: `PHASE5_DECISION.md`.

### Phase 6 — Change-detection / agenda-diff service [done]
- Generalized the document-level hash-and-compare primitive introduced for
  Municode in Phase 4 (`hash_bytes`/`detect_changes`) to two levels in a new
  `civicconnector/diff.py`, shared by all three connectors:
  - Item-level (`hash_item`/`detect_agenda_changes`): diffs a meeting's
    `AgendaItem` list across polls, classifying each `native_id` as
    `added`, `amended`, `unchanged`, or `pulled` (present previously, absent
    now — pulled since last posting). Content fields only; provenance
    fields (`action_source`/`confidence`) are excluded so a connector
    backfilling them later doesn't spuriously register as "amended".
  - Meeting-level (`hash_meeting`/`detect_meeting_changes`): diffs a
    jurisdiction's `Meeting` list across polls (`new`/`changed`/`unchanged`
    per `native_id`). This is the only agenda-revision signal available for
    CivicClerk and Municode, whose `get_items()` return `[]` (Phases 3-4);
    Legistar gets both levels since its `get_items()` is populated.
- Both functions are stateless, matching the Phase 4 `detect_changes()`
  contract: the caller supplies the previous poll's `{native_id: hash}` map
  (`hashes_from_items`/`hashes_from_meetings` build it) and persists the
  returned hashes for the next poll — this toolkit has no storage layer of
  its own.
- Exit criteria: **Met** — `tests/test_diff.py` exercises two successive
  polls against the pinned fixtures for all three pilot jurisdictions
  (Legistar `legistar_eventitems`/`legistar_events`, CivicClerk
  `civicclerk_events`, Municode `municode_meetings_page`), asserting
  `added`/`amended`/`unchanged`/`pulled` (item level, Legistar) and
  `new`/`changed`/`unchanged` (meeting level, all three).

### Phase 7 — Coverage scorecard & confidence/provenance reporting
- Per jurisdiction, compute: % of meetings detected before they occur,
  median lag from meeting to structured action, % of items with a
  decision, % with named votes.
- Surface `action_source`/`confidence` on every record rather than
  presenting uniform certainty.
- Apply the plan's kill/scope criteria: if `civic-scraper` + the two
  native APIs cover ≥90% of documents across the three pilot cities, stop
  building new connectors and invest further effort in the
  extraction/diff layer instead of a fourth platform.
- Exit criteria: scorecard produced for Olympia/Lacey/Tumwater; kill/scope
  decision recorded in this repo.

### Phase 8 — Packaging, docs, and pilot handoff
- Package the toolkit for consumption by IdeaFlow idea #30 (South Sound
  civic brief pilot) and idea #4 (Hyperlocal sites).
- Document setup, connector interface, schema, and the coverage
  scorecard's meaning for a downstream (non-author) engineer.
- Record open follow-ups explicitly: BoardDocs/PrimeGov connectors for
  school-district coverage, and any platforms where the kill/scope
  criteria in Phase 7 recommend against further connector work.
- Exit criteria: a downstream consumer (idea #30) can call the toolkit's
  public interface to pull structured Meeting/AgendaItem/Vote/Document
  records for Olympia, Lacey, and Tumwater without reading this plan.

## Open questions carried from research entry #80

- How should the toolkit explicitly model the partial and lagging
  coverage of structured actions and vote data across platforms so
  confidence reporting stays honest? (Addressed structurally in Phases
  1–3 via `action_source`/`confidence`; needs validation against real
  data in Phases 2–3.)
- What is the best approach to unify data from three acquisition modes
  into one canonical schema while preserving provenance and change
  detection? (Addressed in Phases 1 and 6; needs validation once all
  three connectors exist.)
