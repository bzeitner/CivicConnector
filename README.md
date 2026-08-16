CivicConnector
==============

Reusable connectors for civic-government meeting platforms (Legistar/Granicus,
CivicClerk, Municode), normalizing agenda, vote, and document data into one
canonical schema with provenance and change detection.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the phased build
plan and current status.

## Development

```
pip install -e .[dev]
pytest -q
```

Status: Phase 0 (repo/CI scaffolding), Phase 1 (canonical schema +
fixture-based contract tests), Phase 2 (Legistar connector, Olympia
pilot), Phase 3 (CivicClerk connector, Lacey pilot), Phase 4 (Municode
connector, Tumwater pilot), and Phase 5 (`civic-scraper` build-vs-reuse
evaluation) are all complete: this toolkit's own connectors remain the
acquisition layer for all three pilot cities — see `PHASE5_DECISION.md`.
See `civicconnector/models.py` for the schema,
`civicconnector/connectors/base.py` for the four-method connector interface,
`civicconnector/connectors/legistar.py` for the Legistar connector and
per-event coverage table, `civicconnector/connectors/civicclerk.py` for the
CivicClerk connector, `civicconnector/connectors/municode.py` for the
Municode connector (HTML+PDF acquisition, crawl-delay-throttled, PDF
content-hash change detection), and `tests/fixtures/` for pinned live
Legistar/CivicClerk/Municode responses.

Phase 3 finding: `GetMeetingItemMinutesVotes` is **not** confirmed
populated/reachable for Lacey — see `civicconnector/connectors/civicclerk.py`'s
module docstring for the full live-verification trail. Documents, by
contrast, work well: `GetMeetingFileStream(plainText=true)` returns real
agenda text with no PDF/OCR step. Phase 6 (change-detection/agenda-diff
service) is next.

## Background

This toolkit exists to support hyperlocal civic-reporting projects (starting
with the South Sound / Thurston County, WA pilot) that need structured,
trustworthy data from municipal meeting platforms without hand-rolling a
scraper per city.

Two of the three initial target platforms (Legistar, CivicClerk) expose
undocumented-but-real JSON/OData APIs; the third (Municode) requires
HTML/PDF acquisition. The differentiated value of this project is not
fetching — it's the canonical schema, honest confidence/provenance
tracking, and change detection across agenda revisions.
