"""
Consolidate all OldConversion .xls files into a single .xlsx file
organized like Monthly5-8-dataonly.xlsx Branch Stats sheet.
"""
import xlrd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from collections import defaultdict

BASE = "Data files/OldConversion/"

HEADERS = [
    'Month', 'BRANCH',
    'New Library Card Registrations, Adult (includes YA)',
    'New Library Card Registrations, Juvenile',
    'Gate Count',
    'PC Reservations',
    'WiFi - Unique Sessions',
    'External Party Library Room Use',
    'Total Branch Circulation',
    'Hotspots Circulation',
    'Curbside',
    'ILL - Sent (Main ONLY)',
    'ILL - Received (Main ONLY)',
    'ICLs - Sent (MAIN ONLY)',
    'ICLs - Received (MAIN ONLY)',
    'Total Prints per Month',
    'Year',
]

MONTHS = ['July', 'August', 'September', 'October', 'November', 'December',
          'January', 'February', 'March', 'April', 'May', 'June']

MONTH_ABBR = {
    'July': 'July', 'Jul': 'July',
    'Aug': 'August', 'Aug ': 'August',
    'Sept': 'September', 'Sep': 'September',
    'Oct': 'October', 'Nov': 'November', 'Dec': 'December',
    'Jan': 'January', 'Feb': 'February', 'Mar': 'March',
    'April': 'April', 'Apr': 'April', 'May': 'May', 'June': 'June',
}

BRANCHES = ['Rock Hill', 'Clover', 'Fort Mill', 'Lake Wylie', 'York', 'Bookmobile/Outreach']

def normalize_branch(name):
    s = str(name).strip().lower()
    if 'rock hill' in s: return 'Rock Hill'
    if s == 'clover': return 'Clover'
    if 'fort mill' in s: return 'Fort Mill'
    if 'lake wylie' in s: return 'Lake Wylie'
    if s == 'york': return 'York'
    if 'bookmobile' in s or ('outreach' in s and 'clover' not in s): return 'Bookmobile/Outreach'
    return None

def get_val(v):
    """Convert xlrd cell value to int or None."""
    if isinstance(v, float):
        i = int(v)
        return i  # Keep zeros — some are real (COVID months)
    if isinstance(v, int):
        return v
    return None

def get_month_cols(ws):
    """Find the column index -> month name mapping by scanning for month header row."""
    for r in range(min(5, ws.nrows)):
        row = [ws.cell_value(r, c) for c in range(ws.ncols)]
        mc = {}
        for ci, v in enumerate(row):
            vs = str(v).strip()
            if vs in MONTH_ABBR:
                mc[ci] = MONTH_ABBR[vs]
        if len(mc) >= 10:
            return mc
    return {}

def year_for_month(fy_start, month):
    """Calendar year for a given month in a fiscal year starting in fy_start July."""
    if month in ('July', 'August', 'September', 'October', 'November', 'December'):
        return fy_start
    return fy_start + 1

def extract_branch_rows(ws, start_row, month_cols, max_rows=10):
    """
    Extract branch rows starting from start_row.
    Returns dict: branch_name -> {month: value}
    Stop at TOTAL/Comparison row or section header.
    """
    result = {}
    skip = {'total', 'comparison', 'grand total', 'postage paid', 'ims',
            'quarterly projection', 'quarterlyprojection', 'yearlyprojection',
            'yr projection', 'quarlyprojection', 'began at end', 'of july 2018',
            'peak usage', 'outside usage', 'bookmobile (outreach)/'}

    for r in range(start_row, min(start_row + max_rows, ws.nrows)):
        row = [ws.cell_value(r, c) for c in range(ws.ncols)]
        c0 = str(row[0]).strip()
        c1 = str(row[1]).strip() if len(row) > 1 else ''

        # Stop if we hit another section header
        if c0 and c1 == '' and 'July' not in c0 and 'Aug' not in c0:
            break

        label = c1 if c1 else c0
        if not label or label.lower() in skip:
            continue

        branch = normalize_branch(label)
        if branch is None:
            continue

        vals = {}
        for ci, month in month_cols.items():
            v = row[ci] if ci < len(row) else ''
            vals[month] = get_val(v)

        if branch in result:
            # Combine (for Bookmobile + Outreach in FY15-16)
            for m, v in vals.items():
                existing = result[branch].get(m)
                if v is not None and existing is not None:
                    result[branch][m] = existing + v
                elif v is not None:
                    result[branch][m] = v
        else:
            result[branch] = vals

    return result

def extract_system_row(ws, start_row, label_col1, month_cols, max_rows=8):
    """Extract a single system-level row (Borrowed, Loaned, Received, Sent, YCL)."""
    for r in range(start_row, min(start_row + max_rows, ws.nrows)):
        row = [ws.cell_value(r, c) for c in range(ws.ncols)]
        c1 = str(row[1]).strip() if len(row) > 1 else ''
        if c1.lower() == label_col1.lower():
            vals = {}
            for ci, month in month_cols.items():
                v = row[ci] if ci < len(row) else ''
                vals[month] = get_val(v)
            return vals
    return {}

def scan_sections(ws):
    """
    Scan sheet for section headers.
    Returns list of (row_idx, label).
    Section headers have col0 non-empty and col1 empty.
    They often contain month names in cols 3+ (that's the header row format).
    """
    sections = []
    for r in range(ws.nrows):
        row = [ws.cell_value(r, c) for c in range(ws.ncols)]
        c0 = str(row[0]).strip()
        c1 = str(row[1]).strip() if len(row) > 1 else ''
        if c0 and c1 == '' and c0 not in ('', ' '):
            sections.append((r, c0))
    return sections

# ─── Parsers ────────────────────────────────────────────────────────────────

def parse_simple_sheet(ws, fy_start):
    """
    Parse a single-FY sheet (FY15-16, FY16-17, FY17-18, FY18-19 format).
    Returns nested dict: (month, branch) -> {metric: value}
    """
    month_cols = get_month_cols(ws)
    if not month_cols:
        print("  WARNING: could not find month columns")
        return {}

    sections = scan_sections(ws)
    data = defaultdict(dict)

    # Accumulate circ components separately
    circ_cat = defaultdict(int)   # (month, branch) -> value
    circ_uncat = defaultdict(int)

    for sec_idx, (sec_row, sec_label) in enumerate(sections):
        # Next section start (to limit search)
        next_row = sections[sec_idx + 1][0] if sec_idx + 1 < len(sections) else ws.nrows

        label = sec_label.strip()

        # ── Gate Count ──
        if 'Door Count' in label:
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['gate'] = (data[(m, branch)].get('gate') or 0) + v

        # ── New Library Cards (total) ──
        elif any(x in label for x in ('New Library Card', 'Virtual Library Card', 'Self Reg Library Card')):
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['reg'] = (data[(m, branch)].get('reg') or 0) + v

        # ── PC Reservations / Internet Usage (PCs) ──
        elif 'PC Reservations' in label or 'Internet Usage (Library PC' in label:
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['pc'] = v

        # ── WiFi Sessions (per branch) ──
        elif any(x in label for x in ('Wi-Fi Sessions', 'WiFi Sessions', 'Wi-Fi Unique')):
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['wifi'] = v

        # ── Hotspot / Mi-Fi Circulations ──
        elif any(x in label for x in ('Mi-Fi Circulat', 'Hotspot Circulat')):
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['hotspot'] = (data[(m, branch)].get('hotspot') or 0) + v

        # ── Hotspot Single/Renewal checkout (FY23-24 adds these separately) ──
        elif any(x in label for x in ('Hotspot Single', 'Hotspot Renewal')):
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['hotspot'] = (data[(m, branch)].get('hotspot') or 0) + v

        # ── ILL (system total — put on Rock Hill) ──
        elif 'Interlibrary Loan' in label and 'Inter' == label[:5]:
            # ILL Borrowed = ILL Received; ILL Loaned = ILL Sent
            borrowed = extract_system_row(ws, sec_row + 1, 'Borrowed', month_cols)
            loaned = extract_system_row(ws, sec_row + 1, 'Loaned', month_cols)
            for m, v in borrowed.items():
                if v is not None:
                    data[(m, 'Rock Hill')]['ill_recv'] = v
            for m, v in loaned.items():
                if v is not None:
                    data[(m, 'Rock Hill')]['ill_sent'] = v

        # ── ICL / InterConsortial Loans (system total — put on Rock Hill) ──
        # FY15-16 uses 'Borrowed'/'Loaned'; FY16-17+ uses 'Received'/'Sent'
        elif any(x in label for x in ('InterConsortial', 'Consorital')):
            received = extract_system_row(ws, sec_row + 1, 'Received', month_cols)
            if not received:
                received = extract_system_row(ws, sec_row + 1, 'Borrowed', month_cols)
            sent = extract_system_row(ws, sec_row + 1, 'Sent', month_cols)
            if not sent:
                sent = extract_system_row(ws, sec_row + 1, 'Loaned', month_cols)
            for m, v in received.items():
                if v is not None:
                    data[(m, 'Rock Hill')]['icl_recv'] = v
            for m, v in sent.items():
                if v is not None:
                    data[(m, 'Rock Hill')]['icl_sent'] = v

        # ── Circulation: Cataloged ──
        elif 'Circs-Cataloged' in label or 'Cataloged Materials' in label:
            if 'INHOUSE' in label:
                continue  # Skip in-house for simplicity
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        circ_cat[(m, branch)] += v

        # ── Circulation: Uncataloged ──
        elif 'Circs-Uncataloged' in label or 'Uncataloged Material' in label:
            if 'INHOUSE' in label:
                continue
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        circ_uncat[(m, branch)] += v

        # ── Meeting Room (External Party) ──
        elif 'Outside usage of meeting' in label or 'meeting room' in label.lower():
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['meeting_room'] = v

    # Combine circulation
    all_keys = set(circ_cat.keys()) | set(circ_uncat.keys())
    for key in all_keys:
        total = (circ_cat.get(key) or 0) + (circ_uncat.get(key) or 0)
        if total:
            data[key]['circ'] = total

    return data


def parse_comparison_sheet(ws, fy_start):
    """
    Parse a comparison-format sheet (FY19-20 through FY23-24).
    target prefix is derived from fy_start: e.g. 2019->2020 = '19-20'.
    """
    prefix = f"{str(fy_start)[2:]}-{str(fy_start + 1)[2:]}"
    print(f"  Parsing comparison sheet, looking for prefix '{prefix}'")

    month_cols = get_month_cols(ws)
    if not month_cols:
        print("  WARNING: could not find month columns")
        return {}

    sections = scan_sections(ws)
    data = defaultdict(dict)

    for sec_idx, (sec_row, sec_label) in enumerate(sections):
        next_row = sections[sec_idx + 1][0] if sec_idx + 1 < len(sections) else ws.nrows
        label = sec_label.strip().lstrip()

        # Only process sections for our target FY.
        # Also allow generic (un-prefixed) labels for certain metrics
        # like 'Outside usage of meeting rooms' in FY22-23.
        # But exclude sections that carry a DIFFERENT year prefix (prior year data).
        is_target = label.startswith(prefix) or label.startswith(' ' + prefix)
        other_fy_prefixes = [f"{str(y)[2:]}-{str(y+1)[2:]}" for y in range(2015, 2025) if y != fy_start]
        has_other_prefix = any(label.startswith(p) or label.startswith(' ' + p) for p in other_fy_prefixes)
        is_generic_ok = (any(x in label for x in ('Outside usage of meeting', 'meeting room'))
                         and not has_other_prefix)
        if not is_target and not is_generic_ok:
            continue

        # Strip the prefix from the label for matching
        content = label.replace(prefix, '').strip() if is_target else label

        if 'Door Count' in content or 'Door count' in content:
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['gate'] = (data[(m, branch)].get('gate') or 0) + v

        elif any(x in content for x in ('New Library Card', 'Virtual Library Card', 'Self Reg Library Card')):
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['reg'] = (data[(m, branch)].get('reg') or 0) + v

        elif 'PC Reservations' in content:
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['pc'] = v

        elif any(x in content for x in ('Wi-Fi', 'WiFi', 'Wi-fi')):
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['wifi'] = v

        elif any(x in content for x in ('Mi-Fi', 'Hotspot Circulat')):
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['hotspot'] = (data[(m, branch)].get('hotspot') or 0) + v

        elif 'Hotspot Single' in content or 'Hotspot Renewal' in content:
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['hotspot'] = (data[(m, branch)].get('hotspot') or 0) + v

        elif 'Interlibrary Loan' in content:
            borrowed = extract_system_row(ws, sec_row + 1, 'Borrowed', month_cols)
            loaned = extract_system_row(ws, sec_row + 1, 'Loaned', month_cols)
            for m, v in borrowed.items():
                if v is not None:
                    data[(m, 'Rock Hill')]['ill_recv'] = v
            for m, v in loaned.items():
                if v is not None:
                    data[(m, 'Rock Hill')]['ill_sent'] = v

        elif 'Outside usage of meeting' in content or 'meeting room' in content.lower():
            rows = extract_branch_rows(ws, sec_row + 1, month_cols, next_row - sec_row - 1)
            for branch, vals in rows.items():
                for m, v in vals.items():
                    if v is not None:
                        data[(m, branch)]['meeting_room'] = v

    return data


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    # All data: (fy_start, month, branch) -> {metric: value}
    all_data = {}

    files = [
        # (path, sheet_name, fy_start, format)
        (BASE + "Annual stats FY 15-16-17.xls", "FY15-16",        2015, "simple"),
        (BASE + "Annual stats FY 15-16-17.xls", "FY16-17 Stats",  2016, "simple"),
        (BASE + "Annual stats FY 17-18.xls",    "FY17-18 Stats",  2017, "simple"),
        (BASE + "Annual stats FY 18-19.xls",    "FY18-19 Stats",  2018, "simple"),
        (BASE + "ANNUAL Stats 19-20.xls",       0,                2019, "comparison"),
        (BASE + "20-21 ANNUAL STATS.xls",       0,                2020, "comparison"),
        (BASE + "21-22 Annual Stats.xls",       0,                2021, "comparison"),
        (BASE + "22-23 Annual Stats.xls",       0,                2022, "comparison"),
        (BASE + "23-24 Annual Stats.xls",       0,                2023, "comparison"),
    ]

    for path, sheet, fy_start, fmt in files:
        print(f"\nReading {path.split('/')[-1]}, sheet={sheet}, FY{fy_start}-{fy_start+1}")
        wb = xlrd.open_workbook(path)
        if isinstance(sheet, int):
            ws = wb.sheets()[sheet]
        else:
            ws = wb.sheet_by_name(sheet)

        if fmt == "simple":
            sheet_data = parse_simple_sheet(ws, fy_start)
        else:
            sheet_data = parse_comparison_sheet(ws, fy_start)

        # Store with fy_start as key
        for (month, branch), metrics in sheet_data.items():
            key = (fy_start, month, branch)
            if key not in all_data:
                all_data[key] = {}
            all_data[key].update(metrics)

        print(f"  Extracted {len(sheet_data)} (month, branch) entries")

    # ── Write output spreadsheet ──────────────────────────────────────────
    wb_out = openpyxl.Workbook()
    ws_out = wb_out.active
    ws_out.title = "Branch Stats"

    # Header row
    for ci, h in enumerate(HEADERS, 1):
        cell = ws_out.cell(row=1, column=ci, value=h)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(fill_type="solid", fgColor="D9E1F2")

    row_num = 2

    # Output in fiscal year order, then month order, then branch order
    fy_years = sorted(set(k[0] for k in all_data.keys()))

    for fy_start in fy_years:
        for month in MONTHS:
            for branch in BRANCHES:
                key = (fy_start, month, branch)
                metrics = all_data.get(key, {})
                cal_year = year_for_month(fy_start, month)

                row = [
                    month,
                    branch,
                    metrics.get('reg'),          # Adult (total reg, no adult/juv split)
                    None,                         # Juvenile (not available in old files)
                    metrics.get('gate'),
                    metrics.get('pc'),
                    metrics.get('wifi'),
                    metrics.get('meeting_room'),
                    metrics.get('circ'),
                    metrics.get('hotspot'),
                    None,                         # Curbside
                    metrics.get('ill_sent'),
                    metrics.get('ill_recv'),
                    metrics.get('icl_sent'),
                    metrics.get('icl_recv'),
                    None,                         # Prints
                    cal_year,
                ]

                for ci, v in enumerate(row, 1):
                    ws_out.cell(row=row_num, column=ci, value=v)
                row_num += 1

    # Freeze header
    ws_out.freeze_panes = "A2"

    # Auto-fit column widths (approximate)
    col_widths = [12, 22, 18, 18, 12, 14, 16, 16, 18, 16, 10, 16, 16, 16, 16, 14, 8]
    for ci, w in enumerate(col_widths, 1):
        ws_out.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = w

    out_path = "Data files/OldConversion/Historical_Stats_FY2015-2024.xlsx"
    wb_out.save(out_path)
    print(f"\nSaved {out_path}")
    print(f"Total rows written: {row_num - 2} (excluding header)")


if __name__ == "__main__":
    main()
