"""
Import CSV files from ./db_export/ into a destination database.
Run: python db_import.py postgresql://user:pass@host/dbname
Uses the destination URL as a command-line argument (NOT .env, to avoid
accidentally overwriting your source DB).
"""
import sys, os, csv
from pathlib import Path
from sqlalchemy import create_engine, text

if len(sys.argv) < 2:
    raise SystemExit("Usage: python db_import.py <DESTINATION_DATABASE_URL>")

DATABASE_URL = sys.argv[1]
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Import order respects foreign key dependencies
TABLES = [
    "users",
    "categories",
    "branches",
    "metrics",
    "entries",
    "entry_values",
    "sirsi_checkouts",
    "annual_survey_metrics",
    "annual_survey_values",
    "quarterly_ref_closure_days",
]

in_dir = Path("db_export")
if not in_dir.exists():
    raise SystemExit("db_export/ folder not found. Run db_export.py first.")

BATCH_SIZE = 200

engine = create_engine(DATABASE_URL)

print("Clearing destination tables...")
with engine.begin() as conn:
    conn.execute(text("SET session_replication_role = replica"))
    for table in TABLES:
        conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
    conn.execute(text("SET session_replication_role = DEFAULT"))

for table in TABLES:
    csv_path = in_dir / f"{table}.csv"
    if not csv_path.exists():
        print(f"  {table}: no CSV found, skipping")
        continue

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"  {table}: empty, skipping")
        continue

    cols = list(rows[0].keys())
    col_list = ", ".join(cols)
    val_list = ", ".join(f":{c}" for c in cols)
    insert_sql = text(f"INSERT INTO {table} ({col_list}) VALUES ({val_list})")

    cleaned = [{k: (None if v == "" else v) for k, v in row.items()} for row in rows]

    total = len(cleaned)
    imported = 0
    for i in range(0, total, BATCH_SIZE):
        batch = cleaned[i:i + BATCH_SIZE]
        with engine.begin() as conn:
            conn.execute(insert_sql, batch)
        imported += len(batch)
        print(f"  {table}: {imported}/{total} rows...", end="\r")

    print(f"  {table}: {total} rows imported          ")

print("Resetting sequences...")
with engine.begin() as conn:
    seq_sql = text("""
        SELECT 'SELECT SETVAL(' || quote_literal(s.relname) ||
               ', COALESCE(MAX(t.' || quote_ident(a.attname) || '), 1)) FROM ' ||
               quote_ident(n.nspname) || '.' || quote_ident(c.relname) || ';'
        FROM pg_class s
        JOIN pg_depend d ON d.objid = s.oid
        JOIN pg_class c ON c.oid = d.refobjid
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = d.refobjsubid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE s.relkind = 'S'
          AND n.nspname = 'public'
    """)
    reset_statements = conn.execute(seq_sql).fetchall()
    for (stmt,) in reset_statements:
        conn.execute(text(stmt))

print("Import complete.")
