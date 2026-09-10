"""Display formatting shared by the API, exports and templates."""

from app.config import Config


def format_price_value(value):
    """Format a property price for display in Excel.

    Non-positive or missing prices (-1 sentinel, 0, None) mean the price is
    not published, so we show 'P.O.A.' (Price on Application).
    """
    if value is None or value == '' or value == 'N/A' or value == 'None':
        return 'P.O.A.'
    try:
        float_value = float(value)
        return f"€{float_value:,.0f}" if float_value > 0 else 'P.O.A.'
    except (ValueError, TypeError):
        return 'P.O.A.'


def format_area_value(value):
    """Format area values for display in Excel"""
    if value is None or value == '' or value == 'N/A' or value == 'None':
        return '—'
    try:
        float_value = float(value)
        if float_value > 0:
            return f"{float_value:.0f}"
        else:
            return '—'
    except (ValueError, TypeError):
        if isinstance(value, str):
            cleaned = value.replace('m²', '').replace('m2', '').replace(',', '').strip()
            try:
                float_value = float(cleaned)
                if float_value > 0:
                    return f"{float_value:.0f}"
            except ValueError:
                pass
        return '—'

def display_source_name(source):
    """Map a raw scraper `source` value to its friendly agent name.

    Falls back to stripping a trailing 'Scraper' suffix for sources that are not
    in SOURCE_NAME_MAPPING (e.g. 'OlivehomesScraper' -> 'Olivehomes').
    """
    if not source or source == 'N/A':
        return 'N/A'
    if source in Config.SOURCE_NAME_MAPPING:
        return Config.SOURCE_NAME_MAPPING[source]
    if source.endswith('Scraper'):
        return source[:-7]
    return source


def assign_sardo_references(properties):
    """(Deprecated) SARDO reference IDs are now assigned natively in the database CTE."""
    return properties
