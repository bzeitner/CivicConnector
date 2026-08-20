"""Phase 7: run the coverage scorecard against the toolkit's pinned
fixtures and print the resulting table plus the kill/scope decision, so the
numbers recorded in `PHASE7_SCORECARD.md` are reproducible.

Offline by design (same rationale as `tests/test_scorecard.py`): the
scorecard's single-snapshot measures don't need a live call to demonstrate,
and the two poll-history measures (`pct_meetings_detected_early`,
`median_lag_to_structured_action`) require multi-poll history this toolkit
doesn't collect yet (no storage layer -- see `civicconnector/diff.py` and
`civicconnector/scorecard.py`'s module docstrings), so they are reported as
"not yet measured" rather than run against a fabricated poll history here.

Usage:

    python scripts/phase7_scorecard_run.py
"""

from __future__ import annotations

import json
from pathlib import Path

from civicconnector.connectors.legistar import parse_event_item
from civicconnector.scorecard import format_scorecard_table, jurisdiction_scorecard, kill_scope_decision

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def main() -> None:
    legistar_items = [
        parse_event_item(i, meeting_native_id="7259")
        for i in json.loads((FIXTURES_DIR / "legistar_eventitems.json").read_text())
    ]
    civicclerk_events = json.loads((FIXTURES_DIR / "civicclerk_events_council.json").read_text())["value"]

    rows = [
        jurisdiction_scorecard(
            "olympia-legistar",
            meetings=[],
            items=legistar_items,
            votes=[],  # no connector produces Vote records yet -- see scorecard.py docstring
            document_coverage=True,  # Phase 2: agenda_url from the API, live-verified
        ),
        jurisdiction_scorecard(
            "lacey-civicclerk",
            meetings=[],
            items=[],  # CivicClerkConnector.get_items() always returns [] -- Phase 3 finding
            votes=[],
            document_coverage=True,  # Phase 3: GetMeetingFileStream plain text, live-verified
        ),
        jurisdiction_scorecard(
            "tumwater-municode",
            meetings=[],
            items=[],  # MunicodeConnector.get_items() always returns [] -- Phase 4 (out of scope)
            votes=[],
            document_coverage=True,  # Phase 4: agenda PDF downloaded and hashed, live-verified
        ),
    ]

    print(json.dumps(format_scorecard_table(rows), indent=2, default=str))

    decision = kill_scope_decision({row.jurisdiction_id: row.document_coverage for row in rows})
    print(f"\nkill/scope decision: {decision}")


if __name__ == "__main__":
    main()
