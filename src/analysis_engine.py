from database import update_lead_status, update_all_leads_by_phone, get_lead_by_phone


def sync_not_connected_call(
    phone_number: str,
    lead_id: int = None,
    record_id: str = None,
    scenario: str = "not_answered",
):
    """Update local lead status for a call that was never truly connected (or dropped instantly).

    Args:
        phone_number: Customer phone number.
        lead_id:      Local lead table ID (optional but recommended).
        record_id:    Exact Cube call record ID (unused now, kept for call-site compatibility).
        scenario:     'not_answered' | 'dropped'
    """
    print(f"📵 sync_not_connected_call: phone={phone_number}, scenario={scenario}, "
          f"lead_id={lead_id}, record_id={record_id!r}")

    # ── Update local lead status ───────────────────────────────────────────
    # Use phone-based bulk update so ALL duplicate rows for this number
    # reflect the correct status in the UI (old rows from before dedup fix).
    if phone_number:
        try:
            updated = update_all_leads_by_phone(phone_number, "not_connected")
            print(f"✅ sync_not_connected_call: {updated} lead row(s) for {phone_number} → 'not_connected'")
        except Exception as lead_err:
            print(f"⚠️ sync_not_connected_call: Phone-based status update failed: {lead_err}")
            # Fallback: single-ID update
            if lead_id:
                try:
                    update_lead_status(lead_id, "not_connected")
                except Exception:
                    pass
    elif lead_id:
        try:
            update_lead_status(lead_id, "not_connected")
            print(f"✅ sync_not_connected_call: lead {lead_id} → 'not_connected'")
        except Exception as lead_err:
            print(f"⚠️ sync_not_connected_call: Could not update lead status: {lead_err}")
