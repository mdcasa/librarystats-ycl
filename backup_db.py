"""
Nightly backup of the whole YCL Statistics database to the shared drive.

Writes one zip per run, e.g.
    G:\\Shared drives\\Statistics\\Backups\\YCLStats_backup_2026-10-05_2100.zip
containing, for every table in the database:
    <table>.json   exact rows (types preserved) -- what restore_backup.py reads
    <table>.csv    the same rows, for opening in Excel
plus manifest.json (time, database host, row count per table).

Tables are read from the database itself, not the models, so a table with no
model (e.g. eresource_stats) is still backed up. users.password_hash is left
out on purpose: the shared drive is readable by more people than the app's
admins, and passwords can be reset in Admin -> Users after a restore.

Retention: every backup from the last 30 days, plus the first backup of each
month forever. Run by the "YCL Stats nightly backup" Windows scheduled task
(see Design/design.md -> Backups); safe to run by hand any time:
    python backup_db.py [--dest DIR] [--keep-days N] [--log FILE]
"""
import argparse
import csv
import io
import json
import os
import sys
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal

DEFAULT_DEST = r"G:\Shared drives\Statistics\Backups"
PREFIX = 'YCLStats_backup_'
EXCLUDED_COLUMNS = {('users', 'password_hash')}


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, memoryview)):
        return bytes(v).hex()
    return v


def run_backup(dest, keep_days):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import app, db
    from sqlalchemy import MetaData

    with app.app_context():
        url = db.engine.url
        if url.get_backend_name() != 'postgresql':
            raise SystemExit(f'Refusing to back up {url.get_backend_name()} -- DATABASE_URL is not '
                             f'set to the production Postgres database (got {url!r}).')

        os.makedirs(dest, exist_ok=True)
        stamp = datetime.now().strftime('%Y-%m-%d_%H%M')
        final_path = os.path.join(dest, f'{PREFIX}{stamp}.zip')
        tmp_path = final_path + '.partial'

        meta = MetaData()
        meta.reflect(bind=db.engine)
        manifest = {'created_at': datetime.now().isoformat(timespec='seconds'),
                    'database_host': url.host, 'database': url.database,
                    'excluded_columns': sorted('.'.join(c) for c in EXCLUDED_COLUMNS),
                    'tables': {}}

        # One read-only transaction so every table comes from the same moment.
        with db.engine.connect() as conn, conn.begin(), \
                zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for table in meta.sorted_tables:
                cols = [c for c in table.columns if (table.name, c.name) not in EXCLUDED_COLUMNS]
                order = [c for c in table.primary_key.columns] or cols[:1]
                rows = conn.execute(table.select().with_only_columns(*cols).order_by(*order)).all()
                names = [c.name for c in cols]

                data = [{n: _jsonable(v) for n, v in zip(names, r)} for r in rows]
                zf.writestr(f'{table.name}.json', json.dumps(data, ensure_ascii=False))

                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(names)
                w.writerows([[_jsonable(v) for v in r] for r in rows])
                zf.writestr(f'{table.name}.csv', buf.getvalue())

                manifest['tables'][table.name] = len(rows)
            zf.writestr('manifest.json', json.dumps(manifest, indent=2))

        # Only a complete zip gets the real name -- a crash mid-run leaves a
        # .partial file that pruning cleans up, never a truncated "backup".
        os.replace(tmp_path, final_path)

    pruned = _prune(dest, keep_days)
    total = sum(manifest['tables'].values())
    print(f'{datetime.now():%Y-%m-%d %H:%M} OK  {os.path.basename(final_path)}  '
          f'{len(manifest["tables"])} tables, {total:,} rows, '
          f'{os.path.getsize(final_path) / 1024:,.0f} KB; pruned {pruned}')
    return final_path


def _prune(dest, keep_days):
    """Keep the last keep_days days of backups plus the first backup of every
    month; delete leftover .partial files from interrupted runs."""
    cutoff = datetime.now() - timedelta(days=keep_days)
    backups = []
    for name in os.listdir(dest):
        path = os.path.join(dest, name)
        if name.startswith(PREFIX) and name.endswith('.partial'):
            os.remove(path)
            continue
        if not (name.startswith(PREFIX) and name.endswith('.zip')):
            continue
        try:
            when = datetime.strptime(name[len(PREFIX):-4], '%Y-%m-%d_%H%M')
        except ValueError:
            continue
        backups.append((when, path))

    first_of_month = {}
    for when, path in sorted(backups):
        first_of_month.setdefault((when.year, when.month), path)
    keep = set(first_of_month.values())

    pruned = 0
    for when, path in backups:
        if when < cutoff and path not in keep:
            os.remove(path)
            pruned += 1
    return pruned


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dest', default=DEFAULT_DEST)
    ap.add_argument('--keep-days', type=int, default=30)
    ap.add_argument('--log', help='append output to this file (the scheduled task runs windowless)')
    args = ap.parse_args()
    if args.log:
        sys.stdout = sys.stderr = open(args.log, 'a', encoding='utf-8', buffering=1)
    try:
        run_backup(args.dest, args.keep_days)
    except SystemExit:
        raise
    except Exception as e:
        print(f'{datetime.now():%Y-%m-%d %H:%M} FAILED  {type(e).__name__}: {e}', file=sys.stderr)
        raise
