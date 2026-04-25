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
- **SirsiCheckouts** — granular ILS checkout data (branch × patron type × shelving location), stored separately from Entries

---

## How Data Gets In

All imports go through the `/upload` page. The system auto-detects the file type by reading the sheet name or header row. Files can be uploaded in any order — each importer upserts its specific metrics without overwriting data from other importers.

---

## Import Procedure — File by File

### 1. SIRSI Checkouts by Shelving Location

**Where to get it:** SIRSI ILS → report "Checkouts by Branch and Shelving Location"

**File naming example:** `Checkouts by Branch and Shelving Location - August 2025.xlsx`

**Format:**
- Single sheet, two sections separated by a `Trans Stat Command Desc: Renew Item` header
- Section 1: Charge Item Part B (checkouts)
- Section 2: Renew Item (renewals)
- Columns: `Trans Stat Station Library | Trans Stat User Profile Name | Trans Stat Home Location | Number of Checkouts`
- Header rows identify year (`Trans Stat Year: 2025`) and month (`Trans Stat Month: 8`)

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

**Format:**
- Single sheet, paged by Station Library (the branch where the card was physically registered)
- Each page section opens with a header: `Trans Stat Station Library: YCL-FM`
- Data columns: `Trans Stat Month | Trans Stat User Library | Trans Stat User Profile Name | Count (Trans Stat Id)`
- Year is in a header row near the top: `Trans Stat Year: 2025`
- Month is **not** in a header — it comes from column 0 of the data rows (e.g. `12` for December)
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

**Where to get it:** Manually compiled Excel workbook

**File naming example:** `non-SIRSI423.xlsx`, `statsonly423.xlsx`

**Format:**
- Sheet must be named `Branch Stats`
- Required columns: `Month Num` (or `Month`), `BRANCH`, `Year`
- All other columns are matched to metrics via the column name map in `import_excel.py`

**Key columns and what they map to:**

| Excel Column | Metric |
|---|---|
| `Gate Count` | Gate Count |
| `PC Reservations` | PC Reservations |
| `WiFi - Unique Sessions` | WiFi - Unique Sessions |
| `External Party Library Room Use` | External Party Library Room Use |
| `Curbside` | Curbside |
| `ILL - Sent (Main ONLY)` | ILL - Sent (Main ONLY) |
| `ILL - Received (Main ONLY)` | ILL - Received (Main ONLY) |
| `ICLs - Sent (MAIN ONLY)` | ICLs - Sent (Main ONLY) |
| `ICLs - Received (MAIN ONLY)` | ICLs - Received (Main ONLY) |
| `Total Prints per Month` | Total Prints per Month |
| `I2: ONSITE Sessions 0-5` through `VIRTUAL Attendance General Interest` | Programming metrics |
| `I21: NUMBER OF OUTREACH ACTIVITIES Conducted` | Number of Outreach Activities Conducted |
| `Outreach Attendance (YCL Internal)` | Outreach Attendance |
| `I22: TOTAL # TAKE & MAKES...` | Take & Makes / Other Passive Program Participants |
| `I23: NUMBER OF STAFF TAKING TRAINING` | Number of Staff Taking Training |
| `I24: NUMBER OF HOURS STAFF ATTENDED TRAINING` | Number of Hours Staff Attended Training |
| `1-on-1 Total for Month` | 1-on-1 Total for Month |
| `Locker Circulation` | Locker Circulation |

**What it writes:** All of the above metrics per branch per month → Branch Stats

**How detected:** Sheet named `Branch Stats` inside the workbook

---

### 4. Online Stats Excel

**Where to get it:** Manually compiled Excel workbook

**File naming example:** `onlin423.xlsx`

**Format:**
- Sheet must be named `Online Stats`
- Required columns: `Month Num` (or `Month`), `Year`
- No branch column — these are system-wide metrics

**Key columns:** `yclibrary.org - web sessions`, `ychistory.org - views`, `Dial A Story - CALLS`, `Beanstack - Sessions`, `LibraryCalendar - Sessions`, `Facebook Followers`, `Instragram - Subscribers`, `YouTube - Views`, etc.

**What it writes:** All online/social metrics system-wide per month → Online Stats

**How detected:** Sheet named `Online Stats` inside the workbook

---

### 5. Princh Print Export

**Where to get it:** Princh print management portal → export report

**File naming example:** `princh-export_2026-02-01_2026-02-28.xlsx`

**Format:**
- Columns include: `From`, `To`, `Location`, `Printer Name`, `Letter color pages`, `Letter monochrome pages`, `Legal color pages`, `Legal monochrome pages`, `Ledger color pages`, `Ledger monochrome pages`
- One row per printer per date range
- Location strings matched to branches by substring (e.g. "Lake Wylie" matches "York County Public Library - Lake Wylie")
- Year/month extracted from the `From` date column

**What it writes:** Sum of all page columns per branch per month → `Total Prints per Month` in Branch Stats

**How detected:** Header row contains `Letter color pages` or (`Location` + `Documents` + `From`)

---

### 6. Door Counter Export

**Where to get it:** Door counter management portal

**File naming example:** `daily_door_count.xlsx`

**Format:**
- Columns: `(blank)`, `Location Name`, `Record Date`, `Ins`, `Outs`
- One row per location per hour
- Location names matched exactly: `Clover Library`, `Fort Mill Library`, `Lake Wylie Library`, `Main - Rock Hill Library`, `York Library`
- Date is a datetime object; year/month extracted from it

**What it writes:** Sum of `Ins` per branch per month → `Gate Count` in Branch Stats

**How detected:** Header row contains `Location Name`

---

### 7. Quarterly Reference Stats (QRS)

**Where to get it:** Manually compiled Excel workbook

**File naming example:** `QRSver2.xlsx`

**Format:**
- Sheet named `Qrtly Ref Stats` or `Sheet1`
- Columns: `Year`, `Quarter`, `Month`, `Branch or Location`, `Total # of Transactions for the Week`
- Multiple rows per branch/quarter are summed together

**What it writes:** `Total Transactions for the Week` per branch per quarter → Quarterly Reference Stats

**How detected:** Sheet named `Qrtly Ref Stats` or `Sheet1` with matching metric column

---

## Verifying an Import

After each upload the results page shows:
- **Created** — new entries added
- **Updated** — existing entries that had metrics merged in
- **Warnings** — unrecognised branch names or format issues (check these)

To verify a specific entry worked, go to `/entries` and filter by the month and branch. All metrics that should have values for that source file should show numbers, not dashes.

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
