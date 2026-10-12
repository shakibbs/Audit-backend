"""Cleans a phone number into one standard form (E.164), so every way of writing it gives the same code."""
import phonenumbers

DEFAULT_REGION = 'US'  # numbers without a country code are read as US numbers


def normalize(raw: str, region: str = DEFAULT_REGION) -> str | None:
    """'(916) 555-4471' → '+19165554471'. None when it cannot be a phone number."""
    try:
        number = phonenumbers.parse(str(raw), region)
    except phonenumbers.NumberParseException:
        return None
    # "Possible" (right length for its country), not "valid": real records must never be dropped for an unusual range.
    if not phonenumbers.is_possible_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
