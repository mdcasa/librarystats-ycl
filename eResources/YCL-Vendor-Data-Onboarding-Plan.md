# YCL Database Usage Tracking — Vendor Data Onboarding Plan

**Project:** yclstats.org — Database usage tracking module, referred to elsewhere in the app/docs as **"Monthly eResources"** (distinct from "Annual eResources" — see `Design/design.md`)
**Author:** Martin (Assistant Director, York County Library), drafted with Claude
**Status:** Draft — companion to `YCL-Database-Usage-Tracking-Design.md`
**Purpose:** Define the process for validating and onboarding real vendor usage data once actual exports/SUSHI responses are in hand, before building out the full harvester and manual ingestion paths.

---

## 1. Why This Document Exists

The main design document (`YCL-Database-Usage-Tracking-Design.md`) defines the target architecture and data model. This document covers the step that sits between "design is written" and "Phase 2/3 build starts": actually looking at real vendor data and confirming the assumptions in the design hold up before writing ingestion code against them.

---

## 2. Step 1 — Treat the First Real Export as a Schema Test

Before loading anything into `usage_monthly`, lay each sample vendor spreadsheet or SUSHI response next to the data model and check:

- **Metric names:** Does the vendor actually report `Total_Item_Investigations`, `Total_Item_Requests`, `Unique_Title_Requests` — or vendor-specific labels that need mapping?
- **Time grain:** Monthly, as assumed, or quarterly/annual for some vendors?
- **Row structure:** One row per database, or one file/response covering many databases at once? (Likely for EBSCO and Gale, where one SUSHI pull can return multiple titles in a single JSON response.)

---

## 3. Step 2 — Build a Metric-Name Crosswalk

Vendors won't all use COUNTER's exact vocabulary even when nominally COUNTER-compliant. Maintain a small mapping table:

| Vendor Metric Label | Canonical `metric` value (usage_monthly) |
|---|---|
| e.g. "Investigations" | `total_item_investigations` |
| e.g. "Full-Text Requests" | `total_item_requests` |

This keeps `usage_monthly` consistent across vendors, which is what makes the "by subject category" and "by vendor" dashboard views actually comparable instead of mixing incompatible metrics.

### 3a. Annual eResources bucket crosswalk (for FY tabulation)

Beyond the COUNTER metric-name crosswalk above, once monthly per-database usage is being collected here, it also needs to roll up into the same four buckets tracked by the **Annual eResources** category (`E-Book Circulation`, `E-Audio Circulation`, `E-Video Circulation`, `E-Serials Circulation` — see `Design/design.md`), so a fiscal year of monthly data can be tabulated into the same annual totals that currently come from the manual SC State Annual Report export.

The FY2025-2026 SC State export (`Monthly Stats 2025-2026.xlsx - Annual Stats for SC State.pdf`, loaded via `patch_fy2526_annual_eresources.py`) is the reference for which vendor/product maps to which bucket:

| Annual eResources bucket | Vendor / product |
|---|---|
| **E-Book Circulation** | DataAxle / Ref USA, Biblioboard, Hoopla e-books Instant, Hoopla e-books Flex, Hoopla comics, Hoopla Bingepass (comics/ebooks), Overdrive/Libby e-books |
| **E-Audio Circulation** | Hoopla e-audio Instant, Hoopla e-audio Flex, Hoopla music, Hoopla Bingepass (audio content), Overdrive/Libby e-audio |
| **E-Video Circulation** | ABC Mouse, Brainfuse, Kanopy, Gale Presents Udemy, Hoopla Bingepass (courses/videos), Hoopla TV, Hoopla Movies, Lote4Kids, Mango Languages, Overdrive/Libby streaming |
| **E-Serials Circulation** | Infobase: The Mailbox, EBSCO Flipster, Hoopla Bingepass (magazines), Newsbank, Overdrive/Libby magazines, Value Line |

Grand total across all four buckets = "TOTAL USAGE ELECTRONIC" on the SC State export (640,902 for FY2025-2026).

When Monthly eResources (`usage_monthly`) has a full fiscal year of data for these vendors, tabulating the next year's Annual eResources entry means: sum each vendor's FY-to-date usage metric (whichever COUNTER metric corresponds to "checkouts/uses" for that vendor — confirm per-vendor during Step 1 above), group by the bucket each vendor falls into per this table, and write the four bucket totals into an Annual eResources entry (`year` = the fiscal year's ending calendar year, `month=None`, system-wide) — the same shape `patch_fy2526_annual_eresources.py` writes by hand. This replaces the manual PDF-to-form step with a computed rollup once Monthly eResources is live.

---

## 4. Step 3 — Confirm Name-Matching Against the `databases` Table

With ~104 entries, do a one-time manual pass while the list is still small:

- Vendor exports often use slightly different names than the resources-by-subject page (e.g., "MasterFILE Complete" vs. "MasterFILE Premier").
- Add a `vendor_reported_name` or aliases field to `databases` if needed, so the harvester has a deterministic join key instead of relying on fuzzy string matching.

---

## 5. Step 4 — Prove the Pipeline on EBSCO First

EBSCO covers ~30 of the 104 entries on one account — highest leverage, lowest vendor count to validate against. Before touching any other vendor:

1. Pull one real EBSCO DR report (manually or via SUSHI test call).
2. Confirm the JSON shape matches the parser's expectations (`Report_Items[].Performance[].Instance[]`).
3. Confirm auth works with the credentials Troy (IT Manager) provides.
4. Run it against 2–3 known databases and sanity-check the numbers against EBSCO's own admin portal.

Only after this is proven end-to-end should the other adapters (`harvesters/gale.js`, etc.) be built out — the per-vendor adapter pattern is still the right approach, but EBSCO working correctly de-risks the rest.

---

## 6. Step 5 — Resolve Open Questions Using Real Data

Several open questions from the main design doc will resolve themselves once real exports or admin portals are in hand:

- Whether Gale's "Analytics on Demand" exposes SUSHI or is export-only
- Which "Manual/Verify" entries are genuinely manual vs. SUSHI-capable
- Identification of "Unknown vendor" entries

As each is confirmed, update the `Usage Data Method` and `Confidence` columns in `YCL_Database_Usage_Tracking_Inventory.xlsx` — that spreadsheet is effectively the Phase 5 punch list.

---

## 7. Step 6 — Finalize the Manual CSV Template From Real Exports

The main design doc proposes a `database_name, year_month, metric, value` template. Before locking this in, check 2–3 manual vendors' actual native exports (Mango, Tutor.com, Value Line) to confirm:

- Whether their reports are annual, session-based, or otherwise don't map cleanly to a monthly template
- Whether any require a transform step every time, which would justify revisiting the "script vs. form" decision in Section 6 of the main design doc sooner than planned

---

## 8. Summary Checklist

- [ ] Confirm real metric names/time grain from at least one sample export per major vendor
- [ ] Build and maintain the metric-name crosswalk table
- [ ] Add vendor-name aliasing to `databases` table where needed
- [ ] Complete one full EBSCO pull → parse → sanity-check cycle before building other adapters
- [ ] Update inventory spreadsheet's `Usage Data Method` / `Confidence` columns as vendors are confirmed
- [ ] Finalize manual CSV template shape based on real manual-vendor exports
