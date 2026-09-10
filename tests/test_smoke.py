"""Smoke tests for the restructured application.

Runs under pytest, or standalone with no test framework installed::

    python tests/test_smoke.py
    pytest tests/                     # if pytest is available

These assert the contract the restructure had to preserve: every route still
exists, the data layer still exposes every method, and the main endpoints still
answer with the same shape. They hit the real database, so they need a working
.env — the same requirement as running the app.
"""

import os
import re
import sys

from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from app.repositories import DatabaseManager

# Every URL rule the application exposed before the restructure.
EXPECTED_RULES = {
    '/', '/api/auth/forgot-password', '/api/auth/history', '/api/auth/login',
    '/api/auth/login-2fa', '/api/auth/logout', '/api/auth/mfa/disable', '/api/auth/mfa/enable',
    '/api/auth/mfa/status', '/api/auth/mfa/totp/disable', '/api/auth/mfa/totp/setup',
    '/api/auth/mfa/totp/verify-setup', '/api/auth/refresh', '/api/auth/register',
    '/api/auth/resend-otp', '/api/auth/reset-password', '/api/auth/sessions',
    '/api/auth/sessions/<int:session_id>', '/api/auth/sync-cookie', '/api/auth/verify-otp',
    '/api/auth/verify-totp', '/api/export/excel', '/api/export/pdf', '/api/market-intelligence',
    '/api/metadata', '/api/properties', '/api/properties/<property_id>',
    '/api/properties/<property_id>/documents', '/api/properties/<property_id>/group',
    '/api/properties/<property_id>/tags', '/api/properties/bulk-tags',
    '/api/properties/documents/<int:doc_id>', '/api/properties/manual',
    '/api/properties/manual/<property_id>', '/api/properties/recalculate-groups',
    '/api/properties/tags/sample-csv', '/api/properties/tags/upload-csv',
    '/api/reports/status', '/api/scrapers/activity', '/api/scrapers/logs/<int:run_id>',
    '/api/tags', '/api/tags/global', '/api/tags/global/<tag_name>', '/forgot-password',
    '/login', '/login-history', '/logout', '/reports', '/reset-password', '/scraper-logs',
    '/static/<path:filename>',
}

# The public surface of the data layer, which the mixin split had to preserve.
EXPECTED_DB_METHOD_COUNT = 81

_app = None


def get_app():
    global _app
    if _app is None:
        _app = create_app()
        _app.config['LOGIN_DISABLED'] = True
    return _app


def get_client():
    return get_app().test_client()


def test_app_factory_builds():
    assert get_app() is not None


def test_all_routes_registered():
    rules = {str(r) for r in get_app().url_map.iter_rules()}
    missing = EXPECTED_RULES - rules
    assert not missing, 'routes lost in the restructure: %s' % sorted(missing)


def test_every_endpoint_has_a_blueprint():
    """Blueprint prefixes are what url_for() in the templates now depends on."""
    loose = [r.endpoint for r in get_app().url_map.iter_rules()
             if '.' not in r.endpoint and r.endpoint != 'static']
    assert not loose, 'endpoints not registered under a blueprint: %s' % loose


def test_database_manager_surface_intact():
    methods = [m for m in dir(DatabaseManager) if not m.startswith('__')]
    assert len(methods) == EXPECTED_DB_METHOD_COUNT, \
        'expected %d members, found %d' % (EXPECTED_DB_METHOD_COUNT, len(methods))


def test_database_connects():
    from app.extensions import db_manager
    assert db_manager.connection is not None and not db_manager.connection.closed


def test_pages_render():
    client = get_client()
    for path in ('/', '/reports', '/scraper-logs', '/login'):
        resp = client.get(path)
        assert resp.status_code == 200, '%s returned %s' % (path, resp.status_code)
        assert b'<html' in resp.data.lower(), '%s did not render HTML' % path


def test_static_assets_served():
    client = get_client()
    for path in ('/static/js/main.js', '/static/js/pages/market_intelligence.js',
                 '/static/js/vendor/chart.umd.min.js'):
        resp = client.get(path)
        assert resp.status_code == 200, '%s returned %s' % (path, resp.status_code)
        assert len(resp.data) > 0


def test_every_stylesheet_the_page_links_is_served():
    """style.css was split into 18 files; a broken link would silently unstyle the app."""
    client = get_client()
    html = client.get('/').data.decode('utf-8', 'replace')
    hrefs = re.findall(r'href="(/static/css/[^"]+)"', html)
    assert len(hrefs) >= 18, 'expected the split stylesheets, found %d links' % len(hrefs)
    for href in hrefs:
        assert client.get(href).status_code == 200, 'stylesheet 404: %s' % href


def test_metadata_endpoint():
    body = get_client().get('/api/metadata').get_json()
    for key in ('locations', 'property_types', 'statuses', 'sources', 'tags', 'stats'):
        assert key in body, 'missing key in /api/metadata: %s' % key


def test_properties_search():
    resp = get_client().post('/api/properties',
                             json={'exclude_sold': True, 'limit': 5, 'page': 1})
    assert resp.status_code == 200
    body = resp.get_json()
    assert sorted(body.keys()) == ['limit', 'page', 'properties', 'total_count']
    assert isinstance(body['properties'], list)


def test_market_intelligence():
    resp = get_client().post('/api/market-intelligence', json={'exclude_sold': True})
    assert resp.status_code == 200
    body = resp.get_json()
    for key in ('kpis', 'stock_by_bedroom', 'listings_by_source', 'price_distribution',
                'duplicate_intelligence', 'bedroom_by_source', 'outliers'):
        assert key in body, 'missing key in /api/market-intelligence: %s' % key
    assert body['kpis'].get('active_properties') is not None


def test_market_intelligence_uses_friendly_source_names():
    """Charts must label agencies the way the rest of the app does."""
    body = get_client().post('/api/market-intelligence', json={'exclude_sold': True}).get_json()
    for row in body['listings_by_source']:
        assert row.get('display_source'), 'source row without a display name: %s' % row
        assert not row['display_source'].endswith('Scraper')


def _sample_properties(limit=2):
    body = get_client().post('/api/properties',
                             json={'exclude_sold': True, 'limit': limit, 'page': 1}).get_json()
    return body['properties']


def test_pdf_export():
    """send_file() resolves relative paths against app.root_path, which moved when
    the package was created — so the report path must be absolute."""
    resp = get_client().post('/api/export/pdf',
                             json={'client_name': 'SMOKETEST', 'properties': _sample_properties()})
    assert resp.status_code == 200, resp.data[:400]
    assert resp.headers['Content-Type'] == 'application/pdf'
    assert resp.data[:4] == b'%PDF', 'response is not a PDF'
    assert len(resp.data) > 10000

    generated = os.path.join(PROJECT_ROOT, 'sardo_property_report_%s_SMOKETEST.pdf'
                             % datetime.now().strftime('%Y%m%d'))
    assert os.path.exists(generated), 'report not written to the project root'

    # send_file still holds the handle on Windows until the response is closed,
    # so tidying up is best-effort.
    resp.close()
    try:
        os.remove(generated)
    except OSError:
        pass


def test_excel_export():
    resp = get_client().post('/api/export/excel',
                             json={'client_name': 'SMOKETEST', 'properties': _sample_properties()})
    assert resp.status_code == 200, resp.data[:400]
    assert resp.data[:2] == b'PK', 'response is not an xlsx archive'
    assert 'SMOKETEST' in resp.headers.get('Content-Disposition', '')


def test_property_detail_and_related_endpoints():
    client = get_client()
    prop_id = _sample_properties(1)[0]['id']
    for path in ('/api/properties/%s' % prop_id,
                 '/api/properties/%s/group' % prop_id,
                 '/api/properties/%s/documents' % prop_id,
                 '/api/tags', '/api/tags/global',
                 '/api/scrapers/activity', '/api/reports/status'):
        assert client.get(path).status_code == 200, '%s failed' % path


def test_security_headers_present():
    resp = get_client().get('/')
    for header in ('Strict-Transport-Security', 'X-Content-Type-Options',
                   'X-Frame-Options', 'Content-Security-Policy'):
        assert header in resp.headers, 'missing security header: %s' % header


def test_api_404_returns_json():
    resp = get_client().get('/api/definitely-not-a-route')
    assert resp.status_code == 404
    assert resp.get_json() == {'error': 'Not found'}


def main():
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith('test_') and callable(obj)]
    failures = []
    for name, fn in tests:
        try:
            fn()
            print('  PASS  %s' % name)
        except Exception as exc:                                   # noqa: BLE001
            failures.append((name, exc))
            print('  FAIL  %s -> %s: %s' % (name, type(exc).__name__, exc))
    print('\n%d passed, %d failed, %d total'
          % (len(tests) - len(failures), len(failures), len(tests)))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
