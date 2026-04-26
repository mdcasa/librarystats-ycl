# YCL Statistics — Roadmap

Last updated: 2026-04-26

---

## Phase 1 — Data Completeness (Do Now)

The app is fully built but the database is only partially filled. Reports and dashboards will be incomplete until this is done.

| Task | How | Priority |
|---|---|---|
| Load SIRSI Circulation history | Upload one file/month for available months via `/upload` — **2024 files may not be recoverable** | 🔴 High |
| Load SIRSI Registration history | Same — upload for whatever months are available | 🔴 High |
| Load Princh printing history | Upload monthly files for any missing months | 🟡 Medium |
| Door counter data | Not loaded at all — upload `daily_door_count.xlsx` files if available | 🟡 Medium |
| Enter missing manual metrics | Outreach, Staff Training, 1-on-1 — blank in DB for most months | 🟡 Medium |

> **Note:** 2024 SIRSI historical files may not be available to retrieve. Load whatever is accessible — the app handles partial history gracefully and reports will simply show gaps for months with no data.

**Current data status (as of 2026-04-26):**

| Source | Status | Coverage |
|---|---|---|
| non-SIRSI Branch Stats | ✅ Loaded | Jan 2024 – Mar 2026, all branches |
| SIRSI Circulation | ⚠️ Partial | Aug 2025 only |
| SIRSI Registration | ⚠️ Partial | Aug 2025 only |
| Princh Printing | ⚠️ Partial | Some months, not full history |
| Online Stats | ✅ Loaded | Jan 2024 – Mar 2026 |
| Quarterly Reference Stats | ✅ Loaded | Q1/Jun 2025, Q2/Oct 2025, Q3/Jan 2026 |
| Door Counter | ❌ Not loaded | Gate Count came from non-SIRSI file |

---

## Phase 2 — Feature Gaps (Short Term)

- **Trend Over Time** — add Total Library Card Registrations to the metric selector (metric now exists in DB as of v4)
- **Separate programming entry form** — currently buried in the Branch Stats manual entry accordion; staff need a cleaner dedicated form for programming data
- **Director's Dashboard** — clarify with Juli what data she needs that isn't showing or displaying correctly

---

## Phase 3 — Ongoing Monthly Operations

Once Phase 1 is complete this is the standard recurring workflow:

| Frequency | Task |
|---|---|
| Monthly | Upload SIRSI Circulation file (`Checkouts by Branch and Shelving Location`) |
| Monthly | Upload SIRSI Registration file (`Number of New Library Users by Branch and Patron Type`) |
| Monthly | Upload Princh export (`princh-export_{start}_{end}.xlsx`) |
| Monthly | Enter any remaining manual metrics via Enter Data → Manual Entry |
| Quarterly | Enter QRS via Enter Data → Qrtly Ref Stats |
| Annually | Complete Annual Survey entry for each fiscal year |

---

## Phase 4 — Future

- **eResources** — if YCL starts tracking e-book/e-audio/e-video stats, reactivate the eResources category via Admin → Categories and begin entering data
- **New library deployment** — fork repo, adapt the ILS importer for that library's system (SIRSI is YCL-specific), rebrand, spin up new Supabase + Railway instance. See `design.md → Standing Up a New Instance`.
