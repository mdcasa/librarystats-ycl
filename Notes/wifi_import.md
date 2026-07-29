# WiFi (Cisco Meraki) Summary Report Importer — 2026-07-07

Change log for the WiFi "Summary Report" import work, in case we need to revisit
or roll it back.

## What was requested

Load the per-branch Cisco Meraki "Summary Report" spreadsheets in
`Data files/June/wifi/` into the database and display them as data — an
automated replacement for the WiFi figure that used to be entered by hand.

## The file format

- **One workbook per branch per month** (5 files: Clover, Fort Mill, Lake Wylie,
  Rock Hill, York). Name pattern:
  `Rock Hill - Summary Report 2026-06-01 - 2026-07-01.xlsx`.
- 13 sheets of Meraki network analytics. **Neither the branch nor the month
  appears inside the sheets** — both are read from the file name.
- The figure we track lives in the **`Client stats`** sheet:
  `Total Unique Clients` (col A) = distinct devices seen on the WiFi that month.

## Metric mapping (decided with the user)

| Spreadsheet | Branch Stats metric | Notes |
|---|---|---|
| `Client stats` → `Total Unique Clients` | `WiFi - Unique Sessions` | **Existing** metric. Natural match — the old Google Forms field was literally "WiFi - Unique Clients" mapping to this same metric. No new metric created. |

Only this one figure is imported; the rest of the Meraki analytics (usage,
sessions-over-time, top apps, etc.) are intentionally not stored — the ask was a
replacement for the single manually entered stat.

## Code changes (branch `v4`)

- **`import_excel.py`**
  - `import_meraki_wifi(wb, branch_lookup, filename, year_override)` — resolves
    branch + period from the file name, reads `Total Unique Clients`, upserts
    into `WiFi - Unique Sessions`. Returns `(created, updated, period_set, warnings)`.
  - `detect_and_import` gets a **workbook-level** detector (signature: the
    `Client stats` + `Usage stats` sheets), placed alongside the OPERATIONS
    check — its 13 sheets carry no branch/date, so there is nothing to route
    per-sheet. Period from file name → Year field fallback.
  - Constants: `MERAKI_SIGNATURE_SHEETS`, `MERAKI_BRANCH_MAP`.
  - Reuses `parse_period_from_filename` (handles `2026-06-01`) and
    `_upsert_branch_stat`.
- **`load_wifi.py`** (new) — loops every `.xlsx` in a folder through
  `detect_and_import` (defaults to `Data files/June/wifi`). `load_dotenv()` so it
  targets Supabase like other one-time loads. Idempotent.
- **`app.py`** — no change needed. `WiFi - Unique Sessions` was **already** in
  `_UPLOAD_SOURCED_METRICS`, so it was already hidden from the manual entry/edit
  form; this importer just fills what previously had no source.

## Production actions taken

- June 2026 WiFi loaded into **production Supabase** via `python load_wifi.py`
  (2026-07-07). Values (per branch, June 2026, = spreadsheet exactly):
  Clover 149, Fort Mill 932, Lake Wylie 154, Rock Hill 1295, York 219.
- Attached to the existing June Branch Stats entries (RH 2268, York 2270,
  Fort Mill 2265, Clover 2263, Lake Wylie 2260) — no duplicate entries.

## Where the data lives / how to view it

- Browse Data → Category = Branch Stats, Year = 2026 → open a June entry →
  **Access & Usage** group → `WiFi - Unique Sessions`.
- The Edit form hides this metric by design (upload-sourced).

## How to roll back / re-run

- Re-uploading is safe (upsert) — updates in place, never duplicates.
- Going forward, staff can drag these Meraki files into the web **Upload** page
  once the `v4` code is deployed; the loader script is only needed for bulk loads.
- **Caveat:** `load_wifi.py` writes no `ImportLog`, so a script load has no
  "Recent Imports → Undo" entry (web uploads do). To undo a script load, clear
  the `WiFi - Unique Sessions` EntryValues for that month.

## Gotchas

- Branch + month come from the **file name only** — renaming a file loses them.
- Rock Hill reopened Apr 2026 after renovations, so June numbers are present.
