"""
Export all database tables to CSV files in ./db_export/
Run from project root: python db_export.py
Uses DATABASE_URL from .env (source database).
"""
import os, csv
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL not set in .env")

# SQLAlchemy requires postgresql:// not postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

TABLES = [
    "users",
    "categories",
    "metrics",
    "branches",
    "entries",
    "entry_values",
    "sirsi_checkouts",
    "annual_survey_metrics",
    "annual_survey_values",
    "quarterly_ref_closure_days",
]

out_dir = Path("db_export")
out_dir.mkdir(exist_ok=True)

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    for table in TABLES:
        result = conn.execute(text(f"SELECT * FROM {table}"))
        rows = result.fetchall()
        cols = list(result.keys())
        out_path = out_dir / f"{table}.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            writer.writerows(rows)
        print(f"  {table}: {len(rows)} rows → {out_path}")

print("\nExport complete. Upload the db_export/ folder and run db_import.py on the destination.")
