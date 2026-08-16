CivicConnector
==============

Reusable connectors for civic-government meeting platforms (Legistar/Granicus,
CivicClerk, Municode), normalizing agenda, vote, and document data into one
canonical schema with provenance and change detection.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the phased build
plan and current status.

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
