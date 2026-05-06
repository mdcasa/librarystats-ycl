# OldConversion Historical Import — Design Document

**Purpose**: Load historical monthly Branch Stats data from `Data files/OldConversion/` into the existing database, back-filling pre-2018 months and filling gaps through FY2022-23 without overwriting any already-existing values.

---

## 1. Source Files

| File | Sheet(s) | FY Coverage | Format |
|------|----------|-------------|--------|
| `Annual stats FY 15-16-17.xls` | `FY15-16`, `FY16-17 Stats` | FY2015-16, FY2016-17 | Dedicated |
| `Annual stats FY 17-18.xls` | `FY17-18 Stats` | FY2017-18 | Dedicated |
| `Annual stats FY 18-19.xls` | `FY18-19 Stats` | FY2018-19 | Dedicated |
| `ANNUAL Stats 19-20.xls` | `18-19 to 19-20 Comparison p.1` | FY2019-20 (newer year) | Comparison |
| `20-21 ANNUAL STATS.xls` | `19-20 to 20-21 Comparison p.1` | FY2020-21 (newer year) | Comparison |
| `21-22 Annual Stats.xls` | `20-21 to 21-22 Comparison p.1` | FY2021-22 (newer year) | Comparison |
| `22-23 Annual Stats.xls` | `21-22 to 22-23 Comparison p.1` | FY2022-23 (newer year) | Comparison |
| `FY2024_Jul2023_Dec2023.xlsx` | (to be inspected) | Jul–Dec 2023 partial | TBD |

> **Import only the newer year** from each comparison file (e.g. from the "19-20 to 20-21" file, import only FY2020-21 rows). The older year in those files will have been the newer year in the preceding file.

---

## 2. File Format Types

### 2a. Dedicated Format (FY15–FY19)

Layout per sheet:
- **Row 1**: Header — branch names in columns 3–9 (columns vary by year; inspect dynamically)
- **Rows 2–N**: One metric per row. Column 0 = metric label. Columns 3–14 = monthly values (July–June). Column 15 = annual total (skip this column).
- Month index: col 3 = July (month 7), col 4 = Aug (8), … col 14 = June (6 of next calendar year).

Branch columns may not be in a fixed order — read the header row to map column index → branch name.

### 2b. Comparison Format (FY19–FY23)

Layout per sheet:
- **Section headers**: Rows where col 0 matches pattern `r"^\d{2}-\d{2}\s+.+"` (e.g. `"20-21 Door Count"`). The two-digit prefix identifies the FY label (`20-21` → FY starting July 2020). Each section header introduces a new metric block.
- **Data rows**: Immediately following the section header. Col 0 = branch name. Cols 1–12 = monthly values (July–June). Col 13 = annual total (skip).
- The sheet interleaves two FY blocks for each metric. Only process sections whose label prefix matches the newer year.
- Programs data may appear on a separate sub-sheet (e.g. `Programs` tab). Inspect the specific file — these sheets may use only the current year's data without a year prefix.

---

## 3. FY-to-Calendar-Year Mapping

Fiscal year label `"XX-YY"` → start calendar year = `2000 + XX`.

| Month position (0-indexed) | Month name | Calendar month | Calendar year |
|---|---|---|---|
| 0 | July | 7 | start_year |
| 1 | August | 8 | start_year |
| 2 | September | 9 | start_year |
| 3 | October | 10 | start_year |
| 4 | November | 11 | start_year |
| 5 | December | 12 | start_year |
| 6 | January | 1 | start_year + 1 |
| 7 | February | 2 | start_year + 1 |
| 8 | March | 3 | start_year + 1 |
| 9 | April | 4 | start_year + 1 |
| 10 | May | 5 | start_year + 1 |
| 11 | June | 6 | start_year + 1 |

```python
MONTH_OFFSETS = [7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6]

def fy_col_to_year_month(fy_start_year: int, col_index: int):
    """col_index: 0=July, 1=Aug, ..., 11=June"""
    month = MONTH_OFFSETS[col_index]
    year = fy_start_year if col_index < 6 else fy_start_year + 1
    return year, month
```

---

## 4. Metric Mapping

Old spreadsheet label → DB metric name. The script must look up `Metric.query.filter_by(name=<db_name>).first()` against the Branch Stats category.

| Old label (may vary slightly) | DB metric name | Notes |
|-------------------------------|---------------|-------|
| `Door Count` | `Gate Count` | |
| `New Library Cards` | `New Library Card Registrations, Total` | Total only; old files don't split Adult/Juvenile |
| `PC Reservations` | `PC Reservations` | |
| `Wi-Fi Sessions` / `WiFi Sessions` | `WiFi - Unique Sessions` | |
| `Circs-Cataloged Materials` + `Circs-Uncataloged Materials` | `Total Branch Circulation` | Sum both rows together per branch per month. Do NOT include `INHOUSE` row. |
| `Age 0-5 Sessions` | `ONSITE Sessions 0-5` | |
| `Age 0-5 Participation` | `ONSITE Attendance 0-5` | |
| `Age 6-11 Sessions` | `ONSITE Sessions 6-11` | |
| `Age 6-11 Participation` | `ONSITE Attendance 6-11` | |
| `Age 12-18 Sessions` | `ONSITE Sessions 12-18` | |
| `Age 12-18 Participation` | `ONSITE Attendance 12-18` | |
| `Age 18+ Sessions` / `Adult Sessions` | `ONSITE Sessions 19+` | |
| `Age 18+ Participation` / `Adult Participation` | `ONSITE Attendance 19+` | |
| `Mixed Ages Sessions` / `All Ages Sessions` | `ONSITE Sessions General Interest` | approximate match |
| `Mixed Ages Participation` / `All Ages Participation` | `ONSITE Attendance General Interest` | approximate match |

> **`Total Branch Circulation` and `New Library Card Registrations` are in `_SIRSI_METRIC_NAMES`** — the existing `import_branch_stats` route will refuse to overwrite them. The historical import script must write directly to the DB (not via the Flask route).

---

## 5. Branch Name Normalization

Old spreadsheet names → DB branch name. Use `Branch.query.filter_by(name=<db_name>).first()`.

| Old name(s) | DB branch name |
|-------------|---------------|
| `Rock Hill` / `Rock Hill (SDD Site)` | `Rock Hill` |
| `Clover` | `Clover` |
| `Fort Mill` | `Fort Mill` |
| `Lake Wylie` | `Lake Wylie` |
| `York` | `York` |
| `Bookmobile` | `Bookmobile/Outreach` |
| `Outreach` | `Bookmobile/Outreach` |
| `Bookmobile/Outreach` | `Bookmobile/Outreach` |

> If older files list `Bookmobile` and `Outreach` as **separate rows**, **sum** them into a single value for `Bookmobile/Outreach` before writing.

> **Never write to locker branches, desk sub-locations, or `YCL (System Wide)`** from this script.

---

## 6. Skip Logic (Critical)

Before writing any value, check whether an `EntryValue` already exists:

```python
entry = Entry.query.filter_by(
    category_id=bs_cat.id,
    branch_id=branch.id,
    year=year,
    month=month
).first()

if entry:
    ev = EntryValue.query.filter_by(
        entry_id=entry.id,
        metric_id=metric.id
    ).first()
    if ev is not None:
        continue  # already populated — skip
```

If the `Entry` row does not exist at all, create it (this is the case for all pre-July-2018 months). If it exists but the specific `EntryValue` is missing, add it. If the `EntryValue` exists with any value (even 0), skip.

---

## 7. Script Architecture

```
load_dotenv()   # must call before db init to hit Supabase, not local SQLite

for each file in OldConversion/:
    determine fy_start_year and format_type (dedicated vs comparison)
    open with xlrd (for .xls) or openpyxl (for .xlsx)
    
    for each relevant sheet:
        parse header row → map column index to branch name
        
        if dedicated format:
            read rows sequentially
            accumulate circ_cataloged[branch][col] and circ_uncatalogued[branch][col]
            on each metric row, for each branch column × 12 month columns:
                look up metric, branch, year, month
                apply skip logic
                write EntryValue
        
        if comparison format:
            scan for section headers matching newer FY label
            for each matching section:
                read subsequent branch-name rows
                for each branch × 12 month columns:
                    apply same logic

    db.session.commit() after each file (or each sheet)
    print summary: N written, M skipped
```

---

## 8. Circulation Special Handling

Old files break circulation into:
- `Circs-Cataloged Materials` (physical items with catalog records)
- `Circs-Uncataloged Materials` (ephemeral/uncataloged)
- `INHOUSE` circulation (in-library use, not included in standard circ)

The correct mapping is `Cataloged + Uncataloged = Total Branch Circulation` (omit INHOUSE).

Since these are two separate rows, the parser must buffer them and sum before writing:

```python
# accumulate
if 'cataloged' in label_lower:
    circ_cat[branch_col] = value
elif 'uncataloged' in label_lower:
    circ_uncat[branch_col] = value
elif 'inhouse' in label_lower:
    pass  # skip

# when both are seen for the same branch/month
total_circ = (circ_cat.get(col, 0) or 0) + (circ_uncat.get(col, 0) or 0)
```

---

## 9. Dependencies

- **`xlrd`** — required for `.xls` files (old Excel format). Check `requirements.txt`; add if missing.
  - `pip install xlrd` — supports `.xls` only (not `.xlsx`). For `.xlsx` use openpyxl.
- **`openpyxl`** — already in requirements; used for `.xlsx`.
- Standard imports: `os`, `re`, `flask`, `models` (`Entry`, `EntryValue`, `Branch`, `Category`, `Metric`), `db`.

---

## 10. Implementation Notes

### Script location
`/workspaces/librarystats/load_old_conversion.py` — standalone script, not a Flask route.

### Run pattern
```bash
cd /workspaces/librarystats
python load_old_conversion.py --dry-run   # print what would be written, no DB writes
python load_old_conversion.py             # live run
```

### Priorities (implement in this order)
1. `Total Branch Circulation` (most important for trend reports)
2. `Gate Count`
3. `New Library Card Registrations, Total`
4. Programming metrics (`ONSITE Sessions/Attendance` by age group)
5. `PC Reservations`, `WiFi - Unique Sessions`

### Recommended test approach
1. Run for a single file (FY2017-18) and a single branch (Rock Hill) first.
2. Verify written values against the source spreadsheet manually.
3. Check Monthly Board Report for that year to confirm the numbers surface correctly.
4. Then run for all files.

### Dry-run output format
```
[DRY RUN] Would write: Rock Hill | 2017-07 | Gate Count | 4821
[SKIP]    Rock Hill | 2018-03 | Gate Count — value already exists (5102)
[DRY RUN] Would create Entry: Rock Hill | Branch Stats | 2016-08
```

---

## 11. Known Gaps / Edge Cases

- **`FY2024_Jul2023_Dec2023.xlsx`**: Partial year (Jul–Dec 2023 only). Inspect this file separately — format may differ. Much of this period may already be loaded from `YCL_All_Stats_2019_2024.xlsx`.
- **Comparison files only import the newer year**: The older year in each comparison file is already covered by the preceding comparison file. Only exception: if a file is the oldest (no earlier file), consider importing both years from it.
- **`submitted_by` field**: Set to `'OldConversion Import'` when creating new Entry rows so the source is auditable.
- **Zero vs null**: If a cell is empty, skip it (don't write 0). Only write cells with a numeric value > 0.
- **Bookmobile + Outreach separate rows**: Sum them before writing to avoid double-write conflict. Use a buffer dict keyed by `(branch_name, col_index)` and resolve after seeing all rows.
- **Column count variation**: Dedicated format files may not all have exactly 15 data columns. Read column count from the header row rather than assuming.
