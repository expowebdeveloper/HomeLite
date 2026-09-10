"""Property search, detail, tags, manual records and documents."""

from app.utils.formatting import assign_sardo_references

from flask import Blueprint
import io
import logging
import time
from app.config import Config
from app.extensions import db_manager
from app.extensions import s3_manager
from app.utils.formatting import display_source_name
from flask import request, jsonify, Response
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

bp = Blueprint('properties', __name__)



@bp.route('/api/metadata', methods=['GET'])
@login_required
def metadata():
    locations = db_manager.get_locations()
    property_types = db_manager.get_property_types()
    stats = db_manager.get_statistics()
    # Agent/source options carry the raw value (used for filtering) and the
    # friendly label (shown in the UI).
    sources = [{'value': s, 'label': display_source_name(s)} for s in db_manager.get_sources()]
    tags = db_manager.get_all_tags()
    return jsonify({
        'locations': locations,
        'property_types': property_types,
        'statuses': Config.PROPERTY_STATUSES,
        'sources': sources,
        'tags': tags,
        'stats': stats,
        'app_title': Config.APP_TITLE
    })

@bp.route('/api/properties', methods=['POST'])
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
            if prop.get('source_type') == 'manual' or source == 'Manual / Off-Market':
                if s3_key.startswith('http'):
                    prop['image_url'] = s3_key
                else:
                    prop['image_url'] = s3_manager.get_image_url(s3_key)
            elif source:
                s3_key = f"properties/{source}/{prop['image_filename']}"
                prop['image_url'] = s3_manager.get_image_url(s3_key)
            else:
                prop['image_url'] = s3_manager.get_image_url(s3_key)
        else:
            prop['image_url'] = None
            
        # Format the source mapping
        original_source = prop.get('website_source', 'N/A')
        prop['display_source'] = display_source_name(original_source)

        # Determine reference (Waratah properties use title)
        is_waratah = original_source == 'WaratahpropertiesScraper'
        title = prop.get('title')
        reference = prop.get('reference', 'N/A')
        prop['display_reference'] = title if is_waratah and title and title.strip() else reference

        # Coerce NULL/missing/Unknown property_status to 'For Sale'.
        # Per spec §4: "No status detected at all → For Sale".
        # This prevents the frontend from showing 'Unknown' for properties
        # where the scraper hasn't written a status yet or extracted non-status feature text.
        if not prop.get('property_status') or prop.get('property_status') == 'Unknown':
            prop['property_status'] = 'For Sale'

    return jsonify({
        'properties': properties,
        'total_count': total_count,
        'page': page,
        'limit': limit
    })


@bp.route('/api/properties/<property_id>', methods=['GET'])
@login_required
def get_property_detail(property_id):
    prop = db_manager.get_property_by_id(property_id)
    if not prop:
        return jsonify({'error': 'Property not found'}), 404
    if prop.get('image_filename'):
        s3_key = prop['image_filename']
        source = prop.get('website_source')
        if prop.get('source_type') == 'manual' or source == 'Manual / Off-Market':
            prop['image_url'] = s3_key if s3_key.startswith('http') else s3_manager.get_image_url(s3_key)
        elif source:
            prop['image_url'] = s3_manager.get_image_url(f"properties/{source}/{s3_key}")
        else:
            prop['image_url'] = s3_manager.get_image_url(s3_key)
    else:
        prop['image_url'] = None
    # Coerce NULL/Unknown property_status → 'For Sale' (same rule as the list endpoint)
    if not prop.get('property_status') or prop.get('property_status') == 'Unknown':
        prop['property_status'] = 'For Sale'
    return jsonify(prop)

@bp.route('/api/properties/<property_id>/group', methods=['GET'])
@login_required
def get_property_group_breakdown(property_id):
    info = db_manager.get_property_group_info(property_id)
    if not info or not info.get('listings'):
        return jsonify({'has_group': False, 'message': 'No duplicate group found for this property'}), 200

    for item in info.get('listings', []):
        item['display_source'] = display_source_name(item.get('source'))
        if not item.get('property_status') or item.get('property_status') == 'Unknown':
            item['property_status'] = 'For Sale'
        if item.get('image_filename'):
            source = item.get('source')
            if source:
                s3_key = f"properties/{source}/{item['image_filename']}"
            else:
                s3_key = item['image_filename']
            item['image_url'] = s3_manager.get_image_url(s3_key)
        else:
            item['image_url'] = None

    return jsonify({
        'has_group': True,
        'group': info
    })

@bp.route('/api/properties/recalculate-groups', methods=['POST'])
@login_required
def recalculate_groups_endpoint():
    res = db_manager.recalculate_unique_property_groups()
    return jsonify(res)

@bp.route('/api/tags', methods=['GET'])
@login_required
def get_tags_endpoint():
    tags = db_manager.get_all_tags()
    return jsonify({'tags': tags})

@bp.route('/api/tags/global', methods=['GET'])
@login_required
def get_global_tags_endpoint():
    global_tags = db_manager.get_global_tags()
    return jsonify({'global_tags': global_tags})

@bp.route('/api/tags/global', methods=['POST'])
@login_required
def create_global_tag_endpoint():
    data = request.json or {}
    name = data.get('name', '').strip()
    category = data.get('category', 'General').strip()
    color = data.get('color', '#4f46e5').strip()
    description = data.get('description', '').strip()
    res = db_manager.create_global_tag(name=name, category=category, color=color, description=description)
    if not res.get('success'):
        return jsonify(res), 400
    return jsonify(res), 201

@bp.route('/api/tags/global/<tag_name>', methods=['DELETE'])
@login_required
def delete_global_tag_endpoint(tag_name):
    res = db_manager.delete_global_tag(tag_name)
    if not res.get('success'):
        return jsonify(res), 400
    return jsonify(res)

@bp.route('/api/properties/bulk-tags', methods=['POST'])
@login_required
def bulk_assign_tags_endpoint():
    data = request.json or {}
    property_ids = data.get('property_ids', [])
    tag = data.get('tag', '').strip()
    action = data.get('action', 'add').strip().lower()
    if not property_ids:
        return jsonify({'success': False, 'error': 'No properties selected'}), 400
    if not tag:
        return jsonify({'success': False, 'error': 'Tag name cannot be empty'}), 400
    res = db_manager.bulk_assign_tag_to_properties(property_ids, tag, action=action)
    if not res.get('success'):
        return jsonify(res), 400
    return jsonify(res)

@bp.route('/api/properties/<property_id>/tags', methods=['PUT'])
@login_required
def update_property_tags_endpoint(property_id):
    data = request.json or {}
    tags = data.get('tags', [])
    res = db_manager.update_property_tags(property_id, tags)
    if not res.get('success'):
        return jsonify(res), 400
    return jsonify(res)

@bp.route('/api/properties/tags/upload-csv', methods=['POST'])
@login_required
def upload_tags_csv_endpoint():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'}), 400

    if not file.filename.lower().endswith(('.csv', '.txt')):
        return jsonify({'success': False, 'error': 'Invalid file format. Please upload a .csv file'}), 400

    mode = request.form.get('mode', 'replace').lower()
    if mode not in ('replace', 'append'):
        mode = 'replace'

    try:
        import csv
        import io
        content = file.read().decode('utf-8-sig', errors='replace')
        reader = csv.DictReader(io.StringIO(content))
        csv_rows = list(reader)
        
        if not csv_rows:
            return jsonify({'success': False, 'error': 'The uploaded CSV file is empty'}), 400

        res = db_manager.bulk_update_tags_from_csv(csv_rows, mode=mode)
        return jsonify(res)
    except Exception as e:
        logging.error(f"Error parsing tags CSV: {e}")
        return jsonify({'success': False, 'error': f'Failed to parse CSV: {str(e)}'}), 500

@bp.route('/api/properties/tags/sample-csv', methods=['GET', 'POST'])
@login_required
def download_sample_tags_csv_endpoint():
    filters = {}
    limit = 100
    if request.method == 'POST':
        filters = request.json or {}
        limit = None  # No limit when fetching filtered properties
        
    result = db_manager.get_properties(filters, limit=limit, offset=0)
    props = assign_sardo_references(result.get('properties', []))
    
    import io
    import csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['property_id', 'tags', 'property_title_hint'])
    
    for p in props:
        tags_str = ", ".join(p.get('tags') or [])
        ref = p.get('sardo_reference') or p.get('reference') or p.get('id')
        price_val = p.get('property_price')
        price_str = f"€{price_val:,}" if price_val and price_val > 0 else "P.O.A."
        title_hint = f"{p.get('property_type', '')} in {p.get('location', '')} ({price_str})"
        writer.writerow([ref, tags_str, title_hint])
        
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=sardo_property_tags_template.csv'}
    )

@bp.route('/api/properties/manual', methods=['POST'])
@login_required
def create_manual_property_endpoint():
    data = request.json or {}
    force = data.get('confirm_duplicate', False)
    user_id = int(current_user.id) if hasattr(current_user, 'id') else 0
    res = db_manager.create_manual_property(data, user_id=user_id, force=force)
    if not res.get('success'):
        if res.get('duplicate_warning'):
            return jsonify(res), 409
        return jsonify(res), 400
    return jsonify(res), 201

@bp.route('/api/properties/manual/<property_id>', methods=['PUT'])
@login_required
def update_manual_property_endpoint(property_id):
    data = request.json or {}
    user_id = int(current_user.id) if hasattr(current_user, 'id') else 0
    res = db_manager.update_manual_property(property_id, data, user_id=user_id)
    if not res.get('success'):
        return jsonify(res), 400
    return jsonify(res)

@bp.route('/api/properties/manual/<property_id>', methods=['DELETE'])
@login_required
def delete_manual_property_endpoint(property_id):
    res = db_manager.delete_manual_property(property_id)
    if not res.get('success'):
        return jsonify(res), 400
    return jsonify(res)

@bp.route('/api/properties/<property_id>/documents', methods=['POST'])
@login_required
def upload_property_document_endpoint(property_id):
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file part provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
        
    doc_type = request.form.get('document_type', 'Image')
    notes = request.form.get('notes', '')
    user_id = int(current_user.id) if hasattr(current_user, 'id') else 0
    
    filename = secure_filename(file.filename)
    timestamp = int(time.time())
    s3_key = f"properties/manual/{property_id}/{timestamp}_{filename}"
    
    upload_ok = s3_manager.upload_file_object(file, s3_key, content_type=file.content_type)
    if not upload_ok:
        return jsonify({'success': False, 'error': 'Failed to upload file to S3'}), 500
        
    res = db_manager.add_property_document(property_id, doc_type, filename, s3_key, user_id=user_id, notes=notes)
    if not res.get('success'):
        return jsonify(res), 400
        
    res['display_url'] = s3_manager.get_image_url(s3_key)
    return jsonify(res), 201

@bp.route('/api/properties/<property_id>/documents', methods=['GET'])
@login_required
def get_property_documents_endpoint(property_id):
    docs = db_manager.get_property_documents(property_id)
    for d in docs:
        if d.get('file_url'):
            d['display_url'] = s3_manager.get_image_url(d['file_url']) if not d['file_url'].startswith('http') else d['file_url']
    return jsonify({'documents': docs})

@bp.route('/api/properties/documents/<int:doc_id>', methods=['DELETE'])
@login_required
def delete_property_document_endpoint(doc_id):
    res = db_manager.delete_property_document(doc_id)
    if not res.get('success'):
        return jsonify(res), 400
    doc = res.get('document', {})
    if doc.get('file_url') and not doc['file_url'].startswith('http'):
        s3_manager.delete_image(doc['file_url'])
    return jsonify(res)
