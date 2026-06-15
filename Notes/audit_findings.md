# Audit Findings — 2026-05-12

> Steps 1 & 2 complete (importer code + report aggregation). Steps 3–5 pending.

---

## Step 1 — Importer Audit

### FINDING 1 — QRS importer uses skip-not-upsert (Low)
**File:** `import_excel.py` line 665-668  
`import_quarterly_ref` skips rows that already exist in the DB (`if entry_exists_quarterly: skipped += 1; continue`). Every other importer upserts. This contradicts the CLAUDE.md rule "importers upsert — never skip." Re-uploading a corrected QRS file will silently leave stale values in place.

### FINDING 2 — `col_index` truthiness hazard (Informational)
**File:** `import_excel.py` lines 332, 564  
```python
month_idx = col_index(headers, 'Month Num') or col_index(headers, 'Month')
```
`col_index` returns `None` when not found and an `int` when found. If 'Month Num' were column 0, the `or` would skip it. Practically impossible (column 0 is always Branch or Year), but the pattern is fragile. Low risk, no action needed now.

### FINDING 3 — All other importers look correct
- `import_branch_stats`: SIRSI metrics protected ✓, desk branches skipped ✓, Main-only metrics gated ✓, upsert logic correct ✓
- `import_sirsi_checkouts`: charge + renewal summing correct ✓, hotspot-only for hotspot circ ✓, locker-to-parent mapping correct ✓
- `import_new_library_users`: adult/juvenile profile lists match known patron types ✓
- `import_door_count`, `import_princh`: upsert via `_upsert_branch_stat` ✓
- `import_google_forms_stats`: SIRSI metrics protected, year inferred from timestamp ✓
- `import_annual_comparables`: delegated to `import_annual.py` (not audited in this pass)

---

## Step 2 — Report Aggregation Audit

### FINDING 4 — Inconsistent branch exclusions across `fy_totals` variants (Low)

Three `fy_totals` implementations omit exclusions that `_real_branch_q()` applies:

| Function | Excl. System Wide | Excl. Lockers | Excl. Administration | Excl. is_desk |
|---|---|---|---|---|
| `_real_branch_q()` (canonical) | ✓ | ✓ | ✓ | ✓ |
| `report_monthly_stats.get_sums` | ✓ | ✓ | ✓ | ✓ |
| `report_fiscal` branches list | ✓ | ✓ | ✓ | ✓ |
| `report_annual` (uses `_real_branch_q`) | ✓ | ✓ | ✓ | ✓ |
| `report_overview.fy_totals` (line 2815) | ✓ | ✓ | **✗** | **✗** |
| `report_impact.fy_totals` (line 2889) | ✓ | ✓ | ✓ | **✗** |
| `report_impact_pdf.fy_totals` (line 3021) | ✓ | ✓ | **✗** | **✗** |
| `report_impact_docx._fy_totals` (line 3162) | ✓ | ✓ | **✗** | **✗** |

**Practical risk today: low.** Desk branches never receive Branch Stats entries (import skips them) and Administration was just added with no data. But if either ever gets entries, these reports will overcount.

**Recommended fix:** Extract a shared helper so all callers use the same exclusion logic:
```python
def _is_excluded_branch(branch):
    if not branch:
        return False
    n = branch.name
    return (n == 'YCL (System Wide)' or n == 'Administration'
            or 'locker' in n.lower() or branch.is_desk)
```

### FINDING 5 — `_branches_for_category` omits Administration (Informational)
**File:** `app.py` lines 438-441  
The data entry form branch dropdown excludes lockers, desks, and System Wide but not Administration. Administration could appear in the dropdown for Branch Stats/Online Stats entry forms. Not a data corruption risk, just a UX oddity.

---

## Steps 3–5 — Pending

- **Step 3:** Run `python test_monthly.py` smoke test
- **Step 4:** Live DB spot checks (duplicate entries, orphaned values, FY24/FY25 totals vs. verified)
- **Step 5:** `/security-review` on current branch

---

## Summary

No critical bugs found. Two actionable issues:
1. **Fix (low priority):** Make `import_quarterly_ref` upsert instead of skip.
2. **Fix (low priority):** Extract a shared branch-exclusion helper and use it in all four `fy_totals` variants.
