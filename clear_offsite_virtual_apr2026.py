"""
Clear OFFSITE Programming and VIRTUAL Programming metric values
for April 2026 from all Branch Stats entries.

Sets value_number to NULL for the affected EntryValue rows
(does not delete the entries or other metric values).
"""
from dotenv import load_dotenv
load_dotenv()

from app import app, db
from models import Entry, EntryValue, Metric, Category

with app.app_context():
    target_groups = {'OFFSITE Programming', 'VIRTUAL Programming'}

    # Get the Branch Stats category
    bs_cat = Category.query.filter_by(name='Branch Stats').first()
    if not bs_cat:
        print("ERROR: Branch Stats category not found.")
        exit(1)

    # Get metric IDs for OFFSITE and VIRTUAL groups
    metrics = Metric.query.filter(
        Metric.category_id == bs_cat.id,
        Metric.group_name.in_(target_groups)
    ).all()

    metric_ids = [m.id for m in metrics]
    print(f"Found {len(metrics)} OFFSITE/VIRTUAL metrics:")
    for m in metrics:
        print(f"  [{m.group_name}] {m.name}")

    # Get April 2026 Branch Stats entries
    entries = Entry.query.filter_by(
        category_id=bs_cat.id, month=4, year=2026
    ).all()
    entry_ids = [e.id for e in entries]
    print(f"\nFound {len(entries)} Branch Stats entries for April 2026:")
    for e in entries:
        print(f"  {e.branch_label}")

    if not entries:
        print("Nothing to do.")
        exit(0)

    # Find affected EntryValue rows that have non-null values
    affected = EntryValue.query.filter(
        EntryValue.entry_id.in_(entry_ids),
        EntryValue.metric_id.in_(metric_ids),
        EntryValue.value_number.isnot(None)
    ).all()

    print(f"\nEntryValue rows with non-null values: {len(affected)}")
    for ev in affected:
        branch = next(e.branch_label for e in entries if e.id == ev.entry_id)
        print(f"  {branch} / {ev.metric.name} = {ev.value_number}")

    if not affected:
        print("No non-null values found — nothing to clear.")
        exit(0)

    confirm = input(f"\nSet all {len(affected)} values to NULL? Type YES to confirm: ")
    if confirm.strip() != 'YES':
        print("Aborted.")
        exit(0)

    for ev in affected:
        ev.value_number = None
    db.session.commit()
    print(f"Done. Cleared {len(affected)} values.")
