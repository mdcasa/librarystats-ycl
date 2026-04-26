# Annual Survey Dashboard — Design Notes

## What This Is

A dedicated dashboard and data entry system for the SC State Library annual survey data. This is separate from the monthly Branch Stats system because the data is structured completely differently: system-wide only, one row per fiscal year, covering ~130 metrics across 16 sections.

The SC State Library annual survey runs on a fiscal year of **July 1 – June 30**. Report Year 2024 = FY July 2023 – June 2024.

Data is submitted via the Counting Opinions LibPAS portal at sc.countingopinions.com. Historical data (FY2012–FY2024) is tracked in `Data files/annual/Annual Comparables.xlsx`.

---

## Data Model

Two new tables (separate from the monthly Entry/Metric system):

### `annual_survey_metrics`
Defines each metric — created once, not per-year.

| Field | Type | Notes |
|---|---|---|
| `id` | integer | PK |
| `section` | string | Matches the Excel sheet name (e.g. `OPERATIONS`, `CIRC`) |
| `name` | string | Full metric name as used in the SC State Library report |
| `data_type` | string | `integer`, `decimal`, or `text` |
| `sort_order` | integer | Display order |
| `is_auto_calculated` | boolean | True if value is derived from monthly data |
| `auto_calc_note` | string | Human-readable description of the monthly source |

### `annual_survey_values`
One row per metric per fiscal year.

| Field | Type | Notes |
|---|---|---|
| `id` | integer | PK |
| `report_year` | integer | FY end year (e.g. 2024 = Jul 2023 – Jun 2024) |
| `metric_id` | integer | FK to `annual_survey_metrics` |
| `value` | float | Numeric value |
| `value_text` | text | Text value (for text-type metrics like "Yes/No") |
| `is_adjusted` | boolean | True if this value was corrected from the original source |
| `adjustment_note` | text | Describes the original value and why it was changed |

Unique constraint on `(report_year, metric_id)` — one value per metric per year.

---

## Sections (16 total, matching Excel sheet names)

| Section | Metrics | Notes |
|---|---|---|
| OPERATIONS | 7 | Hours, trustees, board meetings, Friends group |
| STAFFING | 20 | FTE counts by credential level, total staff |
| REVENUE | 19 | Millage, county/state/federal/other revenue |
| EXPENSES STAFF | 3 | Salary, benefits, total |
| EXPENSES COLLECTION | 6 | Print, electronic, AV, other materials |
| EXPENSES OPERATIONS | 5 | Furniture, plant, other, totals |
| EXPENSES CAPITAL | 5 | Building, vehicle, equipment, other, total |
| EXPENSES TOTAL | 1 | Grand total operating + capital |
| COLLECTION SIZE | 22 | Physical and electronic items added/removed/held |
| USERS GATE COUNT | 5 | Registered users, gate count, population |
| TECH USE | 3 | Public computers, WiFi sessions, website visits |
| REF MTG RM | 3 | External facility use, reference transactions, 1:1 sessions |
| CIRC | 16 | Physical and electronic circulation by format and age |
| ILL | 2 | ILL provided and received |
| PROGRAMMING | 12 | Sessions and attendance by age group |
| OUTREACH | 3 | Staff trained, training hours, take-and-makes |

---

## Routes

| Route | Function | Description |
|---|---|---|
| `/annual-survey` | `annual_survey_dashboard` | Main dashboard with KPI cards, trend charts, full data table |
| `/annual-survey/<year>/enter` | `annual_survey_enter` | Entry/edit form for a specific fiscal year |
| `/annual-survey/<year>/calculate` | `annual_survey_calculate` | Auto-calculate metrics from monthly data (POST) |

Accessible via **Annual Survey** in the main nav.

---

## Auto-Calculated Metrics

When "Calculate FY[year]" is clicked on the entry form, the system sums the relevant monthly data for the fiscal year (Jul year-1 through Jun year) and writes the results to the annual survey values. Locker branches are excluded from branch-level sums.

| Annual Metric | Monthly Source |
|---|---|
| Annual Library Visits (gate count) | Sum of `Gate Count` (Branch Stats, all non-locker branches) |
| Number of wireless sessions | Sum of `WiFi - Unique Sessions` (Branch Stats) |
| Number of website visits | Sum of `yclibrary.org - Web Sessions` (Online Stats) |
| TOTAL CIRC ALL PHYSICAL | Sum of `Total Branch Circulation` (Branch Stats) |
| Synchronous Pgm Sessions Kids 0-5 | Sum of `ONSITE/OFFSITE/VIRTUAL Sessions 0-5` |
| Synchronous Pgm Sessions Kids 6-11 | Sum of `ONSITE/OFFSITE/VIRTUAL Sessions 6-11` |
| Total Programs 0-11 | Sum of Sessions 0-5 + Sessions 6-11 |
| Total YA Programs for ages 12-18 | Sum of `ONSITE/OFFSITE/VIRTUAL Sessions 12-18` |
| Total Adult Programs for 18+ | Sum of `ONSITE/OFFSITE/VIRTUAL Sessions 19+` |
| Total Gen Audience | Sum of `ONSITE/OFFSITE/VIRTUAL Sessions General Interest` |
| Total of all programs | Sum of all session metrics |
| Children 0 to 11 programs attendance | Sum of all Attendance 0-5 and 6-11 |
| YA 12-18 programs attendance | Sum of all `Attendance 12-18` |
| Adult programs attendance | Sum of all `Attendance 19+` |
| Total General attendance | Sum of all `Attendance General Interest` |
| Total Attendance all programs and all ages | Sum of all attendance metrics |
| Number of staff trained | Sum of `Number of Staff Taking Training` |
| Number of hours of training attended by staff | Sum of `Number of Hours Staff Attended Training` |
| Number of items distributed as take-and-makes | Sum of `Take & Makes / Other Passive Program Participants` |

Auto-calculated fields are shown as read-only in the entry form and are labelled with an "auto" badge. They can only be updated by clicking the Calculate button — not by manual entry.

---

## Data Entry Workflow

### For a completed fiscal year (after June data is in monthly system):
1. Go to **Annual Survey → Enter / Edit FY[year]**
2. Click **Calculate FY[year]** — fills all auto-calculated fields from monthly data
3. Manually enter the remaining fields section by section:
   - USERS GATE COUNT: Registered users, Population
   - CIRC: Juvenile/Adult breakdown, Electronic circ
   - REF MTG RM: External facility use, Reference transactions, 1:1 sessions
   - ILL: Provided and received
   - OPERATIONS: Hours, trustees, board meetings, Friends group
   - STAFFING: All FTE and position counts
   - REVENUE: All revenue sources
   - EXPENSES (all sections): All expenditure figures
   - COLLECTION SIZE: Items added, removed, held
   - TECH USE: Public internet computers (WiFi/website auto-calculated)
4. Click **Save FY[year] Data**

### For future years (ongoing):
- Repeat the same process at the end of each fiscal year (after July entry of June monthly data)
- The ILL data in this system is the **state report total** (all transactions system-wide), not the Rock Hill-only ILL Sent/Received from the monthly form — these are different figures and should be entered manually

---

## Historical Data Load

**File:** `Data files/annual/Annual Comparables.xlsx`
**Script:** `import_annual.py`
**Loaded:** 2026-04-26 — 1,716 values created, covering FY2012–FY2024

To re-run the import (safe to repeat — upserts existing values):
```bash
python3 import_annual.py
```

To add a new year's data from a new version of the Excel file, run the same script — it will update existing values and create new ones.

---

## Data Quality Corrections Applied

All corrections are flagged in the database with `is_adjusted=True` and `adjustment_note` describing the original value and reason. The dashboard displays a warning icon (⚠) on all adjusted values; hovering shows the full note.

| Year | Section | Metric | Original | Corrected | Method |
|---|---|---|---|---|---|
| 2024 | ILL | ILL provided to another library | 92,589 | 55,766 | Average of 2022 (69,373) and 2023 (42,159) |
| 2024 | ILL | ILL received from another library | 114,784 | 80,803 | Average of 2022 (97,217) and 2023 (64,389) |
| 2018 | PROGRAMMING | Total Programs 0-11 | 4,765 | 2,538 | Average of 2017 (2,466) and 2019 (2,609) |
| 2018 | PROGRAMMING | Total YA Programs for ages 12-18 | 921 | 270 | Average of 2017 (195) and 2019 (344) |
| 2018 | PROGRAMMING | Total Adult Programs for 18+ | 6,177 | 1,496 | Average of 2017 (2,252) and 2019 (740) |
| 2018 | PROGRAMMING | Total of all programs | 11,421 | 3,770 | Average of 2017 (4,588) and 2019 (2,953) |
| 2018 | PROGRAMMING | Children 0-11 attendance | 63,184 | 68,046 | Average of 2017 (78,311) and 2019 (57,780) |
| 2018 | PROGRAMMING | YA 12-18 attendance | 11,257 | 8,947 | Average of 2017 (6,845) and 2019 (11,049) |
| 2018 | PROGRAMMING | Adult programs attendance | 12,178 | 7,716 | Average of 2017 (7,734) and 2019 (7,698) |
| 2018 | PROGRAMMING | Total Attendance all programs | 118,040 | 80,860 | Average of 2017 (92,890) and 2019 (68,829) |
| 2013 | USERS GATE COUNT | Annual Library Visits (gate count) | 844,406 | 621,616 | Average of 2012 (669,059) and 2014 (574,173) |
| 2014 | PROGRAMMING | Children 0 to 11 programs attendance | 95,836 | 49,175 | Back-calculated: Total (62,587) − YA − Adult − Gen |
| 2015 | PROGRAMMING | Children 0 to 11 programs attendance | 133,781 | 68,202 | Back-calculated: Total (79,560) − YA − Adult − Gen |
| 2016 | PROGRAMMING | Children 0 to 11 programs attendance | 97,827 | 67,768 | Back-calculated: Total (78,319) − YA − Adult − Gen |

**Reason for corrections:** Data in the original Annual Comparables.xlsx was entered by a staff member using incorrect methodology for several years. The corrected values represent the best available estimate using surrounding years as reference points. The original values are preserved in the `adjustment_note` field in the database.

---

## Key Differences from Monthly Data System

| Aspect | Monthly System | Annual Survey |
|---|---|---|
| Frequency | Monthly | Fiscal year (Jul–Jun) |
| Branch breakdown | Per branch | System-wide only |
| Data entry | Upload files or manual form | Manual entry + auto-calculate |
| Source | SIRSI, door counters, Princh, staff forms | SC State Library survey |
| ILL counting | Rock Hill monthly requests only | All system ILL transactions (different methodology) |
| Circulation | Physical only, by branch | Physical + electronic, all ages |
| Programming | Sessions and attendance by type and age | Same but annual totals only |
