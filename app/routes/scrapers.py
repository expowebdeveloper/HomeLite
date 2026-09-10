"""Scraper activity, log streaming and the status report."""

from app.repositories import DatabaseManager

from flask import Blueprint
from app.extensions import db_manager
from app.utils.formatting import display_source_name
from flask import request, jsonify
from flask_login import login_required

bp = Blueprint('scrapers', __name__)




@bp.route('/api/scrapers/activity', methods=['GET'])
@login_required
def scrapers_activity():
    """Current state of every scraper run, for live polling.

    Data is published by the scraper application into `scrape_runs` /
    `scrape_logs`; this endpoint only reads it.
    """
    data = db_manager.get_scraper_activity(limit=int(request.args.get('limit', 25)))

    for run in data.get('runs', []):
        run['display_source'] = display_source_name(run.get('source_name'))

    # Which scrapers have never reported a run at all?
    # Use only the source values that actually exist in `properties` — the legacy
    # aliases in SOURCE_NAME_MAPPING would otherwise show up as phantom duplicates
    # (e.g. both 'QuintaProperty' and 'QuintapropertyScraper' -> "Quinta").
    reported = {r['source_name'] for r in data.get('runs', [])}
    data['never_reported'] = [
        {'source': s, 'display_source': display_source_name(s)}
        for s in db_manager.get_sources() if s not in reported
    ]
    data['stale_after_seconds'] = DatabaseManager.STALE_HEARTBEAT_SECONDS
    return jsonify(data)


@bp.route('/api/scrapers/logs/<int:run_id>', methods=['GET'])
@login_required
def scraper_run_logs(run_id):
    """Log lines for one run.

    Behaves like a terminal:
      * no params            -> the MOST RECENT lines (tail), so you always see the end
                                of the scrape (including "Scraping completed")
      * ?after_id=<last seen> -> incremental poll: only lines newer than that
      * ?before_id=<first seen> -> "load earlier": the chunk above what you have
    """
    after_id = int(request.args.get('after_id', 0))
    before_id = request.args.get('before_id', type=int)
    level = request.args.get('level') or None
    limit = min(int(request.args.get('limit', 500)), 2000)

    result = db_manager.get_scrape_logs(
        run_id, after_id=after_id, before_id=before_id, level=level, limit=limit)
    result['run_id'] = run_id
    return jsonify(result)


@bp.route('/api/reports/status', methods=['GET'])
@login_required
def status_report():
    """Status + market-movement figures, optionally scoped to a date range.

    Movement figures (sold / delisted / new listings) come from
    property_status_history, which is populated by the scraper.
    """
    date_from = (request.args.get('date_from') or '').strip() or None
    date_to = (request.args.get('date_to') or '').strip() or None

    report = db_manager.get_status_report(date_from=date_from, date_to=date_to)
    if not report:
        return jsonify({'error': 'Could not build the status report'}), 500

    # Attach friendly agent names for display
    for row in report.get('by_source', []):
        row['display_source'] = display_source_name(row['source'])
    for change in report.get('recent_changes', []):
        change['display_source'] = display_source_name(change.get('source'))

    report['scrape_runs'] = db_manager.get_scrape_runs(limit=10)
    return jsonify(report)
