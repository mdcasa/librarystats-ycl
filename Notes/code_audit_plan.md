# Code & Data Audit Plan

**Purpose:** Systematically verify that the app code is correct and that uploaded statistical data lands in the DB accurately.

---

## Step 1 — Importer Audit (`import_excel.py`)

For each importer function, verify:
- Column/cell references match the actual Excel format (no off-by-one offsets)
- Branch ILS codes used match the branches actually in the DB
- Metric names written to the DB match those defined in `seed_data.py`
- Upsert logic: find-or-create entry, then set/overwrite only that importer's metrics (no duplication)
- Edge cases: missing sheet, blank rows, unexpected column headers — are errors surfaced or silently swallowed?

Importers to check (all in `import_excel.py`):
- `import_sirsi_checkouts` — Total Branch Circulation, Hotspot Circulation
- `import_sirsi_registrations` — new card registrations
- `import_branch_stats` — general monthly Branch Stats upload
- `import_qrs` — Quick Reference Stats (desk sub-locations)
- `import_programs` — programming stats (onsite/offsite/virtual)
- `import_annual_comparables` — Annual Comparables importer (added recently)
- Any others present in the file

---

## Step 2 — Report Aggregation Audit (`app.py`)

For every route that sums Branch Stats, confirm it excludes:
- Locker branches (`*Lockers`, `is_desk=False` but ILS code `YCL-XX-LOC`)
- Desk sub-locations (`is_desk=True`): Rock Hill - Circulation, Rock Hill - YA
- `YCL (System Wide)`
- `Administration` (if present)

Key routes to check:
- `/reports/monthlystats`
- `/reports/fiscalreport`
- `/reports/trendovertime`
- `/reports/yoy` (year-over-year)
- `/reports/annualsurvey`
- Dashboard data endpoints

Memory note: Missing this exclusion is a known past source of inflated totals. See `memory/feedback_branch_filtering.md`.

---

## Step 3 — Run Existing Smoke Test

```bash
cd /workspaces/librarystats
python test_monthly.py
```

Verify status 200 and expected report sections are present.

---

## Step 4 — Data Integrity Spot Checks (live DB)

Requires `.env` with `DATABASE_URL` pointing at Supabase.

Checks to run:
1. **Duplicate entries** — any branch/month/year/category combination with more than one Entry row
2. **Orphaned EntryValues** — EntryValues whose entry_id points to a non-existent Entry
3. **Known totals verification** — compare DB aggregates for FY24 and FY25 against verified totals stored in `memory/project_impact_report_verified.md`
4. **ICL/ILL data** — confirm known-bad months are still the only anomalies (see `memory/project_icl_data_issues.md`)
5. **Circulation gap months** — Jul 2024–Jun 2025 are known undercounts (charges only, no renewals); verify no other months share that pattern unexpectedly

---

## Step 5 — Security Spot Check

Run `/security-review` (Claude Code skill) on the current branch to catch any upload-route vulnerabilities, unvalidated file paths, or auth gaps introduced by recent changes.

---

## Notes for the Reviewer

- Read `Design/DesignPrinciples.md` before making any code changes found during the audit.
- Do not fix and audit at the same time — log issues first, then fix.
- All memory files are in `/home/codespace/.claude/projects/-workspaces-librarystats/memory/`.
- The verified FY24/FY25 totals in memory are the ground truth for Step 4.
