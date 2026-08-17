# Phase 5 — `civic-scraper` evaluation and build-vs-reuse decision

Status: **done**. Source: `IMPLEMENTATION_PLAN.md` Phase 5; idea #32
research entry #80 (2026-08-10), which recommended evaluating
`biglocalnews/civic-scraper` (PyPI: `civic-scraper`, v1.1.0 as of
2026-08-17) as a possible acquisition-layer base before building or
extending any more connectors.

## Decision

**Diverge, with a documented reason: keep this toolkit's own three native
connectors (`legistar.py`, `civicclerk.py`, `municode.py`) as the
acquisition layer. Do not adopt `civic-scraper` as a dependency or base
class for any of the three pilot jurisdictions.**

This is not a rejection of `civic-scraper` as a project — its commit and
release feeds remain registered on idea #32 (ratings 5 and 4) precisely
because per-vendor scraper breakage is real and worth tracking upstream.
It is a finding, evaluated live against this toolkit's three specific
pilot cities on 2026-08-17, that `civic-scraper` currently provides **less
coverage, not more**, for all three:

| Jurisdiction | Platform | `civic-scraper` result (live, 2026-08-17) | This toolkit's connector |
|---|---|---|---|
| Olympia | Legistar | **Works**, but document-links only: 14 agenda/minutes URLs found for a 14-day window, no item/action/vote data | `LegistarConnector`: same 14-day window plus structured `EventItem`/`action_name`/`votes`/coverage table straight from the JSON API (Phase 2, live-verified against research entry #80's figures) |
| Lacey | CivicClerk | **Fails** — `ValueError: not enough values to unpack` scraping for a `__VIEWSTATE` hidden field that the current portal doesn't serve | `CivicClerkConnector` (PR #4): calls the live OData API directly (`Events`, `GetMeetingFileStream`), unaffected by the front-end's HTML |
| Tumwater | Municode (`municodemeetings.com`) | **Unsupported** — `ScraperError: No scraper found`; `civic-scraper`'s URL dispatch only recognizes CivicPlus's *AgendaCenter* product and an unrelated DigitalTowPath platform, not this Drupal-based Meetings product | `MunicodeConnector` (Phase 4): 9 `bc-*` bodies, 25 meetings, crawl-delay-respecting PDF hash change detection, live-verified |

Reproducible via `scripts/phase5_civic_scraper_eval.py` (dev-only spike
script, not part of the installed package or test suite — see
"Evaluation method" below).

## Evidence (live, 2026-08-17)

### Legistar (Olympia) — works, but shallower than our connector

```
$ python scripts/phase5_civic_scraper_eval.py   # Legistar section
assets found: 14
  2026-08-17 'Planning Commission' agenda https://olympia.legistar.com/View.ashx?M=A&ID=1374800...
  2026-08-17 'Finance Committee' agenda https://olympia.legistar.com/View.ashx?M=A&ID=1378109...
  ...
```

`civic-scraper`'s `LegistarSite` scrapes the public **InSite** HTML
calendar (`olympia.legistar.com`), not the `webapi.legistar.com` JSON API
this toolkit's connector uses. It correctly finds agenda/minutes
documents, but the `Asset` model it returns has no field for item-level
actions, votes, or roll-call flags — the toolkit's core differentiator
per research entry #80 and the Phase 2 coverage table. Using it here would
be a straight downgrade for a platform we already have full API coverage
of.

One undocumented gotcha found in the process: `LegistarSite.__init__`'s
`timezone` keyword defaults to `None`, but omitting it raises an opaque
`pytz.exceptions.UnknownTimeZoneError: None` from deep inside the
underlying `legistar-scraper` dependency — not mentioned in
`civic-scraper`'s CLI `--help` or README. Worth knowing if this project
ever does reach for `civic-scraper` directly.

### CivicClerk (Lacey) — broken against the live site

```
$ python scripts/phase5_civic_scraper_eval.py   # CivicClerk section
FAILED: ValueError: not enough values to unpack (expected 1, got 0)
```

Traceback bottoms out at `civic_scraper/platforms/civic_clerk/site.py`,
`_paginate()`:

```python
(payload["__VIEWSTATE"],) = tree.xpath("//input[@name='__VIEWSTATE']/@value")
```

`__VIEWSTATE` is a classic ASP.NET WebForms postback field. Lacey's
current CivicClerk portal (`laceywa.portal.civicclerk.com`) is a modern
SPA front-end backed by the OData v1 API documented in research entry #80
and used directly by this toolkit's `CivicClerkConnector` — it doesn't
serve that field. `civic-scraper`'s CivicClerk scraper targets an older
CivicClerk UI generation and is not currently usable against this pilot
city at all.

### Municode (Tumwater) — no scraper exists for this product

```
$ python scripts/phase5_civic_scraper_eval.py   # Municode section
FAILED (expected): No scraper found for https://tumwater-wa.municodemeetings.com
```

`civic_scraper.runner.Runner._get_site_class_name()` only matches two
patterns: a URL containing `civicplus` or `AgendaCenter` (CivicPlus's
*AgendaCenter* agenda-publishing product), or `DigitalTowPathSite.can_scrape()`
(also `False` for this URL). `civic-scraper` ships a `civic_scraper.platforms.civic_plus`
module, but it targets a different, older CivicPlus product than the
Drupal-based "Municode Meetings" product Tumwater and (per research entry
#80) the other target platform actually runs. There is no code path in
`civic-scraper` v1.1.0 that reaches `municodemeetings.com` at all — this
confirms research entry #80's original finding that Municode is HTML-only
with no reusable scraper available, rather than a gap this evaluation
could close.

## Evaluation method

`civic-scraper==1.1.0` was installed as an ad hoc dependency in a
throwaway venv (`pip install civic-scraper`; it is **not** added to
`pyproject.toml` — see "Why not keep it as a dependency" below) and run
three ways against this toolkit's exact three pilot jurisdictions:

1. `civic_scraper.platforms.legistar.site.Site` directly against
   `https://olympia.legistar.com` (14-day window, no download).
2. `civic_scraper.platforms.civic_clerk.site.CivicClerkSite` directly
   against `https://laceywa.portal.civicclerk.com`.
3. The public `civic-scraper scrape --url https://tumwater-wa.municodemeetings.com`
   CLI entry point (and, for confirmation, the `Runner` class directly),
   since Municode isn't reachable via any platform-specific class without
   going through the URL dispatcher.

`scripts/phase5_civic_scraper_eval.py` reproduces all three calls in one
script for anyone re-running this evaluation later (e.g., to check
whether `civic-scraper`'s CivicClerk scraper has been fixed upstream).

## Why not keep it as a dependency

`civic-scraper` is not added to `pyproject.toml`, not even as an optional
extra, because none of the three live results above would replace or
strengthen an existing connector: Legistar coverage would regress, and
CivicClerk/Municode aren't usable at all right now. Adding a dependency
that isn't wired into any connector and isn't exercised by the test suite
would be dead weight. If a future connector for a `civic-scraper`-native
platform (e.g., a `civicplus`/AgendaCenter or PrimeGov site, per the
toolkit's suggested-children list) is built, this decision should be
revisited for that specific platform — this finding is scoped to Olympia,
Lacey, and Tumwater as they exist today, not a blanket verdict on
`civic-scraper`.

## Recommendation for Phase 6+

Proceed with the toolkit's own connectors as the acquisition layer for
all three pilot jurisdictions. Continue watching the `civic-scraper`
commits/releases feeds already registered on idea #32 (rating 5/4) — if
its CivicClerk scraper is updated to target the current SPA/API, or a
Municode/Drupal-Meetings scraper is added upstream, that would be worth a
follow-up evaluation. No action needed against this toolkit's code today.
