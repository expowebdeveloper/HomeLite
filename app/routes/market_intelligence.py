"""Aggregated analytics for the Market Intelligence dashboard."""

from flask import Blueprint, current_app
from app.extensions import db_manager
from app.utils.formatting import display_source_name
from datetime import datetime, timedelta
from flask import request, jsonify
from flask_login import login_required

bp = Blueprint('market_intelligence', __name__)



@bp.route('/api/market-intelligence', methods=['POST'])
@login_required
def market_intelligence():
    """Aggregated analytics powering the Market Intelligence dashboard.

    Takes the same filter payload as /api/properties so both views always
    describe the same slice of stock. Raw scraper source values are mapped to
    their friendly agent names here (e.g. 'QuintaProperty' -> 'QP Savills') so
    every chart, table and legend labels agencies the way the rest of the app
    does.
    """
    filters = request.json or {}
    # Pagination/sorting have no meaning for aggregates.
    for key in ('page', 'limit', 'sort_by', 'sort_dir'):
        filters.pop(key, None)

    kpis = db_manager.get_market_intelligence_kpis(filters)
    stock_by_bedroom = db_manager.get_stock_by_bedroom_count(filters)
    listings_by_source = db_manager.get_listings_by_source(filters)
    price_distribution = db_manager.get_price_distribution(filters)
    duplicate_intel = db_manager.get_duplicate_intelligence(filters)
    bedroom_by_source = db_manager.get_bedroom_stock_by_source(filters)
    outliers = db_manager.get_market_outliers(filters)

    for row in listings_by_source:
        row['display_source'] = display_source_name(row.get('source'))
    for row in bedroom_by_source:
        row['display_source'] = display_source_name(row.get('source'))
    if kpis.get('highest_priced_property'):
        kpis['highest_priced_property']['display_source'] = display_source_name(
            kpis['highest_priced_property'].get('source')
        )
    for item in duplicate_intel.get('top_widely_listed', []):
        item['agencies'] = [display_source_name(a) for a in (item.get('agencies') or [])]

    # Two agencies can share a friendly name (legacy scraper spellings map onto
    # the same agent), so fold them together before the frontend charts them.
    merged_sources = {}
    for row in listings_by_source:
        label = row['display_source']
        if label in merged_sources:
            existing = merged_sources[label]
            weight_old = existing['active_count'] or 0
            weight_new = row['active_count'] or 0
            total_weight = weight_old + weight_new
            for field in ('avg_price', 'avg_price_per_sqm', 'median_price'):
                a, b = existing.get(field), row.get(field)
                if a is not None and b is not None and total_weight:
                    existing[field] = (a * weight_old + b * weight_new) / total_weight
                elif b is not None:
                    existing[field] = b
            existing['active_count'] = total_weight
            existing['unique_count'] = (existing.get('unique_count') or 0) + (row.get('unique_count') or 0)
            existing['total_value'] = (existing.get('total_value') or 0) + (row.get('total_value') or 0)
        else:
            merged_sources[label] = row
    listings_by_source = sorted(
        merged_sources.values(), key=lambda r: r['active_count'] or 0, reverse=True
    )

    current_app.logger.info(
        f"[MI] active={kpis.get('active_properties')} unique={kpis.get('unique_properties')} "
        f"sources={len(listings_by_source)} bedrooms={len(stock_by_bedroom)} "
        f"prices={len(price_distribution)} matrix={len(bedroom_by_source)}"
    )

    return jsonify({
        'kpis': kpis,
        'stock_by_bedroom': stock_by_bedroom,
        'listings_by_source': listings_by_source,
        'price_distribution': price_distribution,
        'duplicate_intelligence': duplicate_intel,
        'bedroom_by_source': bedroom_by_source,
        'outliers': outliers,
        'generated_at': datetime.now().isoformat()
    })
