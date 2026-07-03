"""
CRM API integration removed.
OPG/AbacusDesk CRM (opglms.abacusdesk.com) is no longer used by PALUCK Technologies.
This file is kept as a stub so any accidental imports do not crash the server.
"""


class CRMClient:
    def fetch_daily_leads(self, *args, **kwargs):
        print("[CRM] CRMClient.fetch_daily_leads: OPG CRM removed — no-op")
        return []

    def update_customer_details(self, *args, **kwargs):
        print("[CRM] CRMClient.update_customer_details: OPG CRM removed — no-op")
        return None

    def add_activity(self, *args, **kwargs):
        print("[CRM] CRMClient.add_activity: OPG CRM removed — no-op")
        return None

    def add_follow_up(self, *args, **kwargs):
        print("[CRM] CRMClient.add_follow_up: OPG CRM removed — no-op")
        return False
