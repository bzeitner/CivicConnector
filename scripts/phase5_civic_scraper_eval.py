"""Phase 5 spike: run `civic-scraper` against the toolkit's three pilot
jurisdictions (Olympia/Legistar, Lacey/CivicClerk, Tumwater/Municode) and
report what it finds, so the build-vs-reuse decision in
`PHASE5_DECISION.md` is backed by a reproducible script rather than only a
one-off shell transcript.

Not part of the installed package and not covered by the test suite: this
is a throwaway evaluation tool, run manually against the live internet, in
the same spirit as the live-verification scripts used in Phases 2-4.

Usage (after `pip install civic-scraper`, an *optional* dev-only
dependency — see pyproject.toml's `[project.optional-dependencies].eval`):

    python scripts/phase5_civic_scraper_eval.py
"""

from __future__ import annotations

import datetime


def check_legistar() -> None:
    from civic_scraper.platforms.legistar.site import Site as LegistarSite

    print("\n== Legistar (Olympia) ==")
    # `timezone` looks optional in the signature but is not: omitting it
    # raises an opaque pytz.exceptions.UnknownTimeZoneError deep inside the
    # underlying `legistar-scraper` dependency, with no mention of
    # `timezone` in the traceback or in `civic-scraper`'s own docs.
    site = LegistarSite("https://olympia.legistar.com", timezone="America/Los_Angeles")
    today = datetime.date.today()
    start = today - datetime.timedelta(days=14)
    assets = site.scrape(start_date=start.isoformat(), end_date=today.isoformat(), download=False)
    print(f"assets found: {len(assets)}")
    for asset in list(assets)[:5]:
        print(f"  {asset.meeting_date} {asset.committee_name!r} {asset.asset_type} {asset.url}")
    print(
        "Note: this is a document-link scrape only (agenda/minutes URLs). "
        "It carries none of the structured item/action/vote/coverage data "
        "civicconnector.connectors.legistar.LegistarConnector gets from the "
        "same city's JSON API."
    )


def check_civicclerk() -> None:
    from civic_scraper.platforms.civic_clerk.site import CivicClerkSite

    print("\n== CivicClerk (Lacey) ==")
    site = CivicClerkSite(
        "https://laceywa.portal.civicclerk.com", place="lacey", state_or_province="wa"
    )
    try:
        assets = site.scrape(download=False)
        print(f"assets found: {len(assets)}")
    except Exception as exc:  # pragma: no cover - live network spike, not test code
        print(f"FAILED: {type(exc).__name__}: {exc}")
        print(
            "Expected as of 2026-08-17: CivicClerkSite scrapes an ASP.NET "
            "WebForms page (looks for a __VIEWSTATE hidden input) that "
            "Lacey's current portal no longer serves; it now runs the SPA "
            "front-end backed by the OData API this toolkit's own "
            "CivicClerkConnector (PR #4) uses directly."
        )


def check_municode() -> None:
    from civic_scraper.runner import Runner, ScraperError

    print("\n== Municode (Tumwater) ==")
    runner = Runner()
    try:
        runner.scrape(
            start_date=str(datetime.date.today()),
            end_date=str(datetime.date.today()),
            site_urls=["https://tumwater-wa.municodemeetings.com"],
        )
    except ScraperError as exc:
        print(f"FAILED (expected): {exc}")
        print(
            "civic-scraper's URL dispatch only recognizes `civicplus`/"
            "`AgendaCenter` URLs (a different CivicPlus product) and the "
            "unrelated DigitalTowPath platform. It has no scraper at all "
            "for the municodemeetings.com Drupal product this toolkit's "
            "MunicodeConnector targets."
        )


if __name__ == "__main__":
    check_legistar()
    check_civicclerk()
    check_municode()
