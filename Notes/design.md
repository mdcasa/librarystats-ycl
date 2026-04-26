# Library Stats — System Design

## What the System Is

Library Stats is a Flask web app (hosted on Railway, PostgreSQL in production) that tracks monthly, quarterly, and annual statistics across all YCL library branches. Data comes from multiple sources and is consolidated into a single browsable database.

---

## Data Model

- **Categories** — the types of stats (Branch Stats, Online Stats, Quarterly Reference Stats)
- **Metrics** — individual fields within a category (Gate Count, WiFi Sessions, etc.), grouped and ordered
- **Branches** — physical locations (Clover, Fort Mill, Lake Wylie, Rock Hill, York, Outreach/Bookmobile, plus Locker sub-branches kept separate)
- **Entries** — one record per branch/month/category combination
- **EntryValues** — the actual numbers, linked to an Entry and a Metric
- **SirsiCheckouts** — granular ILS checkout data (branch x patron type x shelving location), stored separately from Entries

---

## How Data Gets In

All imports go through the `/upload` page. The system auto-detects the file type by reading the sheet name or header row. Files can be uploaded in any order — each importer upserts its specific metrics without overwriting data from other importers.

For metrics not covered by uploaded files, staff use the **Manual Entry** form at `/enter/manual`.

---

## Manual Entry Form (`/enter/manual`)

The manual entry form lets staff enter data for a selected month without uploading a file. It has three tabs:

### Tab 1 — Branch Stats

Shows all active Branch Stats metrics **except** those sourced from uploads. Metrics excluded from this tab (controlled by `_UPLOAD_SOURCED_METRICS` in `app.py`):

| Metric | Source |
|---|---|
| Gate Count | Door counter upload |
| New Library Card Registrations, Adult | SIRSI registration upload |
| New Library Card Registrations, Juvenile | SIRSI registration upload |
| New Library Card Registrations, Total | SIRSI registration upload |
| Total Branch Circulation | SIRSI checkout upload |
| Hotspots Circulation | SIRSI checkout upload |
| ILL - Sent (Main ONLY) | ILL/ICL tab (see below) |
| ILL - Received (Main ONLY) | ILL/ICL tab (see below) |
| ICLs - Sent (Main ONLY) | ILL/ICL tab (see below) |
| ICLs - Received (Main ONLY) | ILL/ICL tab (see below) |

Each branch appears as an accordion panel. Panels that already have data for the selected month are automatically expanded.

### Tab 2 — Online Stats

System-wide online/social media metrics (not branch-specific). All active Online Stats metrics appear here.

### Tab 3 — ILL / ICL (Main only)

ILL and ICL data is entered only for the Rock Hill (Main) branch. The tab is split into two groups:

- **Interlibrary Loans (ILL):** ILL - Sent (Main ONLY), ILL - Received (Main ONLY)
- **Interlibrary Cooperative Loans (ICL):** ICLs - Sent (Main ONLY), ICLs - Received (Main ONLY)

Input field names use the prefix `illicl_m{metric_id}`. On POST, these values are saved to the Rock Hill branch's Branch Stats entry for the selected month (upserted — existing values are overwritten, missing ones are created).

**Why ILL/ICL live in Rock Hill's Branch Stats:** These metrics are collected only at the Main (Rock Hill) branch. Storing them in Branch Stats keeps all branch-level data in one category and avoids a separate entry type.

### History

Before April 2026, ILL and ICL had separate routes (`/enter/ill`, `/enter/icl`) using a dedicated `main_only_entry.html` template. These were removed and consolidated into the third tab of the main manual entry form. The `main_only_entry.html` template remains on disk but no route points to it.

---

## Import Procedure — File by File

### 1. SIRSI Checkouts by Shelving Location

**Where to get it:** SIRSI ILS → report "Checkouts by Branch and Shelving Location"

**File naming example:** `Checkouts by Branch and Shelving Location - August 2025.xlsx`

**Sample file:** `Data files/Circulation/Checkouts by Branch and Shelving Location - August 2025.xlsx`

**Format:**
- Single sheet, two sections separated by a `Trans Stat Command Desc: Renew Item` header
- Section 1: Charge Item Part B (checkouts)
- Section 2: Renew Item (renewals)
- Columns: `Trans Stat Station Library | Trans Stat User Profile Name | Trans Stat Home Location | Number of Checkouts`
- Header rows identify year (`Trans Stat Year: 2025`) and month (`Trans Stat Month: 8`)
- ILS codes in Station Library column: `YCL-BK`, `YCL-CL`, `YCL-CL-LOC`, `YCL-FM`, `YCL-FM-LOC`, `YCL-LW`, `YCL-LW-LOC`, `YCL-RH`, `YCL-RH-LOC`, `YCL-YK`, `YCL-YK-LOC` (plus `YCL` system-wide, which is skipped)

**What it writes:**
- `Total Branch Circulation` (checkouts + renewals) per branch → Branch Stats
- `Hotspots Circulation` (A-HOTSPOT shelving location checkouts only) per branch → Branch Stats
- Locker branches (`YCL-CL-LOC`, `YCL-FM-LOC`, etc.) stored as separate branch entries
- All granular rows also stored in `SirsiCheckouts` table for detailed reporting

**How detected:** Title cell contains `Checkouts by Branch and Shelving Location`

---

### 2. SIRSI New Library Users (Registrations)

**Where to get it:** SIRSI ILS → report "Number of New Library Users by Branch and Patron Type"

**File naming example:** `Number of New Library Users by Branch and Patron Type - December 2025.xlsx`

**Sample file:** `Data files/Registration/Number of New Library Users by Branch and Patron Type - December 2025.xlsx`

**Format:**
- Single sheet, paged by Station Library (the branch where the card was physically registered)
- Each page section opens with a header: `Trans Stat Station Library: YCL-FM`
- Data columns: `Trans Stat Month | Trans Stat User Library | Trans Stat User Profile Name | Count (Trans Stat Id)`
- Year is in a header row near the top: `Trans Stat Year: 2025`
- Month is **not** in a header row — it comes from column 0 of the data rows (e.g. `12` for December)
- `Trans Stat User Library` = the patron's **home branch** (ILS code, e.g. `YCL-FM`)

**How counting works:**
The importer ignores which branch the card was registered at (Station Library) and instead counts by **User Library** — the patron's home branch. This gives "new patrons belonging to each branch" regardless of where they physically registered. Rows with `Total` or header text in any column are skipped.

**Patron profile classification:**
- Adult: `ADULT`, `A-NONRES`, `INST-TEACH`, `TEEN`, `COLLEGE`, `HOMEBOUND`
- Juvenile: `JUVENILE`, `J-INTERNET`, `J-RESTRICT`, `JR-NONRES`
- Any other profile (e.g. `PRGMNG`, `STAFF-PERS`) is ignored

**Locker locations:** Locker station pages (e.g. `YCL-FM-LOC`) appear in the file but User Library in those rows is always the parent branch (`YCL-FM`), so counts roll up to the parent branch naturally.

**What it writes:**
- `New Library Card Registrations, Adult` per branch → Branch Stats
- `New Library Card Registrations, Juvenile` per branch → Branch Stats
- `New Library Card Registrations, Total` (adult + juvenile) per branch → Branch Stats

**How detected:** Title cell contains `Number of New Library Users`

---

### 3. Branch Stats Excel (non-SIRSI monthly data)

**Where to get it:** Manually compiled Excel workbook (staff fill this in each month)

**File naming example:** `non-SIRSI423.xlsx`, `statsonly423.xlsx`

**Sample file:** `Data files/manual/non-SIRSI423.xlsx` — covers Jan 2024 through early 2026, 201 rows, all branches

**Format:**
- Sheet must be named `Branch Stats`
- 51 columns; required: `Month` (col 0), `BRANCH` (col 1), `Year` (col 49)
- There is NO separate `Month Num` column — col 0 contains full month names (`January`, `February`, etc.)
- Branch names are uppercase in the file (`ROCK HILL`, `CLOVER`, `FORT MILL`, `LAKE WYLIE`, `YORK`, `OUTREACH/BOOKMOBILE`) — the branch lookup handles case variants and trailing spaces automatically
- `YCL (System Wide)` rows appear in the file but are skipped by the importer
- All metric columns matched to metrics by exact header name via `BRANCH_STATS_MAP` in `import_excel.py`
- Safe to upload even if SIRSI data already exists for that month — importer upserts each metric individually

**Complete column map (51 columns):**

| Col | Excel Header | Metric |
|---|---|---|
| 0 | `Month` | *(period — month name)* |
| 1 | `BRANCH` | *(branch)* |
| 2 | `Gate Count` | Gate Count |
| 3 | `PC Reservations` | PC Reservations |
| 4 | `WiFi - Unique Sessions` | WiFi - Unique Sessions |
| 5 | `External Party Library Room Use` | External Party Library Room Use |
| 6 | `Curbside` | Curbside |
| 7 | `ILL - Sent (Main ONLY)` | ILL - Sent (Main ONLY) |
| 8 | `ILL - Received (Main ONLY)` | ILL - Received (Main ONLY) |
| 9 | `ICLs - Sent (MAIN ONLY)` | ICLs - Sent (Main ONLY) |
| 10 | `ICLs - Received (MAIN ONLY)` | ICLs - Received (Main ONLY) |
| 11 | `Total Prints per Month` | Total Prints per Month |
| 12 | `I2:  ONSITE Sessions 0-5` | ONSITE Sessions 0-5 |
| 13 | `I3:   ONSITE Sessions 6-11` | ONSITE Sessions 6-11 |
| 14 | `I4: ONSITE Sessions 12-18` | ONSITE Sessions 12-18 |
| 15 | `I5:   ONSITE Sessions 19+` | ONSITE Sessions 19+ |
| 16 | `I6:  ONSITE Sessions GENERAL INTEREST` | ONSITE Sessions General Interest |
| 17 | `ONSITE Attendance 0-5` | ONSITE Attendance 0-5 |
| 18 | `ONSITE Attendance 6-11` | ONSITE Attendance 6-11 |
| 19 | `ONSITE Attendance 12-18` | ONSITE Attendance 12-18 |
| 20 | `ONSITE Attendance 19+` | ONSITE Attendance 19+ |
| 21 | `ONSITE Attendance General Interest` | ONSITE Attendance General Interest |
| 22 | `OFFSITE Sessions 0-5` | OFFSITE Sessions 0-5 |
| 23 | `OFFSITE Sessions 6-11` | OFFSITE Sessions 6-11 |
| 24 | `OFFSITE Sessions 12-18` | OFFSITE Sessions 12-18 |
| 25 | `OFFSITE Sessions 19+` | OFFSITE Sessions 19+ |
| 26 | `OFFSITE Sessions General Interest` | OFFSITE Sessions General Interest |
| 27 | `OFFSITE Attendance 0-5` | OFFSITE Attendance 0-5 |
| 28 | `OFFSITE Attendance 6-11` | OFFSITE Attendance 6-11 |
| 29 | `OFFSITE Attendance 12-18` | OFFSITE Attendance 12-18 |
| 30 | `OFFSITE Attendance 19+` | OFFSITE Attendance 19+ |
| 31 | `OFFSITE Attendance General Interest` | OFFSITE Attendance General Interest |
| 32 | `VIRTUAL Sessions 0-5` | VIRTUAL Sessions 0-5 |
| 33 | `VIRTUAL Sessions 6-11` | VIRTUAL Sessions 6-11 |
| 34 | `VIRTUAL Sessions 12-18` | VIRTUAL Sessions 12-18 |
| 35 | `VIRTUAL Sessions 19+` | VIRTUAL Sessions 19+ |
| 36 | `VIRTUAL Sessions General Interest` | VIRTUAL Sessions General Interest |
| 37 | `VIRTUAL Attendance 0-5` | VIRTUAL Attendance 0-5 |
| 38 | `VIRTUAL Attendance 6-11` | VIRTUAL Attendance 6-11 |
| 39 | `VIRTUAL Attendance 12-18` | VIRTUAL Attendance 12-18 |
| 40 | `VIRTUAL Attendance 19+` | VIRTUAL Attendance 19+ |
| 41 | `VIRTUAL Attendance General Interest` | VIRTUAL Attendance General Interest |
| 42 | `I21: NUMBER OF OUTREACH ACTIVITIES Conducted` | Number of Outreach Activities Conducted |
| 43 | `Outreach Attendance (YCL Internal)` | Outreach Attendance |
| 44 | `I22: TOTAL # TAKE & MAKES and OTHER PASSIVE PROGRAM PARTICIPANTS` | Take & Makes / Other Passive Program Participants |
| 45 | `I23: NUMBER OF STAFF TAKING TRAINING` | Number of Staff Taking Training |
| 46 | `I24: NUMBER OF HOURS STAFF ATTENDED TRAINING` | Number of Hours Staff Attended Training |
| 47 | `1-on-1 Total for Month` | 1-on-1 Total for Month |
| 48 | `Email Address` | *(ignored)* |
| 49 | `Year` | *(period)* |
| 50 | `Locker Circulation` | Locker Circulation |

**How detected:** Sheet named `Branch Stats` inside the workbook

---

### 4. Online Stats Excel

**Where to get it:** Manually compiled Excel workbook (staff fill this in each month)

**File naming example:** `onlin423.xlsx`

**Sample file:** `Data files/manual/onlin423.xlsx` — covers Jul 2025 through early 2026, 41 rows, system-wide

**Format:**
- Sheet must be named `Online Stats`
- 28 columns; required: `Month Num` (col 0), `Year` (col 27)
- Col 0 is `Month Num` — contains numeric month values (1–12)
- No branch column — all metrics are system-wide
- Two column headers contain typos in the Excel file; the importer maps them correctly

**Complete column map (28 columns):**

| Col | Excel Header | Metric |
|---|---|---|
| 0 | `Month Num` | *(period)* |
| 1 | `Month` | *(period label)* |
| 2 | `yclibrary.org - web sessions` | yclibrary.org - Web Sessions |
| 3 | `ychistory.org - views` | ychistory.org - Views |
| 4 | `patchworktales.org  - views` | patchworktales.org - Views |
| 5 | `Dial A Story - CALLS` | Dial A Story - Calls |
| 6 | `Dial A Story - VIEWS` | Dial A Story - Views |
| 7 | `DSpace - Views` | DSpace - Views |
| 8 | `Beanstack - Sessions` | Beanstack - Sessions |
| 9 | `LibraryCalendar - Sessions` | LibraryCalendar - Sessions |
| 10 | `LibGuides - Sessions` | LibGuides - Sessions |
| 11 | `DigitalLearn.org - Sessions` | DigitalLearn.org - Sessions |
| 12 | `DigitalLearn.org - Completed Courses` | DigitalLearn.org - Completed Courses |
| 13 | `LOTE4Kids - Stories Watched` | LOTE4Kids - Stories Watched |
| 14 | `LOTE4Kids - Actvitities` *(typo in Excel)* | LOTE4Kids - Activities |
| 15 | `LOTE4Kids - Logins` | LOTE4Kids - Logins |
| 16 | `Youtube - Subscribers` | YouTube - Subscribers |
| 17 | `YouTube - Views` | YouTube - Views |
| 18 | `YouTube - Hours Watched` | YouTube - Hours Watched |
| 19 | `YCL News - Subscriber` | YCL News - Subscribers |
| 20 | `Website Messages` | Website Messages |
| 21 | `YCL - App - Users` | YCL App - Users |
| 22 | `YCL - App - Sessions` | YCL App - Sessions |
| 23 | `Facebook Followers` | Facebook Followers |
| 24 | `Instragram - Subscribers` *(typo in Excel)* | Instagram - Subscribers |
| 25 | `YouTube Uploads` | YouTube Uploads |
| 26 | `Dial A Story Uploads` | Dial A Story Uploads |
| 27 | `Year` | *(period)* |

**How detected:** Sheet named `Online Stats` inside the workbook

---

### 5. Princh Print Export

**Where to get it:** Princh print management portal → export report

**File naming example:** `princh-export_2026-02-01_2026-02-28.xlsx`

**Sample file:** `Data files/Printing/princh-export_2026-02-01_2026-02-28.xlsx`

**Format:**
- Columns: `From`, `To`, `Location`, `Printer Name`, `Number of orders`, `Documents`, `Revenue - At desk`, `Revenue - Electronic`, `Currency`, `Letter color pages`, `Letter monochrome pages`, `Legal color pages`, `Legal monochrome pages`, `Ledger color pages`, `Ledger monochrome pages`
- One row per printer per date range
- Location strings matched to branches by substring, case-insensitive (e.g. `York County Public Library - Lake Wylie` matches `lake wylie`)
- Year/month extracted from the `From` date column (string `2026-02-01` or datetime)
- Page columns summed: Letter color + Letter mono + Legal color + Legal mono + Ledger color + Ledger mono

**What it writes:** Total pages per branch per month → `Total Prints per Month` in Branch Stats

**How detected:** Header row contains `Letter color pages`, or contains all of `Location`, `Documents`, `From`

---

### 6. Door Counter Export

**Where to get it:** Door counter management portal

**File naming example:** `daily_door_count.xlsx`

**Sample file:** `Data files/daily_door_count.xlsx`

**Format:**
- Columns: `(blank)`, `Location Name`, `Record Date`, `Ins`, `Outs`
- One row per location per hour of the day
- Location names matched exactly to branch names via `DOOR_COUNT_BRANCH_MAP` in `import_excel.py`:
  - `Clover Library` → Clover
  - `Fort Mill Library` → Fort Mill
  - `Lake Wylie Library` → Lake Wylie
  - `Main - Rock Hill Library` → Rock Hill
  - `York Library` → York
- Date is a Python datetime object; year/month extracted from it
- Only `Ins` column is used (entries, not exits)

**What it writes:** Sum of `Ins` per branch per month → `Gate Count` in Branch Stats

**How detected:** Any cell in first 3 rows contains `Location Name`

---

### 7. Quarterly Reference Stats (QRS)

**Where to get it:** Google Forms export (staff submit weekly desk tally counts each quarter)

**File naming example:** `QRSver2.xlsx`

**Sample file:** `Data files/manual/QRSver2.xlsx` — covers Q1-Q3 2025 and into 2026, ~1000 rows

**Format:**
- Sheet named `Sheet1` (Google Forms export format — do not rename)
- Columns: `Timestamp`, `Quarter`, `Month`, `Branch or Location`, `Total # of Transactions for the Week`, `Year`
- `Timestamp` is the Google Forms submission time — not imported, just present
- `Quarter` values accepted: `Q1`, `Q2`, `Q3`, `Q4`, `Quarter 1`, `1`, etc.
- `Month` values: full month names (`January`, `June`, `October`)
- Multiple rows for the same branch/quarter/month are **summed** — each row is one week's tally

**Branches in the file and how they map:**

| File Value | Maps To |
|---|---|
| `Clover` | Clover |
| `Fort Mill` | Fort Mill |
| `Lake Wylie` | Lake Wylie |
| `York` | York |
| `Outreach / Bookmobile` | Outreach/Bookmobile (alias) |
| `Rock Hill - Circulation` | Rock Hill - Circulation (desk branch) |
| `Rock Hill - Reference` | Rock Hill - Reference (desk branch) |
| `Rock Hill - YA` | Rock Hill - YA (desk branch) |

**What it writes:** `Total Transactions for the Week` (summed per branch/quarter/month) → Quarterly Reference Stats

**How detected:** Sheet named `Qrtly Ref Stats` or `Sheet1` containing a `Total # of Transactions for the Week` column

---

## One-Time Historical Data Loads

Some files are not meant to be uploaded through the web UI — they are run once via a Python script to seed historical data directly into the production database.

### How to run a one-time import

From the project root (with `.env` loaded so it hits the production PostgreSQL database):

```bash
python3 -c "
from dotenv import load_dotenv
load_dotenv()
import openpyxl
from app import app, db
from import_excel import do_import

wb = openpyxl.load_workbook('Data files/manual/your_file.xlsx', data_only=True)
with app.app_context():
    results = do_import(wb)
    for r in results:
        print(r['sheet'], r.get('created',0), 'created', r.get('updated',0), 'updated')
        for w in r.get('warnings', []): print('  WARNING:', w)
"
```

### Historical loads completed

| File | Date Loaded | Result |
|---|---|---|
| `Data files/manual/non-SIRSI423.xlsx` | 2026-04-26 | 165 Branch Stats entries created, covering Jan 2024 – Mar 2026 (all branches, all non-SIRSI metrics) |

### Verifying after a one-time load

Query the database directly:

```bash
python3 -c "
from dotenv import load_dotenv
load_dotenv()
from app import app, db
from models import Entry, Category
with app.app_context():
    cat = Category.query.filter_by(name='Branch Stats').first()
    entries = Entry.query.filter_by(category_id=cat.id).all()
    print(f'Total entries: {len(entries)}')
    from collections import Counter
    for (y,m), n in sorted(Counter((e.year,e.month) for e in entries).items()):
        print(f'  {y}-{m:02d}: {n}')
"
```

---

## Verifying an Upload

After each upload the results page shows:
- **Created** — new entries added
- **Updated** — existing entries that had metrics merged in
- **Warnings** — unrecognised branch names or format issues (always check these)

To verify a specific entry, go to `/entries`, filter by month and branch, and confirm the metrics from that file show numbers rather than dashes.

---

## Locker Branches

Locker circulation (`YCL-CL-LOC`, `YCL-FM-LOC`, `YCL-LW-LOC`, `YCL-RH-LOC`, `YCL-YK-LOC`) are treated as **separate branches** in the DB, not rolled into the parent branch totals. This prevents double-counting.

---

## Dashboard

Shows the most recent month with circulation data as the "current" month, so it does not go blank if data for the latest calendar month has not been uploaded yet.

---

## Known Issues Fixed

### Importer skipping existing entries (fixed 2026-04-25)

**Problem:** The SIRSI checkout import runs first and creates a Branch Stats entry for each branch/month with just the circulation totals. When the Branch Stats Excel file was uploaded afterward, the importer saw the entry already existed and skipped it entirely — so WiFi, PC reservations, programs, registrations, and everything else never got stored.

**Fix:** Both `import_branch_stats` and `import_online_stats` now upsert instead of skip. They find or create the entry, then add or overwrite only the specific metrics from that file.

### Double-counting system-wide circulation (fixed)

The SIRSI import previously wrote a system-wide circulation entry in addition to per-branch entries. This was removed to prevent totals from being counted twice.

### Princh importer branch matching (fixed)

Princh export location strings are matched to branches via substring search (case-insensitive), handling variations in how location names appear in the export.

### New Library Users month detection (fixed)

Added fallback month detection for SIRSI New Library Users reports where the month is in the data column rather than the report header.
