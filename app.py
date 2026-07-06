from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash
import os
import io
import pandas as pd
from datetime import datetime
import tempfile
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash

from config import Config
from database import DatabaseManager
from s3_manager import S3Manager
from pdf_generator import PDFGenerator

app = Flask(__name__)
app.config.from_object(Config)

# Initialize singletons
db_manager = DatabaseManager()
s3_manager = S3Manager()
pdf_generator = PDFGenerator()

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    # This is slightly inefficient as it queries the DB on every request, but fine for a small admin tool.
    # We should ideally fetch by ID, but we only have get_user_by_username right now.
    # Let's add get_user_by_id in database.py later, or just query it here.
    if not db_manager.connection:
        db_manager.connect()
    try:
        cursor = db_manager.connection.cursor()
        cursor.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        if user:
            return User(id=user[0], username=user[1])
    except:
        pass
    return None

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

def assign_sardo_references(properties):
    """Assign SARDO reference IDs to properties based on source and image filename"""
    sardo_ref_counter = 1100
    
    # Create a list of tuples (source, image_filename, property_index) for sorting
    property_info = []
    for i, prop in enumerate(properties):
        source = prop.get('website_source', '') or ''
        image_filename = prop.get('image_filename', '') or ''
        property_info.append((source, image_filename, i))
    
    # Sort by source name, then by image filename (alphabetical)
    property_info.sort(key=lambda x: (x[0] or '', x[1] or ''))
    
    # Assign SARDO reference IDs
    for _, _, prop_index in property_info:
        properties[prop_index]['sardo_reference'] = f"SARDO{sardo_ref_counter}"
        sardo_ref_counter += 1
    
    return properties

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_data = db_manager.get_user_by_username(username)
        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(id=user_data['id'], username=user_data['username'])
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/api/metadata', methods=['GET'])
@login_required
def metadata():
    locations = db_manager.get_locations()
    property_types = db_manager.get_property_types()
    stats = db_manager.get_statistics()
    return jsonify({
        'locations': locations,
        'property_types': property_types,
        'stats': stats,
        'app_title': Config.APP_TITLE
    })

@app.route('/api/properties', methods=['POST'])
@login_required
def search_properties():
    filters = request.json or {}
    
    # Extract pagination parameters
    page = filters.pop('page', 1)
    limit = filters.pop('limit', 10)
    
    # Handle "All" properties request
    if limit == 'all' or limit == 'All' or limit is None or limit == '':
        limit = None
        offset = None
    else:
        try:
            limit = int(limit)
            page = int(page)
            offset = (page - 1) * limit
        except ValueError:
            limit = 10
            page = 1
            offset = 0

    result = db_manager.get_properties(filters, limit=limit, offset=offset)
    properties = result.get('properties', [])
    total_count = result.get('total_count', 0)
    
    properties = assign_sardo_references(properties)

    # Resolve S3 urls and clean data
    for prop in properties:
        # Pre-generate presigned url for the image if it exists
        if prop.get('image_filename'):
            s3_key = prop['image_filename']
            source = prop.get('website_source')
            if source:
                s3_key = f"properties/{source}/{prop['image_filename']}"
            prop['image_url'] = s3_manager.get_image_url(s3_key)
        else:
            prop['image_url'] = None
            
        # Format the source mapping
        original_source = prop.get('website_source', 'N/A')
        source = original_source
        if source and source != 'N/A':
            if source in Config.SOURCE_NAME_MAPPING:
                source = Config.SOURCE_NAME_MAPPING[source]
            elif source.endswith('Scraper'):
                source = source[:-7]
        prop['display_source'] = source
        
        # Determine reference (Waratah properties use title)
        is_waratah = original_source == 'WaratahpropertiesScraper'
        title = prop.get('title')
        reference = prop.get('reference', 'N/A')
        prop['display_reference'] = title if is_waratah and title and title.strip() else reference

    return jsonify({
        'properties': properties,
        'total_count': total_count,
        'page': page,
        'limit': limit
    })

@app.route('/api/export/pdf', methods=['POST'])
@login_required
def export_pdf():
    data = request.json
    client_name = data.get('client_name', 'Client').strip() or 'Client'
    properties = data.get('properties', [])
    
    if not properties:
        return jsonify({'error': 'No properties selected'}), 400
        
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

    try:
        output_path = pdf_generator.generate_property_report(
            properties=properties,
            total_properties=total_properties,
            avg_price=avg_price,
            median_price=median_price,
            min_price=min_price,
            max_price=max_price,
            client_name=client_name
        )
        return send_file(output_path, as_attachment=True, download_name=os.path.basename(output_path))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/excel', methods=['POST'])
@login_required
def export_excel():
    data = request.json
    client_name = data.get('client_name', 'Client').strip() or 'Client'
    properties = data.get('properties', [])
    
    if not properties:
        return jsonify({'error': 'No properties selected'}), 400

    properties = assign_sardo_references(properties)
    
    selected_property_data = []
    for prop in properties:
        original_source = prop.get('website_source', 'N/A')
        source = original_source
        if source and source != 'N/A':
            if source in Config.SOURCE_NAME_MAPPING:
                source = Config.SOURCE_NAME_MAPPING[source]
            elif source.endswith('Scraper'):
                source = source[:-7]
        
        is_waratah = original_source == 'WaratahpropertiesScraper'
        title = prop.get('title')
        reference = prop.get('reference', 'N/A')
        display_reference = title if is_waratah and title and title.strip() else reference
        
        row = {
            'Price': format_price_value(prop.get('property_price')),
            'Location': prop.get('location', 'N/A'),
            'Type': prop.get('property_type', 'N/A'),
            'Beds': prop.get('num_beds'),
            'Baths': prop.get('num_baths'),
            'Build (m²)': format_area_value(prop.get('living_area')),
            'Plot (m²)': format_area_value(prop.get('land_area')),
            'Source': source,
            'SARDO Ref': prop.get('sardo_reference', 'N/A'),
            'Reference (with link to page source)': display_reference,
            'property_url': prop.get('property_url', '')
        }
        selected_property_data.append(row)

    df = pd.DataFrame(selected_property_data)
    columns_order = [
        'Price', 'Location', 'Type', 'Beds', 'Baths', 
        'Build (m²)', 'Plot (m²)', 'Source', 'SARDO Ref', 
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
            
        # Add hyperlinks manually
        url_col_idx = len(columns_order) + 1
        for i, url in enumerate(df['property_url']):
            if url and isinstance(url, str) and url.startswith('http'):
                cell = worksheet.cell(row=i+2, column=10) # Reference column is the 10th
                cell.hyperlink = url
                cell.style = "Hyperlink"

    output.seek(0)
    return send_file(output, as_attachment=True, download_name=default_filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

if __name__ == '__main__':
    app.run(debug=True, port=5002)
