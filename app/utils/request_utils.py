"""Details derived from the incoming request."""

import json
import urllib.request
from app.config import Config
from flask import request




# ---------------------------------------------------------------------------
# Authentication helpers (login tracking + email OTP two-factor auth)
# ---------------------------------------------------------------------------

def get_client_ip():
    """Best-effort client IP from the request, honoring common proxy headers."""
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        # First entry is the original client when behind proxies
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def get_country(ip):
    """Best-effort country lookup for an IP via a free public API.

    Returns 'Local' for private/loopback addresses and None on failure.
    """
    if not Config.GEO_LOOKUP_ENABLED:
        return None
    if not ip or ip in ('127.0.0.1', '::1', 'unknown') or \
            ip.startswith(('10.', '192.168.', '172.16.', '172.17.', '172.18.',
                           '172.19.', '172.2', '172.30.', '172.31.')):
        return 'Local'
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,country"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('status') == 'success':
                return data.get('country')
    except Exception:
        return None
    return None
