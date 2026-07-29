from dotenv import load_dotenv
load_dotenv()
from app import app, db
from models import Category, Entry, Metric

with app.app_context():
    cat = Category.query.filter_by(name='Branch Stats').first()
    entries = Entry.query.filter_by(category_id=cat.id, year=2026, month=4).all()

    prog_metrics = {m.id: m.name for m in cat.metrics
                    if any(t in m.name for t in ['Sessions', 'Attendance'])}

    TYPE = ['ONSITE', 'OFFSITE', 'VIRTUAL']
    AGE  = ['0-5', '6-11', '12-18', '19+', 'General Interest']

    # Build sums like the report does
    sums = {}
    for e in entries:
        for ev in e.values:
            n = prog_metrics.get(ev.metric_id)
            if n and ev.value_number:
                sums[n] = sums.get(n, 0) + ev.value_number

    print("Per-type, per-age sessions stored in DB:\n")
    grand_sessions = 0
    for t in TYPE:
        for a in AGE:
            k = f'{t} Sessions {a}'
            v = sums.get(k, 0)
            if v:
                print(f"  {k}: {int(v)}")
                grand_sessions += v

    print(f"\nGrand total sessions: {int(grand_sessions)}")

    print("\nReport figures (ONSITE+OFFSITE+VIRTUAL per age):")
    report_total = 0
    for a in AGE:
        total = sum(sums.get(f'{t} Sessions {a}', 0) for t in TYPE)
        if total:
            print(f"  Sessions {a}: {int(total)}")
            report_total += total
    print(f"  Total across all age groups: {int(report_total)}")

    print("\nONSITE-only per age:")
    onsite_total = 0
    for a in AGE:
        v = sums.get(f'ONSITE Sessions {a}', 0)
        if v:
            print(f"  ONSITE Sessions {a}: {int(v)}")
            onsite_total += v
    print(f"  ONSITE total: {int(onsite_total)}")

    print("\nOFFSITE sessions by age:")
    for a in AGE:
        v = sums.get(f'OFFSITE Sessions {a}', 0)
        if v:
            print(f"  OFFSITE Sessions {a}: {int(v)}")

    print("\nVIRTUAL sessions by age:")
    for a in AGE:
        v = sums.get(f'VIRTUAL Sessions {a}', 0)
        if v:
            print(f"  VIRTUAL Sessions {a}: {int(v)}")
