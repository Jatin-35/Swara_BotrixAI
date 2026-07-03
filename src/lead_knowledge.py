"""
Lead Knowledge / Customer Context — Swara The Fashion Street
============================================================
Builds a short per-customer context block appended to Priya's sale-announcement
system prompt.

Swara is a simple outbound INFORMATIONAL call to an existing customer, so this
only surfaces light identifying details (name / contact / city) from the uploaded
Excel calling list. There is deliberately no product / dealer / warranty / AMC /
CRM-vertical logic here — the sale flow lives entirely in the system prompt.
"""

# Values that mean "no real name" — address as Sir/Madam instead.
_PLACEHOLDER_NAMES = {"", "customer", "unknown", "n/a", "na", "-", "—"}


def build_lead_context(lead_data: dict, customer_name: str = None) -> str:
    """
    Build a short customer-context block from lead data for Swara calls.

    Args:
        lead_data: Dictionary of lead data (a row from the uploaded calling list).
        customer_name: Optional customer name override.

    Returns:
        Formatted context string to append to the system prompt. Returns an empty
        string when there is nothing useful to add (so nothing is injected).
    """
    if not isinstance(lead_data, dict):
        return ""

    name = str(lead_data.get('customer_name')
               or lead_data.get('name')
               or customer_name or '').strip()
    phone = str(lead_data.get('phone_number')
                or lead_data.get('mobile') or '').strip()
    city = str(lead_data.get('city')
               or lead_data.get('location')
               or lead_data.get('area') or '').strip()

    parts = []
    if name and name.lower() not in _PLACEHOLDER_NAMES:
        parts.append(f"Customer Name: {name}")
    if phone:
        parts.append(f"Contact Number: {phone}")
    if city:
        parts.append(f"City: {city}")

    # Nothing worth injecting — don't append an empty block.
    if not parts:
        return ""

    block = [
        "\n\n════════════════════════════════════",
        "CUSTOMER CONTEXT (existing Swara customer)",
        "════════════════════════════════════",
    ]
    block.extend(parts)
    block.append(
        "Use the name only if it is a real person's name (see IDENTITY rules); "
        "otherwise address as Sir/Madam. Do NOT read these details aloud."
    )
    block.append("════════════════════════════════════\n")
    return "\n".join(block)
