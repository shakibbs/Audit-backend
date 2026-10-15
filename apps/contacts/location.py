"""Where the person probably is, from the number's area code: state, possible time zones, country, confidence.

Built on the phonenumbers library's offline area-code data, with corrections below for US area codes that span two
time zones (where the library gives one, sometimes the wrong one) and time zones for the other +1 countries.
CORRECTIONS ARE TO VERIFY against NANPA / tz data before results go to clients.
Confidence: 'medium' = area code with one time zone; 'low' = several possible zones or unknown (the Rulebook's
location_uncertain_levels: results are reported as "possible", never dropped). 'high' is for a ZIP code (later).
"""
import phonenumbers
from phonenumbers import geocoder, timezone

ET, CT, MT, PT = 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles'
# US area codes spanning two zones, or where the library's single zone is wrong. To verify.
SPLIT_AREA_CODES = {
    '219': [CT],  # NW Indiana (Gary, Hammond) is Central
    '850': [CT, ET], '448': [CT, ET],  # Florida panhandle: Pensacola Central, Tallahassee Eastern
    '812': [ET, CT], '930': [ET, CT],  # southern Indiana, SW corner Central
    '270': [CT, ET], '364': [CT, ET],  # western Kentucky
    '423': [ET, CT], '931': [CT, ET],  # Tennessee
    '906': [ET, CT],  # Michigan Upper Peninsula, western counties Central
    '915': [MT],  # El Paso, Texas: Mountain
    '432': [CT, MT],  # west Texas
    '785': [CT, MT], '620': [CT, MT],  # Kansas, western counties Mountain
    '308': [CT, MT],  # Nebraska panhandle
    '701': [CT, MT], '605': [CT, MT],  # the Dakotas
    '208': ['America/Boise', PT], '986': ['America/Boise', PT],  # Idaho: south Mountain, north Pacific
    '541': [PT, 'America/Boise'], '458': [PT, 'America/Boise'],  # Oregon, Malheur County Mountain
    '928': ['America/Phoenix', MT],  # Arizona; the Navajo Nation keeps daylight time
}
# Other countries in the +1 numbering plan (the library lists every zone for them).
NANP_COUNTRY_ZONE = {
    'JM': 'America/Jamaica', 'PR': 'America/Puerto_Rico', 'DO': 'America/Santo_Domingo', 'BS': 'America/Nassau',
    'BB': 'America/Barbados', 'TT': 'America/Port_of_Spain', 'BM': 'Atlantic/Bermuda', 'KY': 'America/Cayman',
    'VI': 'America/St_Thomas', 'GU': 'Pacific/Guam', 'AG': 'America/Antigua', 'AI': 'America/Anguilla',
    'DM': 'America/Dominica', 'GD': 'America/Grenada', 'KN': 'America/St_Kitts', 'LC': 'America/St_Lucia',
    'VC': 'America/St_Vincent', 'VG': 'America/Tortola', 'MS': 'America/Montserrat', 'TC': 'America/Grand_Turk',
    'SX': 'America/Lower_Princes', 'AS': 'Pacific/Pago_Pago', 'MP': 'Pacific/Saipan',
}
US_TERRITORIES = {'PR', 'VI', 'GU', 'AS', 'MP'}  # US law applies; flagged by country, not as "outside the US"
STATES = {
    'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT',
    'Delaware': 'DE', 'District of Columbia': 'DC', 'Washington D.C.': 'DC', 'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI',
    'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA',
    'Maine': 'ME', 'Maryland': 'MD', 'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS',
    'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ',
    'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK',
    'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD',
    'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA',
    'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY',
}


def state_code(description: str) -> str:
    """'California' → CA; 'New York, NY' → NY; '' when it is not a US state."""
    if ', ' in description:
        tail = description.rsplit(', ', 1)[1]
        if len(tail) == 2 and tail in STATES.values():
            return tail
    return STATES.get(description, '')


def locate(e164: str) -> dict:
    """Location fields for a cleaned number ('+19165550001'). Unknown parts stay empty, never guessed."""
    unknown = {'recipient_state': '', 'time_zones': [], 'country': '', 'is_non_us': False, 'location_confidence': 'low', 'location_source': ''}
    try:
        number = phonenumbers.parse(e164)
    except phonenumbers.NumberParseException:
        return unknown
    country = phonenumbers.region_code_for_number(number) or ''
    fields = {**unknown, 'country': country, 'location_source': 'area_code', 'is_non_us': country not in ('US', '', *US_TERRITORIES)}
    if country == 'US':
        fields['recipient_state'] = state_code(geocoder.description_for_number(number, 'en'))
        area = str(number.national_number)[:3]
        zones = SPLIT_AREA_CODES.get(area) or list(timezone.time_zones_for_number(number))
    elif country in NANP_COUNTRY_ZONE:
        zones = [NANP_COUNTRY_ZONE[country]]
    else:
        zones = list(timezone.time_zones_for_number(number))
    zones = [] if len(zones) > 4 else zones  # the library's "every zone" answer means unknown
    fields['time_zones'] = zones
    fields['location_confidence'] = 'medium' if len(zones) == 1 else 'low'
    return fields
