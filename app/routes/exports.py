"""PDF and Excel export endpoints."""

from flask import Blueprint
import os
from app.services.export_service import EXCEL_MIMETYPE
from app.services.export_service import generate_excel_report
from app.services.export_service import generate_pdf_report_file
from flask import request, jsonify, send_file
from flask_login import login_required

bp = Blueprint('exports', __name__)




@bp.route('/api/export/pdf', methods=['POST'])
@login_required
def export_pdf():
    data = request.json
    client_name = data.get('client_name', 'Client').strip() or 'Client'
    properties = data.get('properties', [])

    if not properties:
        return jsonify({'error': 'No properties selected'}), 400

    try:
        output_path = generate_pdf_report_file(properties, client_name)
        return send_file(output_path, as_attachment=True, download_name=os.path.basename(output_path))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/export/excel', methods=['POST'])
@login_required
def export_excel():
    data = request.json
    client_name = data.get('client_name', 'Client').strip() or 'Client'
    properties = data.get('properties', [])

    if not properties:
        return jsonify({'error': 'No properties selected'}), 400

    output, default_filename = generate_excel_report(properties, client_name)
    return send_file(output, as_attachment=True, download_name=default_filename, mimetype=EXCEL_MIMETYPE)
