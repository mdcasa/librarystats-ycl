"""
One-time load of FY2025-2026 Annual eResources totals from the SC State
Annual Report electronic-usage export ("Annual Stats for SC State" PDF).

Writes a single system-wide, annual Entry (year=2026 = the fiscal year's
ending calendar year, month=None, branch_id=None — Annual eResources has
has_branch=False, so no branch is set, matching the Online Stats convention)
with the four Annual eResources metrics:

  E-Book Circulation     227,486  (H12 total: DataAxle/RefUSA, Biblioboard,
                                    Hoopla e-books/comics/Bingepass, Overdrive/Libby e-books)
  E-Audio Circulation    273,966  (H13 total: Hoopla e-audio/music/Bingepass,
                                    Overdrive/Libby e-audio)
  E-Video Circulation     31,483  (E-video total: ABC Mouse, Brainfuse, Kanopy,
                                    Gale Presents Udemy, Hoopla Bingepass/TV/Movies,
                                    Lote4Kids, Mango Languages, Overdrive/Libby streaming)
  E-Serials Circulation  107,967  (E-serials total: Infobase Mailbox, EBSCO Flipster,
                                    Hoopla Bingepass magazines, Newsbank,
                                    Overdrive/Libby magazines, Value Line)

Grand total across all four: 640,902 — matches the PDF's "TOTAL USAGE ELECTRONIC".

Per-vendor breakdown is documented in eResources/YCL-Vendor-Data-Onboarding-Plan.md
as the crosswalk to use once Monthly eResources (vendor database usage) data is
being collected and needs to be tabulated into these same four annual buckets.
"""

import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from models import db, Category, Entry, EntryValue

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///librarystats.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# ── Data ─────────────────────────────────────────────────────────────────────

FY_ENDING_YEAR = 2026  # FY 2025-2026 (Jul 2025 - Jun 2026)

VALUES = {
    'E-Book Circulation':    227486,
    'E-Audio Circulation':   273966,
    'E-Video Circulation':    31483,
    'E-Serials Circulation': 107967,
}


def main(dry_run=False):
    print(f"{'DRY RUN - ' if dry_run else ''}Loading FY{FY_ENDING_YEAR} Annual eResources totals\n")

    with app.app_context():
        cat = Category.query.filter_by(name='Annual eResources').first()
        if not cat:
            print("ERROR: 'Annual eResources' category not found.")
            return

        metric_ids = {m.name: m.id for m in cat.metrics}
        missing = [name for name in VALUES if name not in metric_ids]
        if missing:
            print(f"ERROR: metric(s) not found on category: {missing}")
            return

        entry = Entry.query.filter_by(
            category_id=cat.id, branch_id=None, year=FY_ENDING_YEAR, month=None
        ).first()

        if entry:
            print(f"  Found existing entry {entry.id} for FY{FY_ENDING_YEAR} - will upsert values")
        else:
            print(f"  No existing entry for FY{FY_ENDING_YEAR} - will create one")

        if not dry_run:
            if not entry:
                entry = Entry(
                    category_id=cat.id,
                    branch_id=None,
                    year=FY_ENDING_YEAR,
                    month=None,
                    quarter=None,
                    submitted_by='SC State Annual Report import',
                    notes='FY2025-2026 electronic resource usage, loaded from SC State Annual Report export.',
                )
                db.session.add(entry)
                db.session.flush()

        for name, value in VALUES.items():
            metric_id = metric_ids[name]
            print(f"  {name}: {value:,}")
            if not dry_run:
                ev = EntryValue.query.filter_by(entry_id=entry.id, metric_id=metric_id).first()
                if ev:
                    ev.value_number = float(value)
                else:
                    db.session.add(EntryValue(entry_id=entry.id, metric_id=metric_id, value_number=float(value)))

        if not dry_run:
            db.session.commit()
            print(f"\n  -> committed entry {entry.id}")

    if dry_run:
        print("\nDry run complete. Run with --apply to write to DB.")
    else:
        print("\nDone.")


if __name__ == '__main__':
    import sys
    dry_run = '--apply' not in sys.argv
    main(dry_run=dry_run)
