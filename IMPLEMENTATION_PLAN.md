# CivicConnector — Implementation Plan

Status: draft, Phase 0 in progress.
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

### Phase 0 — Repository & environment setup
- Establish repo scaffolding (this change): README, license, `.gitignore`,
  this plan.
- Decide language/tooling: Python (matches `civic-scraper`,
  `python-legistar-scraper`, and `scrapers-us-municipal`, all of which are
  candidates for reuse or reference).
- Add `pyproject.toml`, package skeleton (`civicconnector/`), test runner
  (`pytest`), and CI (lint + test on push).
- Exit criteria: `pytest` runs green on an empty test suite in CI.

### Phase 1 — Canonical schema + contract tests
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

### Phase 2 — Legistar connector (Olympia pilot)
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
  entry #80.

### Phase 3 — CivicClerk connector (Lacey pilot)
- Implement the same four-method interface against
  `laceywa.api.civicclerk.com/v1`.
- Verify `GetMeetingFileStream(plainText=true)` end-to-end for agenda/
  packet text extraction (bypassing PDF parsing).
- Resolve the highest-uncertainty item in the toolkit: whether
  `GetMeetingItemMinutesVotes` is actually populated for Lacey. If yes,
  vote extraction here becomes a function call, not an LLM task; if no,
  drop "vote extraction" from CivicClerk's promise and document the gap.
- Exit criteria: coverage table equivalent to Phase 2's, plus an explicit
  yes/no finding on `GetMeetingItemMinutesVotes` population.

### Phase 4 — Municode connector (Tumwater pilot)
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
  PDF for Tumwater without exceeding the crawl-delay budget.

### Phase 5 — `civic-scraper` evaluation and build-vs-reuse decision
- Run `biglocalnews/civic-scraper` against Olympia, Lacey, and Tumwater
  side by side with the Phase 2–4 connectors.
- Compare on document coverage and maintenance cost, not just raw field
  parity.
- Make an explicit decision: keep `civic-scraper` as the acquisition base
  layer and this toolkit as the normalization/structure layer, or diverge
  with a documented reason. Do not silently drift into a rewrite.
- Exit criteria: written decision + rationale committed to this repo.

### Phase 6 — Change-detection / agenda-diff service
- Add a service that compares successive `content_hash` values per
  meeting/item list and emits structured diff events ("item 7.B added",
  "amended", "pulled since last posting").
- This is the signal no vendor platform surfaces natively and is called
  out in idea #32's research as a differentiated feature, not a
  side-effect of scraping.
- Exit criteria: diff events generated correctly across at least two
  successive polls for each of the three pilot jurisdictions.

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
