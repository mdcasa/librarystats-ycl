"""
Delete all data for a specific month/year from the production DB.
Removes Entry + EntryValue records (cascade) and SirsiCheckout rows.

Usage:
    python delete_month.py <month> <year>
    python delete_month.py 4 2026
"""
import sys
from dotenv import load_dotenv
load_dotenv()

from app import app, db
from models import Entry, SirsiCheckout

if len(sys.argv) != 3:
    print("Usage: python delete_month.py <month> <year>")
    sys.exit(1)

month = int(sys.argv[1])
year  = int(sys.argv[2])

with app.app_context():
    entries = Entry.query.filter_by(month=month, year=year).all()
    sirsi   = SirsiCheckout.query.filter_by(month=month, year=year).count()

    print(f"About to delete all data for {month}/{year}:")
    print(f"  {len(entries):,} entries (+ their entry_values via cascade)")
    print(f"  {sirsi:,} sirsi_checkout rows")
    confirm = input("Type YES to confirm: ")
    if confirm.strip() != 'YES':
        print("Aborted.")
        sys.exit(0)

    for e in entries:
        db.session.delete(e)
    SirsiCheckout.query.filter_by(month=month, year=year).delete()
    db.session.commit()
    print("Done.")
