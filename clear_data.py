"""
Delete all entered/imported data from the production DB,
keeping categories, metrics, and branches intact.
"""
from dotenv import load_dotenv
load_dotenv()

from app import app, db
from models import Entry, EntryValue, SirsiCheckout

with app.app_context():
    ev_count = EntryValue.query.count()
    e_count  = Entry.query.count()
    sc_count = SirsiCheckout.query.count()

    print(f"About to delete:")
    print(f"  {ev_count:,} entry_values")
    print(f"  {e_count:,} entries")
    print(f"  {sc_count:,} sirsi_checkouts")
    confirm = input("Type YES to confirm: ")

    if confirm.strip() != 'YES':
        print("Aborted.")
    else:
        # Delete in FK order
        EntryValue.query.delete()
        Entry.query.delete()
        SirsiCheckout.query.delete()
        db.session.commit()
        print("Done. Categories, metrics, and branches are untouched.")
