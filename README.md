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
pilot), and Phase 4 (Municode connector, Tumwater pilot) are complete.
Phase 3 (CivicClerk connector, Lacey pilot) is implemented and awaiting
review in PR #4. Phase 5 (`civic-scraper` build-vs-reuse evaluation) is
complete: this toolkit's own connectors remain the acquisition layer for
all three pilot cities — see `PHASE5_DECISION.md`. See
`civicconnector/models.py` for the schema,
`civicconnector/connectors/base.py` for the four-method connector interface,
`civicconnector/connectors/legistar.py` for the Legistar connector and
per-event coverage table, `civicconnector/connectors/municode.py` for the
Municode connector (HTML+PDF acquisition, crawl-delay-throttled, PDF
content-hash change detection), and `tests/fixtures/` for pinned live
Legistar/CivicClerk/Municode responses.

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
