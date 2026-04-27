"""
Delete all entered/imported data from the production DB,
keeping categories, metrics, branches, users, and annual_survey_metrics intact.
"""
from dotenv import load_dotenv
load_dotenv()

from app import app, db
from models import Entry, EntryValue, SirsiCheckout, AnnualSurveyValue

with app.app_context():
    ev_count = EntryValue.query.count()
    e_count  = Entry.query.count()
    sc_count = SirsiCheckout.query.count()
    av_count = AnnualSurveyValue.query.count()

    print(f"About to delete:")
    print(f"  {ev_count:,} entry_values")
    print(f"  {e_count:,} entries")
    print(f"  {sc_count:,} sirsi_checkouts")
    print(f"  {av_count:,} annual_survey_values")
    confirm = input("Type YES to confirm: ")

    if confirm.strip() != 'YES':
        print("Aborted.")
    else:
        # Delete in FK order
        EntryValue.query.delete()
        Entry.query.delete()
        SirsiCheckout.query.delete()
        AnnualSurveyValue.query.delete()
        db.session.commit()
        print("Done. Categories, metrics, branches, users, and annual_survey_metrics are untouched.")
