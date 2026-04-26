# Library Stats — System Design

## What the System Is

Library Stats is a Flask web app (hosted on Railway, PostgreSQL in production) that tracks monthly, quarterly, and annual statistics across all YCL library branches. Data comes from multiple sources and is consolidated into a single browsable database.

---

## Branding & UI

The app is branded as **YCL Statistics** (York County Library). All pages use the YCL royal blue color scheme.

**Brand colors (CSS variables in `base.html`):**

| Variable | Hex | Use |
|---|---|---|
| `--ycl-blue` | `#1a4f9e` | Navbar, primary buttons, links, accents |
| `--ycl-blue-dark` | `#153f80` | Hover states |
| `--ycl-blue-light` | `#2563b8` | Lighter accent |
| `--ycl-blue-pale` | `#e8f0fb` | Section header backgrounds, accordion active state |

**Logo:** `static/ycl-logo.png` — the full YCL logo file (`Data files/YCL Logo.png`) copied to `static/` for Flask to serve. Served via `url_for('static', filename='ycl-logo.png')`.
- **Navbar:** rendered white via `filter: brightness(0) invert(1)` (white logo on blue navbar background).
- **Login page:** shown in natural full color — the login card header is white (`background: #fff`) so no filter is applied. The "YCL Statistics" title below the logo is styled in `#1a4f9e`.

**Static files:** Flask's default `static/` folder (project root). `Flask(__name__)` picks this up automatically with no configuration needed.

**Favicon:** `static/ycl-logo.png` is also referenced as the browser tab favicon via `<link rel="icon" type="image/png">`. Modern browsers handle PNG favicons natively — no `.ico` conversion needed.

---

## UI Patterns

### Active nav highlighting
`base.html` sets `request.endpoint` into `ep` and compares against pre-defined endpoint lists (`_enter`, `_data`, `_dash`, `_reports`, `_admin`). The current page's top-level nav item gets `.active-parent` (subtle white tint); the matching dropdown item gets Bootstrap's `.active` class.

### Sticky navbar
The navbar has Bootstrap's `sticky-top` class. It stays visible during scrolling, which matters on long pages like the Annual Survey entry form (16 accordion sections).

### Back-to-top button
A fixed circular button (`#backToTop`) in the bottom-right corner appears after scrolling 400px and scrolls smoothly to the top. Styled with `--ycl-blue`, hidden at page load, toggled by a `scroll` event listener in `base.html`.

### Card hover effect
`.card` has `transition: box-shadow .15s ease` and lifts on hover (`0 4px 14px rgba(0,0,0,.12)`). Applies site-wide automatically.

### Print stylesheet
`@media print` block in `base.html` hides the navbar, footer, buttons, flash alerts, and back-to-top button. Sets body background to white, removes card box-shadows, adds a border, shrinks table font, and colors headings in YCL blue. Used when printing board reports or any page via browser print.

### Empty states
Pages that return no results use the `.empty-state` CSS class (defined in `base.html`) instead of a plain alert. Pattern:
```html
<div class="empty-state">
  <i class="bi bi-calendar-x empty-icon"></i>
  <p>Descriptive message about why there's no data.</p>
  <a href="{{ url_for('upload_data') }}" class="btn btn-outline-primary btn-sm">
    <i class="bi bi-upload me-1"></i>Upload Data
  </a>
</div>
```
Applied to: Monthly Summary, Fiscal Year Totals, Year-over-Year, Cross-tab Heat Map. The Browse Data page already had a similar pattern.

### Warning row highlight
Import results rows with warnings get the `.warning-row` CSS class (`border-left: 4px solid #ffc107`), defined in `base.html`. Warning text is rendered in `#856404` (dark amber) instead of Bootstrap's low-contrast `text-warning` yellow.

### Metric group headers
`.group-header td` in `base.html` styles group header rows in report tables. Uses sentence case (no `text-transform: uppercase`) at `.82rem` for readability. Background is `--ycl-blue-pale`, text is `--ycl-blue`.

### Sidebar labels
`.sidebar-label` (filter form labels, dropdown section headers) is `.8rem` — bumped from `.7rem` for WCAG AA legibility.

### Password reset UI (admin)
The Reset Password card on `/admin/users/<id>/edit` has a yellow left-border header (`border-left: 4px solid #ffc107`, `background: #fff8e1`) to visually distinguish it as a sensitive action. No email flow — admins set the new password directly.

### Admin breadcrumbs
`/admin/users` and `/admin/branches` include a breadcrumb trail (`Admin → [page]`) so admins can navigate back to the Categories & Metrics hub.

### Collapsible Add Category form
The "Add New Category" form on `/admin/categories` is hidden by default behind a Bootstrap collapse toggle. Keeps the page clean when managing existing categories.

### Browse Data — Submitted column
The entries list combines submitted date and username into one column: `DD Mon YYYY · username`. Time-of-day is omitted as it adds no value.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3 |
| Web framework | Flask ≥ 3.0 |
| ORM | Flask-SQLAlchemy ≥ 3.1 |
| Auth | Flask-Login ≥ 0.6.3 |
| Database (production) | PostgreSQL via Railway |
| Database (local dev) | SQLite (`librarystats.db`) |
| WSGI server | gunicorn |
| Excel parsing | openpyxl |
| Environment | python-dotenv |

**Key files:**
- `app.py` — Flask app, all routes, business logic
- `models.py` — SQLAlchemy models (includes `User`)
- `import_excel.py` — all file importers
- `export_excel.py` — Excel export
- `seed_data.py` — initial categories, metrics, and branches (runs once on first boot when DB is empty)
- `requirements.txt` — `Flask`, `Flask-SQLAlchemy`, `Flask-Login`, `psycopg2-binary`, `gunicorn`, `openpyxl`, `python-dotenv`

---

## Git Branching Strategy

| Branch | Purpose |
|---|---|
| `main` | Stable production branch — the version originally deployed to Railway |
| `v2` | Archived copy of the v2-stable state (tagged `v2-stable`) |
| `v3` | Previous active branch (archived) |
| `v4` | Active development branch — currently deployed to Railway |

**Railway is pointed at the `v4` branch.** Auto-deploys on every push to `v4`.

To roll back: in the Railway dashboard, switch the deployment branch back to `v3` or `main`.

To install the Railway CLI (not pre-installed in Codespaces):
```bash
npm install -g @railway/cli
railway login       # opens browser auth
railway link        # links the current directory to the Railway project
```

After linking, run one-time scripts against production:
```bash
railway run python3 import_annual.py
```

---

## Deployment (Railway)

The app is deployed on Railway. On startup, `db.create_all()` runs automatically — no migration tool is used. Schema changes that SQLAlchemy can't handle automatically (e.g. adding a column) are handled with inline `ALTER TABLE` statements inside a try/except in `app.py` at startup.

**Required environment variables:**

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (Railway sets this automatically). Must start with `postgresql://` — the app rewrites `postgres://` automatically. |
| `SECRET_KEY` | Flask session signing key |
| `LOGIN_PASSWORD` | Password for the bootstrap admin account (used only on first boot if no users exist) |
| `LOGIN_USERNAME` | *(Optional)* Username for the bootstrap admin — defaults to `admin` if not set |

**Local development:** Create a `.env` file in the project root with the same variables pointing at the Railway PostgreSQL instance (or omit `DATABASE_URL` to use local SQLite).

---

## Authentication

Individual user accounts managed via Flask-Login. Passwords are hashed with `werkzeug` (`generate_password_hash` / `check_password_hash`). All routes require login except `/login` and `/logout` (enforced by a `before_request` hook).

**User model fields:** `username`, `email`, `password_hash`, `is_active`, `is_admin`

**Roles:**
- `is_admin=True` — full access including user management (`/admin/users`)
- `is_admin=False` — all data entry and reporting routes; no admin panel

**Bootstrap admin:** On first boot, if the `users` table is empty, the app auto-creates one admin account using:
- Username: `LOGIN_USERNAME` env var (defaults to `admin` if not set)
- Password: `LOGIN_PASSWORD` env var

`LOGIN_USERNAME` can be omitted from Railway env vars — the default is `admin`. `LOGIN_PASSWORD` must be set.

After the first user is created, additional accounts are managed via Admin → Users in the nav.

---

## Data Model

Seven tables:

| Table | Purpose |
|---|---|
| `users` | Login accounts — username, hashed password, is_admin, is_active |
| `categories` | Types of stats (Branch Stats, Online Stats, etc.) |
| `metrics` | Individual fields within a category, with group_name for display grouping |
| `branches` | Physical locations; `is_desk=True` for sub-desks like Rock Hill - Circulation |
| `entries` | One record per branch/month(or quarter)/category |
| `entry_values` | The actual numbers, linked to an Entry and a Metric |
| `sirsi_checkouts` | Granular ILS checkout data: branch × patron type × shelving location × month |

**Key model fields:**
- `Entry.month` (1–12) and `Entry.quarter` (1–4) are both nullable — a monthly entry has month set, quarter null, and vice versa
- `Entry.branch_id` is nullable — null means system-wide (used by Online Stats)
- `Metric.group_name` controls section headers in forms and reports
- `Metric.data_type` is `integer`, `decimal`, or `text`
- `Branch.is_desk` — desk-level branches (Rock Hill - Circulation, Rock Hill - YA) are excluded from Branch Stats forms but shown in QRS
- `Branch.is_active=False` hides a branch from all lists (Rock Hill - Reference is deactivated)
- `EntryValue.display_value` — property that formats numbers cleanly (strips trailing `.0`)

---

## Branches (seed data)

Created by `seed_data.py` on first boot. The SIRSI importer also creates branches on the fly if an unrecognised ILS code appears.

| Branch Name | ILS Code | is_desk | Notes |
|---|---|---|---|
| Rock Hill | YCL-RH | No | Main branch |
| Clover | YCL-CL | No | |
| Fort Mill | YCL-FM | No | |
| Lake Wylie | YCL-LW | No | |
| York | YCL-YK | No | |
| Outreach/Bookmobile | YCL-BK | No | Also aliased as `Outreach / BKM`, `Outreach / Bookmobile` |
| YCL (System Wide) | YCL | No | Skipped by importers; excluded from forms |
| Rock Hill - Circulation | — | Yes | QRS desk branch |
| Rock Hill - Reference | — | Yes | Deactivated (`is_active=False`) |
| Rock Hill - YA | — | Yes | QRS desk branch |
| Rock Hill Lockers | YCL-RH-LOC | No | Created by SIRSI importer |
| Clover Lockers | YCL-CL-LOC | No | Created by SIRSI importer |
| Fort Mill Lockers | YCL-FM-LOC | No | Created by SIRSI importer |
| Lake Wylie Lockers | YCL-LW-LOC | No | Created by SIRSI importer |
| York Lockers | YCL-YK-LOC | No | Created by SIRSI importer |

---

## Categories and Metrics (seed data)

Created by `seed_data.py` on first boot if no categories exist. Categories and metrics can also be managed via the Admin UI.

### Branch Stats (monthly, has_branch=True)

| Group | Metric | Type |
|---|---|---|
| Registrations | New Library Card Registrations, Adult | integer |
| Registrations | New Library Card Registrations, Juvenile | integer |
| Access & Usage | Gate Count | integer |
| Access & Usage | PC Reservations | integer |
| Access & Usage | WiFi - Unique Sessions | integer |
| Access & Usage | External Party Library Room Use | integer |
| Access & Usage | Total Prints per Month | integer |
| Circulation | Total Branch Circulation | integer |
| Circulation | Hotspots Circulation | integer |
| Circulation | Curbside | integer |
| Circulation | Locker Circulation | integer |
| ILL / ICL | ILL - Sent (Main ONLY) | integer |
| ILL / ICL | ILL - Received (Main ONLY) | integer |
| ILL / ICL | ICLs - Sent (Main ONLY) | integer |
| ILL / ICL | ICLs - Received (Main ONLY) | integer |
| ONSITE Programming | ONSITE Sessions 0-5 through General Interest (5 metrics) | integer |
| ONSITE Programming | ONSITE Attendance 0-5 through General Interest (5 metrics) | integer |
| OFFSITE Programming | OFFSITE Sessions 0-5 through General Interest (5 metrics) | integer |
| OFFSITE Programming | OFFSITE Attendance 0-5 through General Interest (5 metrics) | integer |
| VIRTUAL Programming | VIRTUAL Sessions 0-5 through General Interest (5 metrics) | integer |
| VIRTUAL Programming | VIRTUAL Attendance 0-5 through General Interest (5 metrics) | integer |
| Outreach | Number of Outreach Activities Conducted | integer |
| Outreach | Outreach Attendance | integer |
| Outreach | Take & Makes / Other Passive Program Participants | integer |
| Staff Training | Number of Staff Taking Training | integer |
| Staff Training | Number of Hours Staff Attended Training | decimal |
| Other | 1-on-1 Total for Month | integer |

### Online Stats (monthly, has_branch=False — system-wide)

Groups: Website, Dial A Story, Other Platforms, DigitalLearn, LOTE4Kids, Social Media, Newsletters & Apps — 25 metrics total. See column map in Import Procedure §4 for full list.

### Quarterly Reference Stats (quarterly, has_branch=True)

Single metric: `Total Transactions for the Week` (integer). Branches are the desk-level branches (Rock Hill - Circulation, Rock Hill - YA) plus all standard branches.

### eResources (monthly, has_branch=False)

Created by seed but not currently used. Metrics: E-Book Circulation, E-Audio Circulation, E-Video Circulation, E-Serials Circulation.

---

## How Data Gets In

All imports go through the `/upload` page. The system auto-detects the file type by reading the sheet name or header row. Files can be uploaded in any order — each importer upserts its specific metrics without overwriting data from other importers.

For metrics not covered by uploaded files, staff use the **Manual Entry** form at `/enter/manual`.

---

## Manual Entry Form (`/enter/manual`)

The manual entry form lets staff enter data for a selected month without uploading a file. It has two tabs:

### Tab 1 — Branch Stats

Shows all active Branch Stats metrics **except** those sourced from uploads or dedicated entry forms. Metrics excluded (controlled by `_UPLOAD_SOURCED_METRICS` in `app.py`):

| Metric | Where to enter |
|---|---|
| Gate Count | Door counter upload |
| New Library Card Registrations, Adult | SIRSI registration upload |
| New Library Card Registrations, Juvenile | SIRSI registration upload |
| New Library Card Registrations, Total | SIRSI registration upload |
| Total Branch Circulation | SIRSI checkout upload |
| Hotspots Circulation | SIRSI checkout upload |
| ILL - Sent (Main ONLY) | `/enter/ill` form |
| ILL - Received (Main ONLY) | `/enter/ill` form |
| ICLs - Sent (Main ONLY) | `/enter/icl` form |
| ICLs - Received (Main ONLY) | `/enter/icl` form |

Each branch appears as an accordion panel. Panels that already have data for the selected month are automatically expanded.

### Tab 2 — Online Stats

System-wide online/social media metrics (not branch-specific). All active Online Stats metrics appear here.

---

## ILL and ICL Entry Forms (`/enter/ill`, `/enter/icl`)

Separate dedicated forms for Interlibrary Loans and Interlibrary Cooperative Loans. Both are Rock Hill (Main branch) only and accessible from the **Enter Data** dropdown in the nav.

- **ILL Entry** (`/enter/ill`) — saves `ILL - Sent (Main ONLY)` and `ILL - Received (Main ONLY)` to Rock Hill's Branch Stats entry for the selected month
- **ICL Entry** (`/enter/icl`) — saves `ICLs - Sent (Main ONLY)` and `ICLs - Received (Main ONLY)` to Rock Hill's Branch Stats entry for the selected month

Both forms use `templates/entries/main_only_entry.html` and upsert values (existing values are overwritten, missing ones are created). The form pre-populates with any existing values for the selected month.

**Why ILL/ICL live in Rock Hill's Branch Stats:** These metrics are collected only at the Main (Rock Hill) branch. Storing them in Branch Stats keeps all branch-level data in one category.

**Historical data note:** ILL/ICL values prior to April 2026 were loaded as a one-time insert from `non-SIRSI423.xlsx` (see One-Time Historical Data Loads). Going forward all ILL/ICL values are entered monthly via these forms.

---

## New Entry / Edit Entry Forms (`/entries/new/<id>`, `/entries/<id>/edit`)

These generic forms (used by "Enter Data → [category]" in the nav) also filter out `_UPLOAD_SOURCED_METRICS` for Branch Stats entries, matching the manual entry form. This prevents staff from accidentally entering values for metrics that are owned by file imports or the dedicated ILL/ICL forms. The filtering applies only to Branch Stats; other categories (Online Stats, Quarterly Reference Stats) show all their metrics.

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

**Current file contents (`QRSver2.xlsx`):** 26 data rows covering 3 quarters:

| Quarter | Month | Year | Notes |
|---|---|---|---|
| Q1 | June | 2025 | 10 rows — Rock Hill Circulation has 3 separate submissions (1,244 + 166 + 2,117 = 3,527 when summed) |
| Q2 | October | 2025 | 8 rows |
| Q3 | January | 2026 | 8 rows |

**Important:** Quarter labels in this file do not follow standard calendar quarters — Q1 = June, Q2 = October, Q3 = January. This is how staff labeled them when submitting via Google Forms. The importer stores whatever quarter value appears in the file without remapping.

**Branches in this file:** Clover, Fort Mill, Lake Wylie, York, Outreach / Bookmobile, Rock Hill - Circulation, Rock Hill - Reference, Rock Hill - YA

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
| `Data files/manual/QRSver2.xlsx` | 2026-04-26 | 24 Quarterly Reference Stats entries created — Q1/Jun 2025, Q2/Oct 2025, Q3/Jan 2026, all 8 branches |
| `Data files/manual/onlin423.xlsx` | 2026-04-26 | 27 Online Stats entries created — Jan 2024 – Mar 2026, system-wide |

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

## Branch Taxonomy

YCL has **6 real service locations**: Rock Hill (Main), Clover, Fort Mill, Lake Wylie, York, and Outreach/Bookmobile. Everything else in the `branches` table is either a desk sub-location, a locker pickup point, or a system-wide placeholder.

| Type | Examples | `is_desk` | Counted as a branch? |
|---|---|---|---|
| Service location | Rock Hill, Clover, Fort Mill, Lake Wylie, York, Outreach/Bookmobile | No | ✅ Yes |
| Locker pickup | Rock Hill Lockers, Clover Lockers, Fort Mill Lockers, Lake Wylie Lockers, York Lockers | No | ❌ No — filtered out |
| Desk sub-location | Rock Hill - Circulation, Rock Hill - YA | Yes | ❌ No — `is_desk=True` excludes them |
| System-wide placeholder | YCL (System Wide) | No | ❌ No — excluded by name |

**Dashboard branch count** (`total_branches` in the index route) uses:
```python
Branch.query.filter(
    Branch.is_active == True,
    Branch.is_desk == False,
    ~Branch.name.ilike('%locker%'),
    Branch.name != 'YCL (System Wide)',
).count()
```
This returns 6 — the five branches plus bookmobile.

**Locker branches** (`YCL-CL-LOC`, `YCL-FM-LOC`, `YCL-LW-LOC`, `YCL-RH-LOC`, `YCL-YK-LOC`) are kept as separate DB branches so their circulation can be tracked independently without being double-counted into the parent branch totals. They are excluded from Branch Stats entry forms, manual entry forms, and branch-count displays. The annual survey auto-calculator also excludes locker branches when summing gate count and other metrics.

**Locker data in line charts (Trend Over Time report):** Locker branch data is merged into the parent branch line. For each real branch, the chart queries both the branch entry and any locker branch whose name starts with the same string (e.g. "Rock Hill Lockers" rolls into "Rock Hill"), summing them for each month. This means the Trend chart always shows 6 lines (the real service locations) with locker circulation already included. Locker branches are also excluded from the branch checkbox selector in the Trend report filter form.

---

## Dashboard

Shows the most recent month with circulation data as the "current" month, so it does not go blank if data for the latest calendar month has not been uploaded yet.

---

## Navigation Structure

The navbar has 6 top-level items (condensed from 8 to reduce crowding):

| Nav item | Type | Contents |
|---|---|---|
| Dashboard | Link | `/` |
| Enter Data | Dropdown | Manual Entry, ILL Entry, ICL Entry, category entry links |
| Data | Dropdown | Upload Data, Browse Data |
| Dashboards | Dropdown | Director's Dashboard, Annual Survey |
| Reports | Dropdown | All 11 report routes |
| Admin | Dropdown | Categories & Metrics, Branches, Users, Import, Export |

Sign Out button is right-aligned (hidden on mobile).

---

## All Routes

### Navigation / Auth
| Route | Function | Description |
|---|---|---|
| `/login` | `login` | Login form (username + password) |
| `/logout` | `logout` | Logs out current user |
| `/` | `index` | Main dashboard |

### Data Entry
| Route | Function | Description |
|---|---|---|
| `/enter/manual` | `manual_entry` | Manual entry form — Branch Stats tab + Online Stats tab |
| `/enter/ill` | `ill_entry` | ILL entry form (Rock Hill only) |
| `/enter/icl` | `icl_entry` | ICL entry form (Rock Hill only) |
| `/entries/new/<category_id>` | `entry_create` | Generic new entry form for any category |
| `/entries/<id>/edit` | `entry_edit` | Edit an existing entry |
| `/entries/<id>/delete` | `entry_delete` | Delete an entry (POST) |

### Browse & View
| Route | Function | Description |
|---|---|---|
| `/entries` | `entries_list` | Browse all entries with filters (category, branch, year) |
| `/entries/<id>` | `entry_view` | View a single entry and all its metric values |

### Upload
| Route | Function | Description |
|---|---|---|
| `/upload` | `upload_data` | Upload any supported Excel file; auto-detects format |

### Reports

**Line chart conventions (Trend Over Time, Year-over-Year monthly mode):**
- Both use Chart.js v4 with `chartjs-plugin-datalabels`. The plugin is registered globally (`Chart.register(ChartDataLabels)`).
- Each line is labeled at its first non-null data point (branch name for Trend, year for YOY). Labels appear above the point with a white pill background and the line's color as font color.
- Trend report branch selector and chart both exclude locker branches and desk sub-locations — only the 6 real service locations appear.

| Route | Function | Description |
|---|---|---|
| `/reports/monthlystats` | `report_monthly_stats` | Monthly Board Report — key metrics for a selected month |
| `/reports/monthly` | `report_monthly` | Monthly Summary — all metrics for a category/month across branches |
| `/reports/fiscal` | `report_fiscal` | Fiscal Year Totals — annual rollup by category |
| `/reports/trend` | `report_trend` | Trend Over Time — one metric charted over months |
| `/reports/yearoveryear` | `report_yoy` | Year-over-Year — compare same month across years |
| `/reports/quarterly_ref` | `report_quarterly_ref` | Quarterly Reference Stats — desk tallies by quarter |
| `/reports/annual` | `report_annual` | Branch Scorecard — annual summary per branch |
| `/reports/crosstab` | `report_crosstab` | Cross-tab Heat Map — metric × branch grid |
| `/reports/programming_age` | `report_programming_age` | Programming Cross-tab — sessions/attendance by age group |
| `/reports/programming` | `report_programming` | Programming Summary — all programming metrics |
| `/reports/online` | `report_online` | Online Stats — all online/social metrics over time |
| `/director` | `director_dashboard` | Director's Dashboard — high-level summary for leadership |

### Annual Survey
| Route | Function | Description |
|---|---|---|
| `/annual-survey` | `annual_survey_dashboard` | Dashboard with KPI cards, Trend Explorer, fixed charts, key metrics table, full section accordion |
| `/annual-survey/<year>/enter` | `annual_survey_enter` | Entry/edit form for a specific fiscal year (16 sections, accordion) |
| `/annual-survey/<year>/calculate` | `annual_survey_calculate` | POST — auto-calculates metrics from monthly data for the fiscal year |

See `Notes/annual_comparables_design.md` for full documentation of the annual survey system.

### Admin
| Route | Function | Description |
|---|---|---|
| `/admin/categories` | `admin_categories` | List and create categories |
| `/admin/categories/<id>` | `admin_category_edit` | Edit category; add/manage metrics |
| `/admin/categories/<id>/toggle` | — | Toggle category active/inactive |
| `/admin/categories/<id>/delete` | — | Delete category |
| `/admin/categories/<id>/metrics/add` | — | Add a metric to a category |
| `/admin/metrics/<id>/edit` | `admin_metric_edit` | Edit a metric |
| `/admin/metrics/<id>/toggle` | — | Toggle metric active/inactive |
| `/admin/metrics/<id>/delete` | — | Delete a metric |
| `/admin/branches` | `admin_branches` | List, create, and manage branches |
| `/admin/branches/<id>/toggle` | — | Toggle branch active/inactive |
| `/admin/branches/<id>/delete` | — | Delete a branch |
| `/admin/import` | `admin_import` | Legacy import page (admin-only upload) |
| `/admin/export` | `admin_export` | Export all data to Excel |
| `/admin/users` | `admin_users` | List all user accounts (admin only) |
| `/admin/users/new` | `admin_users_new` | Create a new user account |
| `/admin/users/<id>/edit` | `admin_user_edit` | Edit user — username, email, role, reset password |
| `/admin/users/<id>/toggle` | — | Activate or deactivate a user account |
| `/admin/users/<id>/delete` | — | Delete a user account |

---

## Current Data Status (as of 2026-04-26)

### What is loaded

| Source | Status | Coverage |
|---|---|---|
| `non-SIRSI423.xlsx` | ✅ Loaded (one-time insert) | Jan 2024 – Mar 2026, all branches, all non-SIRSI Branch Stats metrics (WiFi, PC reservations, programs, ILL/ICL, printing, etc.) |
| SIRSI Circulation | ⚠️ Partial | August 2025 only (11 entries, 1,563 SirsiCheckout rows) |
| SIRSI Registration | ⚠️ Partial | August 2025 only (6 values per metric) |
| Princh Printing | ⚠️ Partial | Some months loaded (79 values), not full history |
| Online Stats | ✅ Loaded (one-time insert) | 27 entries — Jan 2024 – Mar 2026, system-wide |
| Quarterly Reference Stats | ✅ Loaded (one-time insert) | 24 entries — Q1/Jun 2025, Q2/Oct 2025, Q3/Jan 2026, all 8 branches. **Future periods entered manually via nav.** |
| Door Counter | ❌ Not loaded | Gate Count data in DB came from `non-SIRSI423.xlsx`, not door counter exports |

### Remaining uploads needed

Upload through the **Upload Data** page (`/upload`). Files can be uploaded in any order — the system upserts and will not overwrite unrelated metrics.

**Priority 1 — SIRSI Circulation** (one file per month, all months Jan 2024 – present except Aug 2025)
- File: `Checkouts by Branch and Shelving Location - {Month} {Year}.xlsx`
- Writes: `Total Branch Circulation` and `Hotspots Circulation` per branch

**Priority 2 — SIRSI Registration** (one file per month, all months Jan 2024 – present except Aug 2025)
- File: `Number of New Library Users by Branch and Patron Type - {Month} {Year}.xlsx`
- Writes: `New Library Card Registrations, Adult/Juvenile/Total` per branch

**Priority 3 — Online Stats** (single upload covers multiple months)
- File: `onlin423.xlsx` — already loaded (Jan 2024 – Mar 2026)
- Future months: enter via Manual Entry form → Online Stats tab, or upload a new Excel file
- Writes: all Online Stats metrics system-wide

**Priority 4 — Quarterly Reference Stats**
- Historical data already loaded via one-time script from `QRSver2.xlsx` (Q1/Jun 2025, Q2/Oct 2025, Q3/Jan 2026)
- **Going forward: entered manually each period via Enter Data → Qrtly Ref Stats in the nav**
- Do NOT upload future QRS data through the Upload Data page — use manual entry instead

**Priority 5 — Princh Printing** (one file per month, ongoing)
- File: `princh-export_{start}_{end}.xlsx` — upload monthly through Upload Data page
- Writes: `Total Prints per Month` per branch
- Some 2025 months have incomplete branch coverage (see data status table); historical Princh exports can fill gaps if available

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
