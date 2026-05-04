"""
Remove ILL/ICL metric values from any branch that is not Rock Hill.
These metrics are Main-only and should never have been written to other branches.

Usage:
    python patch_remove_ill_icl_non_rockhill.py           # dry run
    python patch_remove_ill_icl_non_rockhill.py --apply   # delete from DB
"""
import sys
from dotenv import load_dotenv
load_dotenv()

from app import app, db
from models import Branch, Metric, Entry, EntryValue

APPLY = '--apply' in sys.argv

MAIN_ONLY_NAMES = {
    'ILL - Sent (Main ONLY)',
    'ILL - Received (Main ONLY)',
    'ICLs - Sent (Main ONLY)',
    'ICLs - Received (Main ONLY)',
}

with app.app_context():
    main_only_metrics = Metric.query.filter(Metric.name.in_(MAIN_ONLY_NAMES)).all()
    if not main_only_metrics:
        print('No Main-only metrics found — nothing to do.')
        sys.exit(0)

    main_only_ids = {m.id for m in main_only_metrics}
    print('Main-only metric IDs:', main_only_ids)

    rock_hill_branches = Branch.query.filter(Branch.name.ilike('%rock hill%')).all()
    rock_hill_ids = {b.id for b in rock_hill_branches}
    print('Rock Hill branch IDs:', rock_hill_ids)

    # Find EntryValues for main-only metrics on non-Rock Hill entries
    bad_evs = (
        EntryValue.query
        .join(Entry, Entry.id == EntryValue.entry_id)
        .filter(EntryValue.metric_id.in_(main_only_ids))
        .filter(Entry.branch_id.notin_(rock_hill_ids))
        .all()
    )

    if not bad_evs:
        print('No bad ILL/ICL values found.')
        sys.exit(0)

    print(f'\nFound {len(bad_evs)} bad value(s):')
    for ev in bad_evs:
        entry = Entry.query.get(ev.entry_id)
        branch = Branch.query.get(entry.branch_id)
        metric = Metric.query.get(ev.metric_id)
        print(f'  Entry {entry.id} | {branch.name} | {entry.year}-{entry.month:02d} '
              f'| {metric.name} = {ev.value_number}')

    if APPLY:
        for ev in bad_evs:
            db.session.delete(ev)
        db.session.commit()
        print(f'\nDeleted {len(bad_evs)} value(s).')
    else:
        print('\nDry run — pass --apply to delete.')
