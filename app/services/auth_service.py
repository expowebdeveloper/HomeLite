"""Login orchestration and the API bearer-token guard."""

import jwt
import os
import secrets
import time
from app.config import Config
from app.extensions import db_manager
from app.services.email_service import _send_security_alert_email
from app.utils.request_utils import get_client_ip
from app.utils.request_utils import get_country
from app.utils.security import _generate_backend_fingerprint
from datetime import datetime, timedelta
from flask import current_app, jsonify, redirect, request, session, url_for
from flask_login import current_user
from functools import wraps
from user_agents import parse


def _complete_login_flow(user_data, trust_device=False):
    """Helper to finalize login, issue tokens, perform anomaly checking and log activity."""
    ip = get_client_ip()
    country = get_country(ip)
    user_agent_str = request.headers.get('User-Agent', '')
    user_agent_parsed = parse(user_agent_str)
    browser = f"{user_agent_parsed.browser.family} {user_agent_parsed.browser.version_string}"
    os_info = f"{user_agent_parsed.os.family} {user_agent_parsed.os.version_string}"
    
    ip_subnet = '.'.join(ip.split('.')[:3]) if '.' in ip else ip
    accept_lang = request.headers.get('Accept-Language', '')
    fingerprint = _generate_backend_fingerprint(user_agent_str, accept_lang, ip_subnet)
    
    role = user_data.get('role', 'user')
    can_view_scrapers = user_data.get('can_view_scrapers', True)
    can_view_reports = user_data.get('can_view_reports', True)
    can_manage_users = user_data.get('can_manage_users', False)

    # Issue Tokens
    access_payload = {
        'sub': str(user_data['id']),
        'username': user_data['username'],
        'email': user_data.get('email'),
        'role': role,
        'can_view_scrapers': can_view_scrapers,
        'can_view_reports': can_view_reports,
        'can_manage_users': can_manage_users,
        'exp': datetime.utcnow() + timedelta(seconds=Config.JWT_ACCESS_EXPIRY),
        'iat': datetime.utcnow()
    }
    access_token = jwt.encode(access_payload, Config.JWT_SECRET_KEY, algorithm='HS256')
    refresh_token = secrets.token_hex(64)
    refresh_expiry = time.time() + Config.JWT_REFRESH_EXPIRY
    db_manager.create_user_session(user_data['id'], refresh_token, refresh_expiry, ip, user_agent_str)
    
    # Device Token Logic
    device_token = None
    if trust_device:
        db_manager.add_trusted_device(user_data['id'], fingerprint)
        dt_payload = {
            'sub': str(user_data['id']),
            'type': 'trusted_device',
            'fingerprint': fingerprint,
            'exp': datetime.utcnow() + timedelta(days=30),
            'iat': datetime.utcnow()
        }
        device_token = jwt.encode(dt_payload, Config.JWT_SECRET_KEY, algorithm='HS256')
        
    is_new_device = db_manager.is_new_device_for_user(user_data['id'], fingerprint, browser, os_info)
    is_new_location = db_manager.is_new_location_for_user(user_data['id'], country)
    
    db_manager.log_login_activity(
        'api_login_success', username=user_data['username'], user_id=user_data['id'],
        ip_address=ip, country=country, user_agent=user_agent_str, browser=browser, os=os_info, device_fingerprint=fingerprint)
    db_manager.update_last_login(user_data['id'], ip, browser)
    
    if is_new_device or is_new_location:
        try:
            _send_security_alert_email(user_data.get('email'), is_new_device, is_new_location, ip, country, browser, os_info)
            db_manager.log_login_activity(
                'security_alert_sent', username=user_data['username'], user_id=user_data['id'],
                ip_address=ip, country=country, user_agent=user_agent_str, 
                browser=browser, os=os_info, device_fingerprint=fingerprint)
        except Exception as e:
            current_app.logger.error(f"Failed to send security alert: {e}")
            
    res = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_in': Config.JWT_ACCESS_EXPIRY,
        'mfa_setup_required': not (user_data.get('mfa_enabled') or user_data.get('two_factor_enabled')),
        'user': {
            'id': user_data['id'],
            'username': user_data['username'],
            'email': user_data.get('email'),
            'role': role,
            'can_view_scrapers': can_view_scrapers,
            'can_view_reports': can_view_reports,
            'can_manage_users': can_manage_users,
            'must_change_password': bool(user_data.get('must_change_password', False))
        }
    }
    if device_token:
        res['device_token'] = device_token
        
    return jsonify(res)


def api_require_auth(f):
    """Decorator to protect API routes with JWT or Flask-Login session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. Check for Flask-Login session
        if current_user.is_authenticated:
            request.user_id = current_user.id
            return f(*args, **kwargs)
            
        # 2. Check for JWT
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
            request.user_id = payload['sub']
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator ensuring the user has administrator privileges."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_app.config.get('LOGIN_DISABLED'):
            return f(*args, **kwargs)
        if current_user.is_authenticated:
            if not getattr(current_user, 'is_admin', False):
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Forbidden: Administrator privileges required.'}), 403
                return redirect(url_for('pages.index'))
            return f(*args, **kwargs)

        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            try:
                payload = jwt.decode(auth_header.split(' ')[1], Config.JWT_SECRET_KEY, algorithms=['HS256'])
                request.user_id = payload['sub']
                if payload.get('role') not in ('super_admin', 'admin') and not payload.get('can_manage_users'):
                    return jsonify({'error': 'Forbidden: Administrator privileges required.'}), 403
                return f(*args, **kwargs)
            except Exception:
                return jsonify({'error': 'Unauthorized'}), 401

        if request.path.startswith('/api/'):
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('auth.auth_portal'))
    return decorated


def scraper_access_required(f):
    """Decorator ensuring the user has permission to access Scraper Logs."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_app.config.get('LOGIN_DISABLED'):
            return f(*args, **kwargs)
        if current_user.is_authenticated:
            if not getattr(current_user, 'can_access_scrapers', False):
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Forbidden: Access to Scraper Logs is restricted.'}), 403
                return redirect(url_for('pages.index'))
            return f(*args, **kwargs)

        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            try:
                payload = jwt.decode(auth_header.split(' ')[1], Config.JWT_SECRET_KEY, algorithms=['HS256'])
                request.user_id = payload['sub']
                if payload.get('role') not in ('super_admin', 'admin') and not payload.get('can_view_scrapers', True):
                    return jsonify({'error': 'Forbidden: Access to Scraper Logs is restricted.'}), 403
                return f(*args, **kwargs)
            except Exception:
                return jsonify({'error': 'Unauthorized'}), 401

        if request.path.startswith('/api/'):
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('auth.auth_portal'))
    return decorated


def report_access_required(f):
    """Decorator ensuring the user has permission to access Market Reports."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_app.config.get('LOGIN_DISABLED'):
            return f(*args, **kwargs)
        if current_user.is_authenticated:
            # Restricted Users are explicitly permitted access to the Market Intelligence area
            is_allowed = getattr(current_user, 'can_access_reports', False) or (getattr(current_user, 'role', '') == 'restricted_user' and '/market-intelligence' in request.path)
            if not is_allowed:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Forbidden: Access to Market Reports is restricted.'}), 403
                return redirect(url_for('pages.index'))
            return f(*args, **kwargs)

        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            try:
                payload = jwt.decode(auth_header.split(' ')[1], Config.JWT_SECRET_KEY, algorithms=['HS256'])
                request.user_id = payload['sub']
                if payload.get('role') not in ('super_admin', 'admin') and not payload.get('can_view_reports', True):
                    return jsonify({'error': 'Forbidden: Access to Market Reports is restricted.'}), 403
                return f(*args, **kwargs)
            except Exception:
                return jsonify({'error': 'Unauthorized'}), 401

        if request.path.startswith('/api/'):
            return jsonify({'error': 'Unauthorized'}), 401
        return redirect(url_for('auth.auth_portal'))
    return decorated
