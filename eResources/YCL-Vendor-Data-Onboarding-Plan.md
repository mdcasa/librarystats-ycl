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
