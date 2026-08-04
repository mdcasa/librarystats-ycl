# Incident: FY24-25 vs FY25-26 Comparison Report Verification — 2026-08-04

## What happened

`Output files/FY2024-25_vs_FY2025-26_Comparison.docx` (a manually-authored report comparing
the FY24-25 state survey submission against the live FY25-26 database) was checked for
accuracy against the live DB and the source state-survey spreadsheet. Every figure in all
four tables and the FY24-25 baseline checked out exactly — except two things in the FY25-26
column, both traced to the doc's numbers having gone stale relative to the DB during the
Aug 3-4, 2026 May/June data-repair process (see `import_log` ids 50-68) rather than being
re-pulled after the repairs finished.

## Errors found and fixed

1. **Total circulation, physical items (FY25-26): 846,274 → corrected to 849,813** (▼16.6% →
   ▼16.2%). Traced precisely: Jul 2025-Apr 2026 summed to 681,507 under both the doc's number
   and the live DB — the entire 3,539 gap sat inside May+June 2026, the two months mid-repair
   when the report was likely generated. Confirmed current DB is correct by reconciling against
   the raw `sirsi_checkouts` detail table (exact match).

2. **"43 values recovered" → corrected to "73"** (both the NOTES section and the "FIXED DURING
   THIS REVIEW" callout box). `import_log #53` moved 101 values during its May/June duplicate-
   Entry merge. Checking which of those 101 were actually missing afterward: 30 were restored
   by `import_log #66` (May Total Branch Circulation/Hotspots/Locker/Registrations, 5 branches)
   and 43 more by `import_log #67` (broader May/June restoration) — confirmed zero overlap
   between the two lists, so 73 of 101 were lost, not 43. The doc's "43" only counted `#67` and
   forgot `#66`, despite citing both logs as its source.

3. **WiFi sessions (FY25-26): 57,713 → 57,711** — downstream of the Bookmobile data fix below
   (percentage stayed ▼49.6%, no visible rounding change).

Both docx fixes were applied by editing `word/document.xml` directly (python-docx can't edit
existing files) and validated paragraph-count-equal against the original before replacing it.

## A real DB data-quality bug found and fixed

**Bookmobile/Outreach WiFi - Unique Sessions, Dec 2025 was 2.0** — the branch has no fixed
wifi infrastructure and has recorded 0 every other month since FY2019. The same entry's PC
Reservations was *also* erroneously 2.0 (its only nonzero value in 7+ years of history),
strongly pointing to a column-shift bug in whatever Excel file produced that one row
(`submitted_by = 'Excel Import'`, entry id 900). Corrected to 0.0, logged as `import_log #69`
(undoable via the app's own `/upload` undo UI — see the `ev_updated` format below).

**Also found but NOT fixed (flagged for the user, needs a source file to fix properly):**
42 Branch Stats entries across FY25-26 where `New Library Card Registrations, Total` ≠
Adult + Juvenile. The live importer (`import_new_library_users`, `import_excel.py:1644`)
always writes Total as their sum atomically, so every one of these is a stale Total left over
from a later Adult/Juvenile update (almost certainly downstream of the same Aug 2025
duplicate-Entry-merge saga) that never got recomputed. Now surfaced automatically by the new
"Registration Total Mismatches" check on Admin → Data Integrity Check — see below.

## Code changes: two new automated checks on Admin → Data Integrity Check

Added to `app.py` (`_branch_metric_violations`, `_registration_total_mismatches`, wired into
`admin_data_integrity()`) and `templates/admin/data_integrity.html`:

1. **Branch/Metric Violations** — flags nonzero values for a (branch, metric) pair configured
   in `BRANCH_METRIC_EXCLUSIONS` as something that branch is documented as never tracking.
   Currently just `{'Bookmobile/Outreach': ['WiFi - Unique Sessions']}` — add more pairs here
   as they're discovered (e.g. if a locker branch or desk sub-location turns out to have a
   metric it structurally can't produce).
2. **Registration Total Mismatches** — flags any Branch Stats entry where Adult + Juvenile ≠
   the stored Total for New Library Card Registrations.

Both are FY-scoped like the existing checks (Circulation Reconciliation, Duplicate Entry Rows)
and render as new card sections between "Duplicate Entry Rows" and the collapsed full-detail
table. Tested via `app.test_client()` with a simulated admin session (never enter the app's
own login password into a browser automation tool — see feedback memory).

## A known, NOT fixed, pre-existing data-quality issue: FY2025 and earlier circulation

The public `/public/annual-stats` page (and its sibling internal `/reports/overview`, both
driven by `_overview_fy_stats()` in `app.py`) shows FY2025 Total Circulation as 596,933 —
but the verified state-survey total for FY2025 is 1,014,285. Root cause (numerically
confirmed, not 100% proven from source since the load script/file no longer exists): FY2025's
historical "Total Branch Circulation" only captured **checkouts**, missing **renewals**
entirely. Evidence: 596,933 / 1,014,285 = 58.85%, and the live FY2026 SIRSI checkout table's
own checkouts-only share is 59.2% — a near-exact match. Gate Count for the same year checks
out almost exactly against the state survey (450,395 vs 450,536), so this is isolated to
circulation, not a wholesale historical-data problem.

Likely source: `Data files/annual/YCL_Stats_2025.xlsx`, loaded 2026-04-27 per
`Design/design.md`'s "Historical loads completed" table (84 Branch Stats entries, Jul 2024-Jun
2025) — the file no longer exists locally to confirm directly. The `_SIRSI_METRIC_NAMES`
exclusion guard in `import_branch_stats()` (`import_excel.py:335-344`), which prevents any
non-SIRSI Excel upload from ever overwriting Total Branch Circulation, almost certainly
postdates this load — it protects FY2026-forward data from this exact failure mode but was
never applied retroactively to FY2025.

**Explicitly decided NOT to fix this with a database override**, after discussion: an earlier
plan to write a corrected "Annual Comparables" system-wide entry for FY2025 (matching a
dormant pattern already in `/reports/impact`'s `ac_totals()`) was rejected because it would
create two disagreeing circulation numbers for the same year — the correct one shown on the
overview page, the wrong one still sitting underneath in the 72 monthly entries anyone could
drill into. The user also pointed out the state survey's own "Total Circulation" concept
blends physical + eResources in some contexts, so a from-scratch DB "fix" risked encoding a
different flawed assumption. **Current decision: leave FY2025 circulation as-is on the public
page for now, keep physical and eResources reported as clearly separate figures (as the docx
report already does), and don't paper over the gap with an unreconciled top-line number.**
If this is ever revisited, the right fix is finding a genuine renewals-inclusive source for
FY2016-2025 monthly/per-branch circulation and reloading it — not a top-line override.

## Checklist for verifying/regenerating this kind of comparison report in the future

1. Query every FY25-26-style "computed from the DB" figure **fresh, at the very end**, after
   any in-progress data repair has fully landed — check `ImportLog.query.order_by(id.desc())
   .first()` to confirm no repair is still in flight relative to when the report's numbers were
   pulled.
2. Cross-check any narrative claim that cites a count from a specific `import_log` (e.g. "N
   values recovered") by actually parsing that log's `changes_json`, not by re-typing a
   remembered or partially-summed number — especially when multiple logs jointly did the
   repair (easy to cite all the logs but only count one of them).
3. Reconcile Total Branch Circulation against the raw `sirsi_checkouts` table (now a one-click
   check: Admin → Data Integrity Check) before trusting any circulation total, for any year
   where that table has coverage. It has no coverage before Jul 2025 — a `_circulation_
   reconciliation` mismatch or empty-SIRSI-side result for older years is expected, not a
   fresh bug.
4. Don't assume a percentage change that runs the "wrong direction" from the year's known
   narrative (e.g. a circulation *increase* during a year with an extended headquarters
   closure) is real without checking the definition on both sides of the comparison first —
   that mismatch is usually the tell that two different things are being measured.
