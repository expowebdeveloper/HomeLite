"""PDF and Excel report generation."""

import logging

from app.utils.formatting import assign_sardo_references

import io
import pandas as pd
import re
import urllib.request
from app.extensions import pdf_generator
from app.utils.formatting import display_source_name
from app.utils.formatting import format_area_value
from app.utils.formatting import format_price_value
from datetime import datetime, timedelta
from flask import request




def crawl_missing_details_live(prop):
    """Attempt a fast crawl of missing details from the property's live URL using HTTP regex matching"""
    url = prop.get('property_url')
    if not url or url.startswith('sardo://'):
        return None, None
        
    try:
        import urllib.request
        import re
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
        construction_year = None
        energy_rating = None
        
        # Look for Year Built
        year_pattern = re.compile(
            r'(?:build\s+year|year\s+built|built\s+in|construction\s+year|year\s+of\s+construction|ano\s+de\s+construção|ano\s+construcao)\s*[:\-\s]\s*(\d{4})',
            re.IGNORECASE
        )
        year_match = year_pattern.search(html)
        if year_match:
            construction_year = year_match.group(1)
        else:
            # Look for "construction" or "construção" text and find a year near it to avoid matching other years (like copyright dates, e.g. 2026)
            near_year_match = re.search(
                r'(?:ano\s+de\s+construção|ano\s+construção|year\s+built|built\s+in|year\s+of\s+construction).{1,50}?\b(19\d{2}|20\d{2})\b',
                html,
                re.IGNORECASE | re.DOTALL
            )
            if near_year_match:
                construction_year = near_year_match.group(1)
                
        # Look for Energy Rating
        energy_pattern = re.compile(
            r'(?:energy\s+certificate|energetic\s+certificate|energy\s+rating|certificado\s+energético|classe\s+energética|certificação\s+energética|energy\s+source|energy\s+efficiency)\s*[:\-\s]?[<\w\s=">/]*?\b(A\+?|B\-?|[C-G]|Electric|Gas|Solar|Exempt|Isento)\b',
            re.IGNORECASE
        )
        energy_match = energy_pattern.search(html)
        if energy_match:
            energy_rating = energy_match.group(1).title()
        else:
            # Fallback scan for isolated Energy class values if keyword not directly adjacent
            energy_rating_fallback = re.search(
                r'(?:energy\s+class|classe\s+energética|energy\s+rating|certificação\s+energética)\s*[:\-\s]?\s*([A-Ga-g]\+?)',
                html,
                re.IGNORECASE
            )
            if energy_rating_fallback:
                energy_rating = energy_rating_fallback.group(1).upper()
            
        return construction_year, energy_rating
    except Exception as e:
        logging.error(f"Error crawling missing details live for URL {url}: {e}")
        return None, None


def generate_pdf_report_file(properties, client_name):
    """Assign SARDO refs, compute stats and render the PDF report.
    Triggers live crawls for properties missing details to instantly populate the PDF and database.
    """
    properties = assign_sardo_references(properties)

    # Calculate stats for the selected properties.
    # Only count real, positive prices — properties with no published price
    # (-1 sentinel, 0, None) are P.O.A. and must be excluded from min/avg/median.
    prices = [p['property_price'] for p in properties
              if p.get('property_price') is not None and p.get('property_price') > 0]
    total_properties = len(properties)
    avg_price = sum(prices) / len(prices) if prices else 0
    median_price = sorted(prices)[len(prices)//2] if prices else 0
    min_price = min(prices) if prices else 0
    max_price = max(prices) if prices else 0

    return pdf_generator.generate_property_report(
        properties=properties,
        total_properties=total_properties,
        avg_price=avg_price,
        median_price=median_price,
        min_price=min_price,
        max_price=max_price,
        client_name=client_name
    )


def generate_excel_report(properties, client_name):
    """Assign SARDO refs and build the Excel workbook in memory.

    Returns a tuple of (BytesIO, filename). Shared by the Excel export and the
    email routes.
    """
    properties = assign_sardo_references(properties)

    selected_property_data = []
    for prop in properties:
        original_source = prop.get('website_source', 'N/A')
        source = display_source_name(original_source)

        is_waratah = original_source == 'WaratahpropertiesScraper'
        title = prop.get('title')
        reference = prop.get('reference', 'N/A')
        display_reference = title if is_waratah and title and title.strip() else reference

        from datetime import datetime, date
        
        first_seen_val = prop.get('first_seen_at')
        first_seen_display = '—'
        days_on_market = '—'
        
        if first_seen_val:
            try:
                if isinstance(first_seen_val, str):
                    try:
                        # Handle typical ISO strings
                        fs_date = datetime.fromisoformat(first_seen_val.replace('Z', '+00:00')).date()
                    except ValueError:
                        # Fallback to RFC 1123 format which database.py emits
                        fs_date = datetime.strptime(first_seen_val, '%a, %d %b %Y %H:%M:%S GMT').date()
                else:
                    fs_date = first_seen_val.date() if hasattr(first_seen_val, 'date') else first_seen_val
                    
                first_seen_display = fs_date.strftime('%d %b %Y')
                days_on_market = (date.today() - fs_date).days
            except Exception as e:
                logging.error(f"Excel DOM Parse Error: {e}")

        row = {
            'Price': format_price_value(prop.get('property_price')),
            'Location': prop.get('location', 'N/A'),
            'Type': prop.get('property_type', 'N/A'),
            'Beds': prop.get('num_beds'),
            'Baths': prop.get('num_baths'),
            'Build (m²)': format_area_value(prop.get('living_area')),
            'Plot (m²)': format_area_value(prop.get('land_area')),
            'Source': source,
            'Status': prop.get('property_status') if (prop.get('property_status') and prop.get('property_status') != 'Unknown') else 'For Sale',
            'First Seen Date': first_seen_display,
            'Days on Market': days_on_market,
            'Tags': ", ".join(prop.get('tags') or []),
            'SARDO Ref': prop.get('sardo_reference', 'N/A'),
            'Reference (with link to page source)': display_reference,
            'property_url': prop.get('property_url', '')
        }
        selected_property_data.append(row)

    df = pd.DataFrame(selected_property_data)
    columns_order = [
        'Price', 'Location', 'Type', 'Beds', 'Baths',
        'Build (m²)', 'Plot (m²)', 'Source', 'Status', 
        'First Seen Date', 'Days on Market', 'Tags', 'SARDO Ref',
        'Reference (with link to page source)'
    ]
    df_export = df[columns_order]
    
    date_str = datetime.now().strftime("%Y%m%d")
    default_filename = f"Property_Selection_{client_name}_{date_str}.xlsx"
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_export.to_excel(writer, index=False, sheet_name='Selected Properties')
        workbook = writer.book
        worksheet = writer.sheets['Selected Properties']
        
        # Auto-adjust column widths
        for col in worksheet.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = (max_length + 2)
            worksheet.column_dimensions[column].width = min(adjusted_width, 50)
            
        # Add hyperlinks manually onto the Reference column.
        # Derive the column index from columns_order (1-based) so that inserting
        # a new column never silently hyperlinks the wrong cells.
        ref_col_idx = columns_order.index('Reference (with link to page source)') + 1
        for i, url in enumerate(df['property_url']):
            if url and isinstance(url, str) and url.startswith('http'):
                cell = worksheet.cell(row=i + 2, column=ref_col_idx)
                cell.hyperlink = url
                cell.style = "Hyperlink"

    output.seek(0)
    return output, default_filename


EXCEL_MIMETYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
