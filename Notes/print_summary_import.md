# Print Summary (LPTOne / Princh) Importer — 2026-07-02

Change log for the "Branch Print Summary" import work, in case we need to
revisit or roll it back.

## What was requested

Import `Data files/June/LPT1/YCL_Print_Summary_June2026.xlsx` into the system
per branch, per month, without deleting/overwriting existing data. Track
**everything** in the sheet (Printed Jobs, Printed Pages, Printed Cost).
"PRINCH" data should be labelled "Prints" and combined with the existing series.

## The file format

- Sheet name: `Branch Print Summary`
- A **title row at the top** carries the period, e.g. `('June', 2026, ...)`
- Header row (below the title): `Branch | Printed Jobs | Printed Pages | Printed Cost`
- One row per branch: `York`, `Rock Hill (RH)`, `Lake Wylie (LW)`, `Clover`, `Fort Mill (FM)`
- Source system is **LPTOne** (hence the `LPT1` folder); the vendor's mobile
  "Princh" prints are believed to already be rolled into these LPTOne totals,
  so no separate Princh merge is needed.

## Metric mapping (decided with the user)

| Spreadsheet column | Branch Stats metric | Notes |
|---|---|---|
| Printed Pages | `Total Prints per Month` | **Existing** metric — old Princh data + new LPTOne data form one continuous series ("combine") |
| Printed Jobs  | `Printed Jobs` | **New** metric (integer) |
| Printed Cost  | `Printed Cost` | **New** metric (decimal) |

There was never a metric or category literally named "Princh"; the print metric
was already `Total Prints per Month`. So "rename PRINCH → Prints" landed as: use
"Prints" in the UI label and keep Printed Pages flowing into the existing metric.

## Code changes (all on branch `v4`)

- **`import_excel.py`**
  - `import_print_summary(ws, branch_lookup, year, month)` — parses the sheet,
    matches branches via `PRINTING_BRANCH_MAP` substring logic (handles the
    `(RH)` / `(LW)` / `*` suffixes), upserts each column as its own Branch Stats
    metric. Skips the `TOTAL` row. Returns `(created, updated, period_set, warnings)`.
  - `parse_period_from_sheet(rows)` — reads month/year from the title row.
  - `parse_period_from_filename(filename)` — fallback: parses `June2026`,
    `2026-06`, etc. from the file name.
  - `_ensure_metric(...)` — find-or-create a Metric row (no migration tool in
    this project), so `Printed Jobs` / `Printed Cost` are created idempotently
    on first upload.
  - `detect_and_import(wb, year_override, filename)` — now takes `filename`;
    routes any sheet with a `Branch` + `Printed Pages` header to the new
    importer. **Period precedence: sheet title row → filename → Year field.**
  - Constants: `PRINT_SUMMARY_COL_MAP`, `PRINT_SUMMARY_NEW_METRICS`, `_MONTH_NAMES`.
- **`app.py`**
  - `/upload` passes `filename=f.filename` to `detect_and_import`.
  - `Printed Jobs` / `Printed Cost` added to `_UPLOAD_SOURCED_METRICS` so they
    stay **off the manual entry/edit form** (like Total Prints, Gate Count, etc.).
  - Upload flash message now reports **created AND updated** counts (previously a
    re-upload said "0 new records added", which read like a failure).
- **`seed_data.py`** — `Printed Jobs` (integer) and `Printed Cost` (decimal)
  added to Branch Stats for fresh installs.
- **`templates/upload.html`** — the old "Printing … coming soon" mock-up row is
  now a live **Prints** entry; added a note that the period comes from the sheet
  title row / file name.

## Commits

- `8d0fcd9` Feat: import LPTOne/Princh Branch Print Summary per branch, per month
  (also carried a pre-existing DigitalLearn.org metric removal)
- `64a0e1a` Feat: read print summary month/year from the sheet's title row
- `6f3d76d` Fix: upload flash message counts updates, not just new records

## Production actions taken

- June 2026 print data was loaded into **production Supabase** (once via a direct
  script when the Railway deploy hadn't yet gone live, then re-confirmed by the
  user's `/upload` at 18:37 — idempotent, so no duplication).
- Values loaded (per branch, June 2026): matches the spreadsheet exactly.
  e.g. Rock Hill: Pages 10778 / Jobs 2985 / Cost 1893.10.

## Where the data lives / how to view it

- All of a branch's monthly metrics share **one** Branch Stats entry per
  branch/month. Prints are attached to the same June 2026 entries that hold the
  SIRSI, door-count and PCRES numbers — not a separate category.
- View: Browse Data → Category = Branch Stats, Year = 2026 → open a June entry →
  **Access & Usage** group. June 2026 entry IDs: RH 2268, York 2270, Fort Mill
  2265, Clover 2263, Lake Wylie 2260.
- The **Edit** form hides these metrics by design (they are upload-sourced).

## How to roll back

- Per-upload undo: Upload Data page → Recent Imports → **Undo** on the
  `YCL_Print_Summary…` log entry.
- The two new metrics (`Printed Jobs`, `Printed Cost`) are safe to leave; they
  only appear where data exists. To remove them entirely, delete the metric rows
  and revert the code commits above.

## Gotchas

- The sheet has **no per-column date**; the period must be in the title row or
  the file name.
- Re-uploading is safe (upsert) — it updates, never duplicates.
- Rock Hill was closed for renovations Oct 2025–Apr 2026; June 2026 is after
  reopening, so its print numbers are expected to be present.
