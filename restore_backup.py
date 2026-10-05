"""
Load a backup zip made by backup_db.py into a NEW local SQLite file -- never
into production. Use it to:
  * check a backup is complete and readable (row counts are compared with the
    backup's manifest), and
  * look up values as they were on the backup date, e.g. to recover numbers
    that were deleted or overwritten since.

    python restore_backup.py <backup.zip> [--out restored.db]

To browse the restored copy in the app, run it with that file as its database:
    set DATABASE_URL=sqlite:///C:/path/to/restored.db  &&  python app.py
Users come back without passwords (backups leave password hashes out), so set
one with a short script or in Admin -> Users from another admin account.

Putting a restored value back into production is a deliberate, per-value step
(e.g. the Restore button in Admin -> Change History, or a reviewed one-off
script) -- this tool intentionally has no "overwrite production" mode.
"""
import argparse
import json
import os
import sys
import zipfile
from datetime import date, datetime

from sqlalchemy import Column, MetaData, Table, Text, create_engine, select, func
from sqlalchemy.types import Date, DateTime

NO_PASSWORD = '!restored-from-backup-no-password'


def restore(zip_path, out_path):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from models import db  # model metadata only; doesn't start the app

    if os.path.exists(out_path):
        raise SystemExit(f'{out_path} already exists -- pick a new --out file.')

    engine = create_engine(f'sqlite:///{out_path}')
    meta = MetaData()
    for t in db.metadata.sorted_tables:
        t.to_metadata(meta)

    with zipfile.ZipFile(zip_path) as zf:
        manifest = json.loads(zf.read('manifest.json'))
        tables = {}
        for name in manifest['tables']:
            rows = json.loads(zf.read(f'{name}.json'))
            if name not in meta.tables:
                # A table with no model (e.g. eresource_stats): keep its columns as text.
                cols = list(rows[0].keys()) if rows else ['id']
                Table(name, meta, *[Column(c, Text) for c in cols])
            tables[name] = rows

    meta.create_all(engine)
    mismatches = []
    with engine.begin() as conn:
        for name, rows in tables.items():
            table = meta.tables[name]
            date_cols = {c.name: type(c.type) for c in table.columns
                         if isinstance(c.type, (DateTime, Date))}
            for r in rows:
                for c, typ in date_cols.items():
                    if r.get(c):
                        r[c] = (datetime.fromisoformat(r[c]) if typ is DateTime
                                else date.fromisoformat(r[c][:10]))
                if name == 'users':
                    r.setdefault('password_hash', NO_PASSWORD)
            if rows:
                conn.execute(table.insert(), rows)
        for name, expected in manifest['tables'].items():
            got = conn.execute(select(func.count()).select_from(meta.tables[name])).scalar()
            if got != expected:
                mismatches.append(f'{name}: backup says {expected}, restored {got}')

    print(f'Backup from {manifest["created_at"]} ({manifest["database_host"]}) '
          f'restored to {out_path}: {len(tables)} tables, '
          f'{sum(manifest["tables"].values()):,} rows.')
    if mismatches:
        print('ROW COUNT MISMATCHES:\n  ' + '\n  '.join(mismatches))
        raise SystemExit(1)
    print('All row counts match the backup manifest.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('zip_path')
    ap.add_argument('--out', default=None, help='new SQLite file (default: next to the zip)')
    a = ap.parse_args()
    restore(a.zip_path, a.out or os.path.splitext(a.zip_path)[0] + '_restored.db')
