# CLAUDE.md — YCL Statistics

This file is read automatically by Claude Code at the start of every session.

**For setting up a new library instance — read `Design/first_steps.md` first.**
Full technical detail is in `Design/design.md`.

---

## What This Is

A Flask web app for York County Library (YCL) that tracks monthly, quarterly, and annual statistics across 6 service locations. Staff upload Excel files from various systems; the app consolidates everything into a single browsable database with reports and dashboards.

---

## Infrastructure

| Service | Role |
|---|---|
| **Supabase** | PostgreSQL database (free tier, good browser UI, backups) |
| **Railway** | App hosting — auto-deploys on push to `v4` branch |
| **GitHub** | Source control — `mdcasa/librarystats`, active branch is `v4` |

Railway hosts the app only. The database lives in Supabase. `DATABASE_URL` in Railway env vars points to Supabase. Do not move the DB to Railway — Supabase is intentionally chosen for its tooling.

**Local dev:** `.env` file with `DATABASE_URL` pointing at Supabase (or omit for local SQLite).

---

## Key Files

- `app.py` — all routes, business logic, startup patches
- `models.py` — SQLAlchemy models (User, Category, Metric, Branch, Entry, EntryValue, SirsiCheckout, AnnualSurvey*)
- `import_excel.py` — all file importers (auto-detected by sheet name / header)
- `seed_data.py` — runs once on first boot when DB is empty
- `templates/base.html` — all shared CSS, nav, branding
- `Design/design.md` — full technical reference

---

## Tech Stack

Flask 3, Flask-SQLAlchemy, Flask-Login, PostgreSQL (Supabase), gunicorn, openpyxl, python-dotenv. No migration tool — schema changes use inline `ALTER TABLE` in a try/except block in `app.py` at startup.

---

## Critical Architectural Rules

**Branch taxonomy — never mix these up:**
- 6 real service locations: Rock Hill, Clover, Fort Mill, Lake Wylie, York, Outreach/Bookmobile
- Locker branches (`*Lockers`, ILS codes `YCL-XX-LOC`) — separate DB rows, excluded from forms, branch counts, and chart lines. Locker data is summed into the parent branch in the Trend Over Time chart.
- Desk sub-locations (`is_desk=True`): Rock Hill - Circulation, Rock Hill - YA — QRS only
- System-wide placeholder: `YCL (System Wide)` — always excluded from counts and forms

**SIRSI is YCL's ILS (Integrated Library System) — not a universal standard.** "SIRSI" throughout this codebase means "ILS circulation data." Every library uses a different ILS (SIRSI, Polaris, Koha, Symphony, etc.). When deploying for another library, the SIRSI-specific importers (`import_excel.py` functions `import_sirsi_checkouts`, `import_sirsi_registrations`) and the `SirsiCheckout` model would need to be adapted or replaced to match that library's ILS export format. The metric names (Total Branch Circulation, Hotspot Circulation, registrations) and where they land in Branch Stats can stay the same — only the importer parsing logic changes.

**ILS/circulation data goes into Branch Stats, not a separate category.** Total Branch Circulation, Hotspot Circulation, and registrations are stored as metrics within Branch Stats entries. The "Circulation" category in the DB is an empty alias — the dashboard Data Status widget falls back to Branch Stats ILS data to show the correct date for it.

**Importers upsert — never skip.** Each importer finds-or-creates the entry then adds/overwrites only its own metrics. Safe to upload the same file twice.

**One-time historical loads must use `load_dotenv()`.** Inline scripts that skip this silently hit local SQLite instead of Supabase.

**Two separate "eResources" concepts — don't conflate them:**
- **Annual eResources** (DB category, `models.py`/`seed_data.py`, `frequency='annual'`) — E-Book, E-Audio, E-Video, E-Serials Circulation, entered once a year via `/entries/new/<category_id>` (system-wide, `branch_id=None` — no branch breakdown, and not the `YCL (System Wide)` Branch row). Feeds the eBook/eAudio/eVideo/eSerial Circ rows on the Director's Dashboard and the Annual Comparables report's "digital" total. First loaded for FY2025-2026 via `patch_fy2526_annual_eresources.py`. Still shows "No data" in Data Status for any fiscal year not yet loaded — a visible reminder, not a bug.
- **Monthly eResources** (planned, not yet built — see `eResources/` folder) — vendor-reported database usage (logins, searches, sessions) for ~90 subscription databases, harvested monthly via COUNTER 5/SUSHI or manual CSV. Entirely different dataset from Annual eResources; has its own future tables (`databases`, `usage_monthly`, `harvest_log`), not part of the existing Category/Metric/Entry schema. Once a full fiscal year of monthly data exists, it should be tabulated into the same four Annual eResources buckets — the vendor→bucket crosswalk is in `eResources/YCL-Vendor-Data-Onboarding-Plan.md` §3a.

**No email-based password reset.** Admins reset passwords directly via Admin → Users. No SMTP required.

---

## Authentication

Flask-Login with individual user accounts. Passwords hashed with werkzeug. All routes require login except `/login` and `/logout`. On first boot with an empty users table, a bootstrap admin is created from `LOGIN_USERNAME` (default: `admin`) and `LOGIN_PASSWORD` env vars.

Roles: `is_admin=True` → full access including user management. `is_admin=False` → data entry and reports only.

---

## Charts

Chart.js v4 with `chartjs-plugin-datalabels` on line charts (Trend Over Time, Year-over-Year). Each line is labeled at its first non-null data point. Trend report shows only the 6 real service locations — locker data is merged into parent branch totals.

---

## Branding (to customise for a new library)

- Logo: replace `static/ycl-logo.png` and `Data files/YCL Logo.png`
- Colors: update CSS variables in `base.html` (`--ycl-blue`, `--ycl-blue-dark`, `--ycl-blue-light`, `--ycl-blue-pale`)
- App name: search `YCL Statistics` in templates
- Branches: update via Admin → Branches after first boot
- Seed data: edit `seed_data.py` before first boot if the new library tracks different metrics

---

## Deploying for a New Library

1. **Supabase** — new project → copy connection string (URI mode, `postgresql://`)
2. **Railway** — new project → deploy from this GitHub repo → set branch
3. **Env vars in Railway:** `DATABASE_URL` (Supabase), `SECRET_KEY` (random hex), `LOGIN_PASSWORD`
4. **First boot** — tables created automatically, seed data loaded, bootstrap admin created
5. **Customise** — branding, branches, categories via admin UI

See `Design/design.md → Standing Up a New Instance` for full detail.
