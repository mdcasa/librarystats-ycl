# Backup: Site Structure & Layout Snapshot — 2026-07-29

**Purpose:** Point-in-time reference of the app's structure, navigation, and report
inventory, captured *before* a planned round of layout changes. If something is lost
or needs to be restored during the redesign, this is the "how it was" reference.
For ongoing/updated documentation, see [`design.md`](design.md) — this file is a
frozen snapshot, not a living doc.

---

## 1. App Structure

Flask app, single `app.py` (4,284 lines) with all routes and business logic.

| File | Lines | Role |
|---|---|---|
| `app.py` | 4,284 | All routes, business logic, startup DB migrations |
| `models.py` | 388 | SQLAlchemy models |
| `import_excel.py` | 2,179 | All Excel file importers (auto-detected by sheet/header) |
| `seed_data.py` | 142 | First-boot seed data |
| `templates/base.html` | — | Shared layout, nav, all CSS (inline `<style>` block) |

### Template tree (`templates/`)

```
templates/
├── base.html              (main authenticated layout — navbar, footer, alerts)
├── base_public.html        (layout for the public annual-stats page, no login)
├── login.html
├── index.html              (Dashboard / home)
├── director.html           (Director's Dashboard)
├── upload.html             (Data → Upload Data)
├── public/
│   └── annual_overview.html
├── annual/
│   ├── dashboard.html      (Annual Survey dashboard)
│   ├── entry.html          (Annual Survey data entry)
│   ├── branch_hours.html   (Branch Weekly Hours)
│   ├── holidays.html       (Holiday Schedule)
│   └── section_j.html      (Section J — Outlet Hours)
├── entries/
│   ├── list.html           (Data → Browse Data)
│   ├── view.html
│   ├── form.html           (create/edit entry)
│   └── main_only_entry.html (ILL/ICL entry, Main branch only)
├── admin/
│   ├── users.html, user_form.html
│   ├── categories.html, category_edit.html
│   ├── branches.html
│   ├── metric_edit.html
│   └── import.html         (Admin → Import from Excel)
└── reports/
    ├── index.html          (Reports → All Reports)
    ├── category_landing.html
    ├── monthly_stats.html
    ├── impact.html, impact_pdf.html
```

### Report templates (`reports/` at project root, separate from `templates/reports/`)

```
reports/
├── fiscal.html
├── quarterly_ref.html
├── online.html
├── trend.html
├── monthly.html
├── programming.html
├── yearoveryear.html
├── overview.html
├── impact_pdf.html
├── impact.html
├── branch_summary.html
├── monthly_stats.html
├── annual.html
├── programs_summary.html
├── programs.html
└── category_landing.html
```
`app.jinja_loader` is a `ChoiceLoader` combining `templates/` and the project root, which is why report templates live in `/reports/` at the top level instead of under `templates/reports/`.

### Data model (`models.py`)

- **User** — auth (Flask-Login), `is_admin` flag
- **Category** — data-collection categories (Branch Stats, Online Stats, eResources, Quarterly Reference Stats, etc.), `frequency` (monthly/quarterly/annual), `sort_order`
- **Metric** — belongs to a Category, has `group_name` (e.g. "Circulation", "Access & Usage", "ONSITE Programming"), `data_type`
- **Branch** — 6 real service locations + locker rows + desk sub-locations (`is_desk`) + `YCL (System Wide)` placeholder
- **Entry** / **EntryValue** — one Entry per category/branch/period, EntryValues hold the actual numbers
- **SirsiCheckout** — granular ILS checkout detail (branch/patron-type/shelving-location/month), rolls up into Branch Stats
- **ProgramEvent** — granular program detail from Communico import, rolls up into ONSITE/OFFSITE/VIRTUAL Branch Stats metrics
- **AnnualSurveyMetric** / **AnnualSurveyValue** — SC State Library annual survey
- **QuarterlyRefClosureDays**, **BranchClosure**, **HolidayClosure**, **BranchWeeklyHours**, **OutletScheduledHours**, **SectionJOutletData** — closure/hours tracking feeding Quarterly Ref and Section J reports
- **ImportLog** — one row per file upload, supports undo

### Route sections in `app.py` (in file order)

1. Auth (`/login`, `/logout`)
2. Dashboard (`/`)
3. Browse / Create / View / Edit / Delete entries (`/entries...`)
4. Admin: Categories, Metrics, Branches (`/admin/categories`, `/admin/metrics`, `/admin/branches`)
5. Reports (`/reports`, `/reports/category/<slug>`, and one route per report — see §3 below)
6. Branch Scorecard helpers
7. Upload — smart auto-detect (`/admin/import`, `/upload`, `/upload/undo/<id>`)
8. ILL/ICL entry (`/enter/ill`, `/enter/icl`)
9. User Management (`/admin/users...`)
10. Annual Survey Dashboard (`/annual-survey...`)
11. Section J: Outlet Hours/Weeks Open (`/annual-survey/<year>/section-j`, `/annual-survey/branch-hours`, `/annual-survey/holidays`)
12. Public annual-stats page (`/public/annual-stats`, no login required)
13. Impact report + PDF/DOCX export (`/reports/impact`, `/reports/impact.pdf`, `/reports/impact.docx`)

---

## 2. Navigation / Menu Layout (`templates/base.html`)

Top navbar (Bootstrap 5, YCL blue `#1a4f9e`), left-to-right:

1. **Dashboard** (single link, no dropdown) → `/`
2. **Enter Data** (dropdown)
   - ILL Entry *(Main only)*
   - ICL Entry *(Main only)*
   - — divider —
   - One entry per active `Category` (from `nav_categories`), each showing a frequency badge (Monthly/Quarterly/Annual)
3. **Data** (dropdown)
   - Upload Data → `/upload`
   - Browse Data → `/entries`
4. **Dashboards** (dropdown)
   - Director's Dashboard
   - Annual Survey
   - Section J — Outlet Hours
   - Branch Weekly Hours
   - Holiday Schedule
5. **Reports** (dropdown)
   - Circulation → `/reports/category/circulation`
   - Facility Usage → `/reports/category/facility-usage`
   - Programming → `/reports/category/programming`
   - Online → `/reports/category/online`
   - eResources → `/reports/category/eresources`
   - — divider —
   - All Reports → `/reports`
6. **Admin** (dropdown, `is_admin` only — otherwise shows "No admin access")
   - Users
   - — divider —
   - Categories & Metrics
   - Branches / Locations
   - — divider —
   - Import from Excel
   - Export to Excel

Right side: current username + Sign Out button.

Active-state logic: `ep` (current endpoint) is checked against hardcoded lists (`_enter`, `_data`, `_dash`, `_reports`, `_admin`) near the top of the template to highlight the correct top-level dropdown (`active-parent` class) and the correct item within it (`active` class).

Footer: centered "YCL Statistics — {year}".

---

## 3. Reports Inventory

### Category landing pages (`/reports/category/<slug>`)
Defined in the `REPORT_CATEGORIES` dict in `app.py` (~line 938):

| Slug | Title | Maps to Category / Metric Groups |
|---|---|---|
| `circulation` | Circulation | Branch Stats → group "Circulation" |
| `facility-usage` | Facility Usage | Branch Stats → group "Access & Usage" |
| `programming` | Programming | Branch Stats → groups "ONSITE/OFFSITE/VIRTUAL Programming" |
| `online` | Online | Online Stats category |
| `eresources` | eResources | eResources category |

### All Reports index (`/reports`) — cards, in display order

| Report | Endpoint | What it shows |
|---|---|---|
| Annual Overview | `report_overview` | Two most recently completed fiscal years, side by side |
| Monthly Board Report | `report_monthly_stats` | System-wide totals, one month, vs. same month last year |
| Monthly Summary | `report_monthly` | Every branch's numbers, one category, one month |
| Fiscal Year Totals | `report_fiscal` | One category, one fiscal year (Jul–Jun), per-branch sums |
| Trend Over Time | `report_trend` | One category/metric, continuous month-by-month line, 1+ fiscal years |
| Year-over-Year | `report_yoy` | One category/metric/branch, 2+ fiscal years side by side |
| Quarterly Ref | `report_quarterly_ref` | Quarterly Reference desk transactions + open days/hours |
| Online Stats | `report_online` | Online Stats category, one month vs. prior month |
| Branch Summary | `report_branch_summary` | Every category rolled up, one branch, one fiscal year |
| Programming Summary | `report_programming` | Sessions/attendance by ONSITE/OFFSITE/VIRTUAL + age group, one year |
| Programs by Topic | `report_programs` | Every individual program (Communico import), grouped by Program Type |
| Programs Summary | `report_programs_summary` | Month-by-month program counts/attendance by age group, one fiscal year |

### Other report-adjacent routes (not on the `/reports` index cards)
- `report_category_landing` — the 5 category landing pages listed above
- `report_impact` / `/reports/impact.pdf` / `/reports/impact.docx` — Impact report with PDF and DOCX export
- `/public/annual-stats` — public-facing annual overview (no login, `base_public.html` layout)

---

## 4. Dashboards (separate from "Reports")

- **Home Dashboard** (`/`) — includes the Data Status widget (falls back to Branch Stats ILS data for Circulation, per [`CLAUDE.md`](../CLAUDE.md))
- **Director's Dashboard** (`/director`)
- **Annual Survey Dashboard** (`/annual-survey`) — SC State Library survey, with sub-pages for entry, calculation, Section J, Branch Weekly Hours, and Holiday Schedule

---

## 5. Branding / Styling (in `base.html` inline `<style>`)

- CSS variables: `--ycl-blue: #1a4f9e`, `--ycl-blue-dark: #153f80`, `--ycl-blue-light: #2563b8`, `--ycl-blue-pale: #e8f0fb`
- Bootstrap 5.3.3 + Bootstrap Icons 1.11.3 (via CDN, jsdelivr)
- Chart.js v4 + `chartjs-plugin-datalabels` for Trend/Year-over-Year charts (per `CLAUDE.md`)
- Custom classes: `.group-header` (collapsible table section headers with chevron), `.card`/`.card-header-custom`, `.empty-state`, `#backToTop` floating button
- Dedicated `@media print` block: hides navbar/footer/buttons/alerts, adjusts table font size, forces blue headings

---

## 6. What's Deliberately Not Changing (per `CLAUDE.md`)

These architectural rules were true as of this snapshot and should still hold after the layout redesign unless the user says otherwise:
- 6 real service locations vs. locker branches vs. desk sub-locations vs. `YCL (System Wide)` — distinct handling in forms/charts/counts
- Circulation/registration data lives in Branch Stats entries, not a separate "Circulation" category
- Importers upsert, never skip
- No email-based password reset — Admin → Users only

---

*Snapshot taken 2026-07-29, branch `v4`, prior to planned layout changes. Compare against this file if reverting or auditing what changed.*
