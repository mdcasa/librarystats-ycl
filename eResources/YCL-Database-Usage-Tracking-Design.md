# YCL Database Usage Tracking — Design Document

**Project:** yclstats.org — Database usage tracking module, referred to elsewhere in the app/docs as **"Monthly eResources"**
**Author:** Martin (Assistant Director, York County Library), drafted with Claude
**Status:** Phase 1 (manual ingestion) implemented; SUSHI harvester (Section 5) and manual upload UI (Section 6a) still to build
**Stack:** Railway (hosting + scheduled jobs) + Supabase (Postgres + storage)

> **Not to be confused with "Annual eResources"** — the existing DB category (E-Book/E-Audio/E-Video/E-Serials Circulation, entered once a year) documented in `Design/design.md`. This document covers a separate, monthly, per-database vendor usage dataset (COUNTER/SUSHI) — see "Implementation Notes" below for what's actually built vs. this original design.

---

## Implementation Notes (added after Phase 1 build)

The `databases`/`usage_monthly` tables are implemented in `models.py`, but **not exactly as specified in Section 4 below** — the differences, and why:

- **Integer primary keys, not UUIDs.** Every other table in this codebase uses plain auto-incrementing integers (see `SirsiCheckout`, `Entry`, etc.) — matching that convention rather than introducing UUIDs as a one-off.
- **No `metric` column on `usage_monthly`.** Instead, each vendor/metric combination is its own row in `databases` (e.g. "Hoopla - eBooks Instant", "Hoopla - Comics" are separate database rows, not one "Hoopla" row with multiple metrics). This is simpler and was faster to ship given data collection is 100% manual right now — no COUNTER/SUSHI JSON to normalize yet. **If/when the SUSHI harvester (Section 5) gets built**, this will likely need revisiting, since one COUNTER DR response returns multiple metrics per database in a single call, which fits the original `metric`-column design much better.
- **No `harvest_log` table yet** — not needed until Section 5's harvester exists.
- **No `sushi_*` credential columns, `subject_categories`, `data_method`, or `raw_payload`** — all deferred until SUSHI work actually starts.
- **89 databases seeded** (`seed_eresource_databases()` in `seed_data.py`), not the ~104 from the inventory spreadsheet — seeded from the director's actual monthly tracking workbook (`Monthly Stats 2025-2026.xlsx`) instead, vendor-by-vendor, since that's the real data source in hand. 19 DISCUS entries are seeded `is_active=False` placeholders (that tab was blank in the workbook).
- **`import_eresources.py`** is the "Step (b) — a script" manual ingestion path called for in Section 6 — reads the tracking workbook directly (each vendor tab has its own row/column layout) and upserts `usage_monthly`. Verified against FY2025-2026 data: 809 rows imported, matches the "Annual Stats for SC State" bucket totals in `patch_fy2526_annual_eresources.py` to within rounding, with one known exception (see below).
- **New `/reports/eresources` report** (not in the original design) — FY selector, the four bucket totals, and a per-vendor monthly usage table. Linked from the "All Reports" page.

**Known data discrepancy — Hoopla BingePass (Comics & eBooks):** the monthly tracking workbook's own Bingepass breakdown table sums to **200** for FY2025-2026, but the "Annual Stats for SC State" export (loaded via `patch_fy2526_annual_eresources.py`) uses **14** for this same line. The other three Bingepass columns (audio, courses/videos, magazines) reconcile exactly between the two sources — only this one doesn't. `import_eresources.py` currently loads the monthly workbook's number (200) as-is; nobody has resolved which figure is correct. Until that's settled, the E-Books bucket total on `/reports/eresources` will read 186 higher (227,672) than the official state-reported total (227,486).

Also fixed during Phase 1 build: the ABC Mouse sheet's own footer note says "For State Report, report Learning Activities," which is wrong — Learning Activities totals 41,555 (far more than the entire E-Video bucket target of 31,483), while Visits totals 4,793, which exactly matches the Annual Stats export. `databases`/`import_eresources.py` use Visits for the `evideo` bucket, not Learning Activities, contradicting the sheet's own (incorrect) instructions.

---

---

## 1. Problem Statement

YCL subscribes to ~90+ online databases and resources, listed on [yclibrary.org/resources-by-subject](https://www.yclibrary.org/resources-by-subject) across 19 subject categories. We want to track **actual vendor-reported usage** (logins, searches, sessions, item requests) for each database, so we can:

- Justify renewals/cuts based on real usage
- Report usage by subject category and by branch (where vendors support it)
- Spot underused resources worth promoting, or dead resources worth cutting
- Build trend views over time on yclstats.org

This is **not** website click-tracking on the resources page — it's vendor-side usage data (patrons actually logging in and using the database), pulled via COUNTER 5 / SUSHI where available, and manual export where not.

Reference data: `YCL_Database_Usage_Tracking_Inventory.xlsx` — deduplicated list of all ~104 database entries from the resources-by-subject page, each tagged with likely vendor/platform and expected data-collection method (SUSHI / Manual / Not Applicable). This spreadsheet is the seed data for the `databases` table (Section 4).

---

## 2. Background: COUNTER 5 and SUSHI

- **COUNTER Release 5** is the library-industry standard for usage reporting. The relevant report type here is the **Database Master Report (DR)**, which returns monthly metrics like `Total_Item_Investigations`, `Total_Item_Requests`, and (for some platforms) `Unique_Title_Requests`.
- **SUSHI** (Standardized Usage Statistics Harvesting Initiative) is a REST API built on top of COUNTER 5 that lets us pull these reports programmatically instead of logging into each vendor's admin portal by hand. A vendor gives us a base URL + `customer_id` (+ sometimes `requestor_id` / API key).
- **Not every vendor supports SUSHI.** Big platforms (EBSCO, Gale, Britannica, ProQuest) generally do. Smaller or niche vendors (Mango, TumbleBooks, Tutor.com, local newspapers, free government tools) often don't — for those we fall back to manual CSV export or the vendor's own usage dashboard.
- **EBSCO covers the largest single chunk of our list** — around a third of our ~104 entries are EBSCO-hosted databases, all reportable through **one SUSHI account**. This is the highest-leverage first target.

---

## 3. Architecture Overview

```
┌─────────────────────┐      monthly cron       ┌──────────────────────┐
│ Railway: sushi-      │ ───────────────────────▶│ Vendor SUSHI APIs     │
│ harvester job        │◀─────────────────────────│ (EBSCO, Gale, etc.)   │
└─────────┬────────────┘      COUNTER 5 JSON      └──────────────────────┘
          │ upsert
          ▼
┌──────────────────────┐
│ Supabase (Postgres)   │◀──── manual CSV upload (non-SUSHI vendors)
│ - databases           │
│ - usage_monthly        │
│ - harvest_log          │
└─────────┬────────────┘
          │ query
          ▼
┌──────────────────────┐
│ yclstats.org dashboard│
│ (existing Railway app)│
└──────────────────────┘
```

**Components:**
1. **`databases` table** — static-ish reference table: one row per database, seeded from the inventory spreadsheet.
2. **`usage_monthly` table** — the actual usage facts, one row per database/month/metric.
3. **`harvest_log` table** — records each harvest attempt (success/failure) per database per run, so failures (expired creds, changed report format) are visible instead of silently missing data.
4. **SUSHI harvester** — a Railway scheduled job (monthly, e.g. 3rd of the month to allow vendors to close out the prior month's data) that loops through SUSHI-enabled databases and pulls the DR report.
5. **Manual ingestion path** — a small upload form (or a scripted CSV import) for vendors without SUSHI, writing into the same `usage_monthly` table with `source = 'manual'`.
6. **Dashboard** — new views/pages on the existing yclstats.org app, reading from `usage_monthly` joined to `databases`.

---

## 4. Data Model (Supabase / Postgres)

### `databases`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `name` | text | Display name, e.g. "MasterFILE Premier" |
| `vendor` | text | e.g. "EBSCO", "Gale/Cengage" |
| `subject_categories` | text[] | e.g. `{Business & Economics, Education}` — matches resources-by-subject tags |
| `data_method` | text | enum-like: `sushi`, `manual`, `not_applicable` |
| `sushi_base_url` | text, nullable | Vendor's SUSHI API base URL |
| `sushi_customer_id` | text, nullable | |
| `sushi_requestor_id` | text, nullable | Some vendors require this in addition to customer_id |
| `sushi_api_key` | text, nullable | **Store in Supabase Vault / Railway secrets, not plain column, if possible** |
| `active` | boolean | Whether we're still subscribed |
| `notes` | text | Free text, carried over from inventory spreadsheet |
| `created_at` / `updated_at` | timestamptz | |

### `usage_monthly`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `database_id` | uuid, FK → databases.id | |
| `year_month` | date | Normalize to first-of-month, e.g. `2026-06-01` |
| `metric` | text | `total_item_investigations`, `total_item_requests`, `unique_title_requests`, `sessions`, `searches`, etc. |
| `value` | integer | |
| `source` | text | `sushi` or `manual` |
| `raw_payload` | jsonb, nullable | Store the original COUNTER JSON blob for that database/month, for auditing/reprocessing |
| `created_at` | timestamptz | |

Unique constraint on `(database_id, year_month, metric, source)` so re-running a harvest is an idempotent upsert, not a duplicate insert.

### `harvest_log`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `database_id` | uuid, FK | |
| `run_at` | timestamptz | |
| `status` | text | `success`, `failed`, `no_data` |
| `error_message` | text, nullable | |
| `months_harvested` | int, nullable | How many months of data came back |

---

## 5. SUSHI Harvester Job

**Where it runs:** Railway scheduled job (cron), separate service from the main yclstats.org web app.

**Trigger:** Monthly, e.g. `0 6 3 * *` (6am on the 3rd, gives vendors a couple days to finalize prior month's COUNTER data).

**Logic:**
1. Query `databases` where `data_method = 'sushi'` and `active = true`.
2. For each, call the vendor's SUSHI `reports/dr` endpoint (or platform-specific equivalent) for the prior month, using stored `sushi_base_url` / `sushi_customer_id` / `sushi_requestor_id` / `sushi_api_key`.
3. Parse the COUNTER 5 JSON response (`Report_Items[].Performance[].Instance[]` gives metric_type + count per month).
4. Upsert rows into `usage_monthly` (one row per metric per month), with `source = 'sushi'` and the raw JSON in `raw_payload`.
5. Write one row to `harvest_log` per database per run — success/failure, so failures don't just silently vanish.
6. On failure, don't crash the whole batch — log it and continue to the next vendor.

**Auth handling:** Each vendor's SUSHI implementation differs slightly (some want `requestor_id` as a query param, some don't need it at all, some use an API key header). Plan on a small per-vendor adapter pattern (e.g. `harvesters/ebsco.js`, `harvesters/gale.js`) rather than one generic client, since exact request shape varies.

**Start narrow:** Ship EBSCO first (covers the largest single group of databases), confirm the pipeline end-to-end, then add other SUSHI-capable vendors (Gale, Britannica, ProQuest) one at a time.

---

## 6. Manual Ingestion Path

For vendors without SUSHI (Mango, TumbleBooks, Tutor.com, Value Line, local newspapers excluded entirely — see Section 7):

- Simple CSV template: `database_name, year_month, metric, value`
- Either:
  - (a) A small upload page/form on yclstats.org that parses and upserts into `usage_monthly` with `source = 'manual'`, or
  - (b) A one-off script Martin runs after manually downloading vendor reports monthly/quarterly.
- Start with (b) — a script — since it's far less build effort, and upgrade to (a) only if the manual workload becomes painful.

---

## 7. Exclusions

Not every entry on the resources-by-subject page belongs in this tracker. Per the inventory spreadsheet, exclude (tag `data_method = 'not_applicable'`):

- Free public resources with no institutional usage API (LearnFree/GCFLearnFree, Chronicling America, Merck Manual, SCDMV, SCIWAY, DigitalLearn.org, etc.)
- Local newspaper links (Charlotte Observer, The Herald, Lake Wylie Pilot) — these are just outbound links, not subscription databases we can meter
- A handful of "unknown vendor" entries that need identification before they can be classified either way

These still get a row in `databases` (for completeness of the resources-by-subject mapping) but are skipped by the harvester and won't appear in usage dashboards.

---

## 8. Dashboard (yclstats.org)

New views, reading from `usage_monthly` joined to `databases`:

1. **By database** — trend line per database over time, current vs. prior period
2. **By subject category** — aggregate usage across all databases tagged with a given subject (since `subject_categories` is an array, a database counts toward every category it's tagged with)
3. **By vendor** — useful for renewal conversations ("here's total usage across all EBSCO products")
4. **Coverage view** — which databases have data vs. which are still pending manual entry or SUSHI setup (pulls from `harvest_log` + `data_method`)

---

## 9. Build Phases

**Phase 1 — Foundation**
- Create `databases`, `usage_monthly`, `harvest_log` tables in Supabase
- Seed `databases` from `YCL_Database_Usage_Tracking_Inventory.xlsx`
- Manually confirm SUSHI credentials for EBSCO (largest vendor group)

**Phase 2 — First harvester**
- Build the EBSCO SUSHI adapter, wire up the Railway scheduled job
- Run manually first, verify data lands correctly in `usage_monthly`
- Turn on the monthly cron

**Phase 3 — Manual path**
- Script or form for non-SUSHI vendors, starting with highest-traffic ones (Mango Languages, Tutor.com, Gale eBooks)

**Phase 4 — Dashboard**
- Build the by-database and by-subject views on yclstats.org
- Add coverage/health view so gaps are visible

**Phase 5 — Expand SUSHI coverage**
- Add Gale, Britannica, ProQuest adapters as credentials are confirmed
- Revisit "Medium/Low confidence" vendors from the inventory spreadsheet and reclassify as SUSHI support is confirmed or ruled out

---

## 10. Open Questions / To Confirm Before Building

- [ ] Do we already have SUSHI credentials for EBSCO, or does Troy (IT Manager) need to request them from the EBSCO account rep?
- [ ] Does Gale's "Analytics on Demand" portal expose a SUSHI endpoint, or is it export-only?
- [ ] For vendors marked "Manual/Verify" in the inventory spreadsheet — worth a pass through each admin portal to confirm before Phase 5.
- [ ] Do we want branch-level breakdown where vendors support it (some COUNTER reports can be sliced by IP range/branch), or is library-wide totals sufficient for v1?
- [ ] Where should `sushi_api_key` values actually live — Supabase Vault, Railway environment variables per-service, or a secrets table with app-level encryption?

---

## 11. Reference

- Seed data: `YCL_Database_Usage_Tracking_Inventory.xlsx`
- COUNTER 5 Code of Practice: https://www.projectcounter.org/code-of-practice-five-sections/
- SUSHI spec: https://www.niso.org/standards-committees/sushi
