import sys
import os
from datetime import datetime, timedelta
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from crm_api import CRMClient
from database import batch_upsert_leads, init_database

# Mapping from User Request
TYPE_MAPPING = {
    "End User": "Consumer Leads",
    "SSS": "Consumer Leads",
    "Distributor": "Channel",
    "Dealer": "Channel",
    "Sub Dealer": "Channel",
    "ASP": "ASP",
    "B2G": "Consumer Leads",
    "OEM": "Institutional",
    "CPO": "Institutional",
    "Fleet Operator": "Consumer Leads",
    "Corporate": "Consumer Leads",
    "Channel Partner": "Channel",
    "OEM/ODM": "Institutional",
    "Export": "Export",
    "Ecommerce": "Ecommerce",
}

def fetch_and_store_leads(date_str: str = None):
    """Fetch leads from CRM and store in database.

    This function is IDEMPOTENT — calling it multiple times for the same date
    will NOT create duplicate entries. Leads are matched by phone number:
      • If a lead with that phone already exists → update its data (preserve status)
      • If it does not exist → insert a new lead with status='pending'

    Args:
        date_str: Date in YYYY-MM-DD format. If None, defaults to yesterday.
    """
    # Ensure DB is ready
    init_database()

    client = CRMClient()

    # Use provided date or default to yesterday
    if date_str:
        target_date = date_str
        print(f"🚀 Fetching leads for specified date: {target_date}")
    else:
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        print(f"🚀 Fetching leads for yesterday: {target_date}")

    all_leads = client.fetch_daily_leads(target_date)

    if not all_leads:
        print("⚠️ No leads found.")
        return

    # Only process AMC leads
    leads = [l for l in all_leads if l.get('lead_type') == 'AMC']
    print(f"📦 Found {len(all_leads)} total leads, {len(leads)} AMC leads. Upserting into database (no duplicates)...")

    result = batch_upsert_leads(leads)
    print(f"🎉 Done. {result['created']} created, {result['updated']} status-reset, {result['skipped']} skipped. Re-fetching same date is always safe.")

if __name__ == "__main__":
    fetch_and_store_leads()
