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

All imports go through the `/upload` page. The system auto-detects file type by reading the sheet name or header row.

| File Type | What It Imports |
|---|---|
| **Branch Stats Excel** (`statsonly...xlsx`) | Most monthly branch metrics — WiFi, PC, gate count, programs, outreach, etc. |
| **SIRSI Checkouts by Shelving Location** | Granular checkout/renewal data → writes `Total Branch Circulation` and `Hotspots Circulation` into Branch Stats |
| **SIRSI Checkouts by User Profile** | Adult/juvenile checkout counts → stored in `SirsiCheckouts` table |
| **SIRSI New Library Users** | New card registrations → writes Adult/Juvenile registration metrics into Branch Stats |
| **Princh export** | Print page counts → writes `Total Prints per Month` into Branch Stats |
| **Door counter export** | Daily ins/outs → sums to `Gate Count` in Branch Stats |
| **QRS Excel** | Quarterly reference transaction samples |

### Import Order Note

Multiple import sources write to the same Branch Stats entries. The system uses an **upsert** approach — each importer finds or creates the entry for a given branch/month, then adds or overwrites only its specific metrics. Other metrics already stored by a different importer are left untouched. This means files can be uploaded in any order without data loss.

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
