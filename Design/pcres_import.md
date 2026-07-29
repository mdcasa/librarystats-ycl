# PCRES — PC Reservation Usage Reports → Single Spreadsheet

How to consolidate the monthly **PC Reservation PC Usage Report** PNGs (one per
branch) into a single spreadsheet with one total row per branch. Written up after
doing it for June 2026 so it can be repeated each month.

---

## What the source files are

- Location: `Data files/<Month>/PCRES/`
- One **PNG screenshot** per branch, produced by the **EnvisionWare** PC
  Reservation reporting module ("PC Reservation PC Usage Report — Organized By PC Area").
- Filenames are inconsistent (spaces, dashes, case vary). June 2026 had:
  - `PCRES-CL.png` → Clover
  - `PCRes -FM.png` → Fort Mill
  - `PCRES-LW.png` → Lake Wylie
  - `PCRes-RH.png` → Rock Hill
  - `PCRES-YK.png` → York
- Only 5 branches report PCRES. **Outreach/Bookmobile has no PC reservation
  report** and is not included.

### What each report contains
Each PNG shows a "Totals" table for the report period (e.g. `6/1/2026 to 6/30/2026`)
broken down by **PC Area**, with a final **TOTALS** row. PC Area names differ per
branch (PUBLIC, EXPRESS, CHILDREN, PUBLIC PCs, Computer Lab, Genealogy Area,
ScanPro 3000s, etc.). Columns:

| Column | Meaning | Format |
|---|---|---|
| PC Area | Sub-area within the branch | text |
| Total Uses | Session count | integer |
| Total Time | Cumulative time | `H:MM` (hours:minutes) — can exceed 24h, e.g. `1166:43` |
| Average Session | Avg minutes/session | decimal |

---

## How to parse them

The PNGs are read visually (they are screenshots, not data files) — open each one
and transcribe the **TOTALS row** for each branch. Only the branch-level TOTALS are
needed; the per-PC-Area breakdown is discarded per the current requirement.

**Watch-outs when transcribing:**
- `Total Time` is `H:MM`, not a decimal. Keep it as text so `1166:43` doesn't get
  mangled into a date/time by the spreadsheet.
- Average Session is not summable/averagable across areas without weighting — just
  copy the branch's own TOTALS value; don't recompute.
- Match each file to the right branch by the CL/FM/LW/RH/YK suffix, not file order.

---

## Output spreadsheet

- Saved as `Data files/<Month>/PCRES/PC_Usage_<Month><Year>.xlsx`
  (June 2026 → `PC_Usage_June2026.xlsx`).
- One header block (report title + period), then **one row per branch** using that
  branch's TOTALS: `Branch | Total Uses | Total Time (H:MM) | Average Session (min)`.
- **No grand-total / all-branches row** — explicitly not wanted.
- Built with `openpyxl` (already a project dependency). Column widths and a shaded
  header row for readability; nothing else fancy.

### June 2026 result (for reference)

| Branch | Total Uses | Total Time | Avg Session |
|---|---|---|---|
| Clover | 242 | 88:32 | 21.950 |
| Fort Mill | 672 | 327:23 | 29.231 |
| Lake Wylie | 265 | 121:00 | 27.396 |
| Rock Hill | 1589 | 1166:43 | 44.055 |
| York | 491 | 180:51 | 22.100 |

---

## Loading into the database

PC Reservations is **already a Branch Stats metric** (`seed_data.py`, group
"Access & Usage", metric id 5 in prod). It has continuous monthly history, so once
a month is loaded it appears automatically in historical + Trend Over Time reports
alongside prior PC Reservation data — **no report or model changes are needed.**

Loading goes through the normal web uploader at **`/upload`** (yclstats.org), which
auto-detects the format via `detect_and_import` in `import_excel.py`.

### The importer — `import_pc_reservations` (`import_excel.py`)
- Detected when the workbook has a sheet named **`PC Reservations`**, or any sheet
  whose header row contains **`Branch`** plus **`Total Uses`** (or `PC Reservations`).
- Reads columns `Branch | Year | Month | Total Uses` (a title block above the header
  is tolerated; extra columns and `TOTALS` rows are ignored).
- Maps branch names via `PCRES_BRANCH_MAP`, sums `Total Uses` per
  (branch, year, month), and **upserts** into the PC Reservations metric using the
  shared `_upsert_branch_stat` helper.

### Why re-uploading is safe (no duplicates, history preserved)
`_upsert_branch_stat` finds-or-creates the Branch Stats entry for that
(branch, year, month) and overwrites only the PC Reservations value. It never
inserts duplicate rows and never touches other months or other metrics. Verified
locally: a second upload of the same file reports **0 created / 5 updated** and the
row count stays at 5. The `/upload` page also records an ImportLog with an **Undo**
and a before/after comparison.

## The upload file

- `PC_Reservations_Upload_June2026.xlsx` — the machine-readable file to upload.
  Sheet **`PC Reservations`**, header row 1 = `Branch | Year | Month | Total Uses`,
  one row per branch (Year=2026, Month=6, Total Uses from the PNG TOTALS).
- `PC_Usage_June2026.xlsx` — the human-readable summary (kept for reference; not the
  upload file).

## Repeat recipe (each month)

1. Drop the new month's branch PNGs into `Data files/<Month>/PCRES/`.
2. Open each PNG, read the branch's **TOTALS** → `Total Uses`.
3. Build `PC_Reservations_Upload_<Month><Year>.xlsx` with `openpyxl`: sheet
   `PC Reservations`, columns `Branch | Year | Month | Total Uses`, one row per branch.
4. At **yclstats.org/upload**, upload that file. Confirm the result shows
   `PC Reservations — 5 created` (or `updated` if re-run) and check the comparison.
5. First-load check: a brand-new month should report all *created*; if it reports
   *updated*, the month already had data — verify before proceeding.
