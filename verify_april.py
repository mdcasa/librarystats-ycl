from dotenv import load_dotenv
load_dotenv()
from app import app, db
from models import Category, Entry, Metric

with app.app_context():
    cat = Category.query.filter_by(name='Branch Stats').first()
    entries = (Entry.query
               .filter_by(category_id=cat.id, year=2026, month=4)
               .all())

    prog_metric_ids = {m.id: m.name for m in cat.metrics
                       if any(t in m.name for t in ['Sessions', 'Attendance',
                                                     'Total Branch Circulation',
                                                     'New Library Card'])}
    sirsi_names = {'Total Branch Circulation', 'Hotspots Circulation', 'Locker Circulation',
                   'New Library Card Registrations, Adult', 'New Library Card Registrations, Juvenile'}
    sirsi_ids = {m.id for m in cat.metrics if m.name in sirsi_names}

    print(f"Entries for April 2026: {len(entries)}\n")
    for e in sorted(entries, key=lambda x: x.branch.name):
        vals = {ev.metric_id: ev.value_number for ev in e.values}
        print(f"  {e.branch.name}")
        for mid, name in sorted(prog_metric_ids.items(), key=lambda x: x[1]):
            v = vals.get(mid)
            if v is not None:
                flag = " *** SIRSI FIELD - SHOULD BE EMPTY ***" if mid in sirsi_ids else ""
                print(f"    {name}: {int(v)}{flag}")
        print()
