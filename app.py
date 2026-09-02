from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash, session, Response
import os
import io
import time
import json
import hmac
import hashlib
import secrets
import urllib.request
import pandas as pd
from datetime import datetime, timedelta
import tempfile
from functools import wraps
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
import bcrypt
import jwt
from user_agents import parse
import pyotp
import qrcode
import base64
import re
from cryptography.fernet import Fernet
import psycopg2
import psycopg2.extras
from config import Config
from database import DatabaseManager
from s3_manager import S3Manager
from pdf_generator import PDFGenerator
from email_sender import EmailSender

app = Flask(__name__)
app.config.from_object(Config)

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize singletons
app.config['JWT_SECRET_KEY'] = Config.JWT_SECRET_KEY
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(seconds=Config.JWT_ACCESS_EXPIRY)

# Strict session cookie configuration
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

db_manager = DatabaseManager()
s3_manager = S3Manager()
pdf_generator = PDFGenerator()
email_sender = EmailSender()

fernet = Fernet(Config.MFA_ENCRYPTION_KEY)

# Ensure auth-related tables exist (best-effort; method handles its own errors)
db_manager.ensure_login_activity_table()

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth_portal'

@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Unauthorized', 'authenticated': False}), 401
    return redirect(url_for('auth_portal', next=request.path))

@app.after_request
def add_security_headers(response):
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: "
        "https://fonts.googleapis.com https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https://*.s3.amazonaws.com;"
    )
    return response

class User(UserMixin):
    def __init__(self, id, username, email=None):
        self.id = id
        self.username = username
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    user_data = db_manager.get_user_by_id(int(user_id))
    if user_data:
        return User(id=user_data['id'], username=user_data['username'], email=user_data.get('email'))
    return None

@app.before_request
def check_flask_session():
    # Only protect non-API routes that use Flask-Login
    if request.path.startswith('/api/'):
        return
        
    if current_user.is_authenticated:
        token = session.get('refresh_token')
        if not token or not db_manager.validate_session_token(token):
            logout_user()
            session.clear()
            return redirect(url_for('auth_portal'))

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

def verify_and_upgrade_password(user_data, password):
    """Verifies a password against bcrypt or legacy pbkdf2:sha256 hash. 
       Automatically upgrades legacy hashes to bcrypt."""
    stored_hash = user_data['password_hash']
    if stored_hash.startswith('$2b$') or stored_hash.startswith('$2a$') or stored_hash.startswith('$2y$'):
        # Bcrypt hash
        try:
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
        except Exception:
            return False
    else:
        # Legacy werkzeug hash
        if check_password_hash(stored_hash, password):
            # Valid legacy password, let's upgrade it to bcrypt immediately
            new_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db_manager.update_user_password(user_data['id'], new_hash)
            return True
        return False

def _hash_otp(code):
    """Hash an OTP with the app secret so the raw code is never stored."""
    secret = app.config.get('SECRET_KEY', '') or 'default-dev-key'
    return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()


def _generate_otp():
    """Generate a zero-padded numeric OTP of the configured length."""
    length = Config.OTP_LENGTH
    return f"{secrets.randbelow(10 ** length):0{length}d}"


def _otp_recipients(user_email=None):
    """Effective OTP destination(s): user's email if set, else the test override or superadmin inbox."""
    if user_email:
        return [user_email]
    raw = (Config.OTP_TEST_RECIPIENT or '').strip() or (Config.OTP_RECIPIENT or '')
    return [addr.strip() for addr in raw.split(',') if addr.strip()]


def verify_and_upgrade_password(user_data, password):
    """Verify password and seamlessly upgrade to bcrypt if using legacy hash"""
    if not password or not user_data.get('password_hash'):
        return False
        
    pw_hash = user_data['password_hash']
    
    # Check if legacy pbkdf2 or scrypt hash (from Werkzeug)
    if pw_hash.startswith('pbkdf2:') or pw_hash.startswith('scrypt:'):
        if check_password_hash(pw_hash, password):
            new_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            db_manager.update_user_password(user_data['id'], new_hash)
            return True
        return False
        
    # Standard bcrypt verify
    try:
        return bcrypt.checkpw(password.encode('utf-8'), pw_hash.encode('utf-8'))
    except Exception:
        return False

def is_strong_password(password):
    return bool(re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$', password))

def _generate_backend_fingerprint(user_agent, accept_language, ip_subnet):
    """Generate a pseudo-fingerprint string from headers and subnet."""
    raw = f"{user_agent}|{accept_language}|{ip_subnet}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

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
    
    # Issue Tokens
    access_payload = {
        'sub': str(user_data['id']),
        'username': user_data['username'],
        'email': user_data.get('email'),
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
            app.logger.error(f"Failed to send security alert: {e}")
            
    res = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_in': Config.JWT_ACCESS_EXPIRY,
        'mfa_setup_required': not (user_data.get('mfa_enabled') or user_data.get('two_factor_enabled'))
    }
    if device_token:
        res['device_token'] = device_token
        
    return jsonify(res)

def _send_password_reset_email(user_email, reset_link):
    """Send a secure password reset link."""
    if not user_email:
        return
        
    subject = f"Password Reset Request - {Config.APP_TITLE}"
    body = f"""Hello,

We received a request to reset your password for {Config.APP_TITLE}.
If you did not make this request, please ignore this email.

To reset your password, click the link below:
{reset_link}

This link will expire in 15 minutes.

Thank you,
The {Config.APP_TITLE} Team
"""
    try:
        email_sender.send(user_email, subject, body)
    except Exception as e:
        app.logger.error(f"Failed to send password reset email: {e}")


def _send_security_alert_email(user_email, is_new_device, is_new_location, ip, country, browser, os_info):
    """Send a security alert email when a new device or location is detected."""
    if not user_email:
        return
        
    reasons = []
    if is_new_device:
        reasons.append("new device")
    if is_new_location:
        reasons.append("new location")
        
    reason_str = " and ".join(reasons)
    
    subject = f"Security Alert: New Login from a {reason_str}"
    body = (
        f"We detected a successful login to your SARDO360 account from a {reason_str}.\n\n"
        f"Details:\n"
        f"- IP Address: {ip}\n"
        f"- Location: {country or 'Unknown'}\n"
        f"- Browser: {browser or 'Unknown'}\n"
        f"- Operating System: {os_info or 'Unknown'}\n"
        f"- Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        f"If this was you, you can safely ignore this email.\n"
        f"If you do not recognize this activity, please contact the administrator immediately and change your password."
    )
    email_sender.send(to=[user_email], subject=subject, body=body)

def _send_otp_email(code, user_email=None):
    """Email the OTP code to the effective recipient(s)."""
    minutes = max(1, Config.OTP_EXPIRY_SECONDS // 60)
    subject = "Your SARDO360 login code"
    body = (
        f"Your SARDO360 verification code is: {code}\n\n"
        f"This code expires in {minutes} minute(s).\n"
        f"If you did not attempt to log in, you can ignore this email."
    )
    email_sender.send(to=_otp_recipients(user_email), subject=subject, body=body)


def _mask_email(email):
    """Partially mask an email for display, e.g. s******e@gmail.com."""
    if not email or '@' not in email:
        return email or ''
    name, domain = email.split('@', 1)
    if len(name) <= 2:
        masked = name[0] + '*'
    else:
        masked = name[0] + '*' * (len(name) - 2) + name[-1]
    return f"{masked}@{domain}"


@app.route('/forgot-password', methods=['GET'])
@app.route('/reset-password', methods=['GET'])
@app.route('/login', methods=['GET'])
def auth_portal():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('auth_portal.html')




@app.route('/login-history')
@login_required
def login_history():
    history = db_manager.get_login_history(limit=100, username=current_user.username)
    return render_template('login_history.html', history=history)


@app.route('/logout')
@login_required
def logout():
    db_manager.log_login_activity(
        'logout', username=current_user.username, user_id=current_user.id,
        ip_address=get_client_ip(), country=None,
        user_agent=request.headers.get('User-Agent', ''))
    logout_user()
    return redirect(url_for('auth_portal'))

# ---------------------------------------------------------------------------
# API Authentication Routes
# ---------------------------------------------------------------------------

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    # Registration via web is disabled. Use create_user.py from the command line.
    return jsonify({'error': 'Registration is not available. Contact your administrator.'}), 403

@app.route('/api/auth/sync-cookie', methods=['POST'])
def api_sync_cookie():
    """Hybrid flow: Validates JWT and sets Flask-Login session cookie."""
    data = request.json or {}
    access_token = data.get('access_token')
    refresh_token = data.get('refresh_token')
    if not access_token or not refresh_token:
        return jsonify({'error': 'Missing access or refresh token'}), 400
        
    try:
        payload = jwt.decode(access_token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
        user_id = int(payload['sub'])
    except Exception as e:
        app.logger.error(f"JWT Decode Error: {e}")
        return jsonify({'error': 'Invalid access token'}), 401
        
    user_data = db_manager.get_user_by_id(user_id)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
        
    user = User(id=user_data['id'], username=user_data['username'], email=user_data.get('email'))
    login_user(user)
    session['refresh_token'] = refresh_token
    return jsonify({'message': 'Cookie synced successfully'})


@app.route('/api/auth/forgot-password', methods=['POST'])
def api_forgot_password():
    data = request.json or {}
    email = data.get('email')
    
    if not email:
        return jsonify({'error': 'Email is required'}), 400
        
    user_data = db_manager.get_user_by_identifier(email)
    
    if user_data and user_data.get('email'):
        # Generate single-use reset token
        pw_hash_fragment = user_data['password_hash'][:10] if user_data.get('password_hash') else 'nohash'
        reset_payload = {
            'sub': str(user_data['id']),
            'type': 'password_reset',
            'pw_hash': pw_hash_fragment,
            'exp': datetime.utcnow() + timedelta(minutes=15),
            'iat': datetime.utcnow()
        }
        reset_token = jwt.encode(reset_payload, Config.JWT_SECRET_KEY, algorithm='HS256')
        reset_link = f"{Config.FRONTEND_URL}/reset-password?token={reset_token}"
        
        _send_password_reset_email(user_data['email'], reset_link)
        
    # Always return success to prevent user enumeration
    return jsonify({'message': 'If an account with that email exists, a password reset link has been sent.'})


@app.route('/api/auth/reset-password', methods=['POST'])
def api_reset_password():
    data = request.json or {}
    token = data.get('token')
    new_password = data.get('new_password')
    
    if not token or not new_password:
        return jsonify({'error': 'Token and new password are required'}), 400
        
    if not is_strong_password(new_password):
        return jsonify({'error': 'Password must be at least 8 characters long and contain uppercase, lowercase, numbers, and symbols.'}), 400
        
    try:
        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
        if payload.get('type') != 'password_reset':
            return jsonify({'error': 'Invalid token type'}), 401
            
        user_id = int(payload['sub'])
        pw_hash_fragment = payload.get('pw_hash')
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'Reset token has expired. Please request a new one.'}), 401
    except Exception:
        return jsonify({'error': 'Invalid reset token'}), 401
        
    user_data = db_manager.get_user_by_id(user_id)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
        
    current_hash_fragment = user_data['password_hash'][:10] if user_data.get('password_hash') else 'nohash'
    if pw_hash_fragment != current_hash_fragment:
        return jsonify({'error': 'This reset token has already been used.'}), 401
        
    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    if db_manager.update_user_password(user_id, hashed_password):
        db_manager.revoke_all_sessions(user_id)
        db_manager.reset_failed_login(user_id)
        
        ip = get_client_ip()
        country = get_country(ip)
        user_agent_str = request.headers.get('User-Agent', '')
        user_agent_parsed = parse(user_agent_str)
        browser = f"{user_agent_parsed.browser.family} {user_agent_parsed.browser.version_string}"
        os_info = f"{user_agent_parsed.os.family} {user_agent_parsed.os.version_string}"
        
        db_manager.log_login_activity(
            'api_password_reset', username=user_data['username'], user_id=user_id,
            ip_address=ip, country=country, user_agent=user_agent_str, browser=browser, os=os_info)
            
        return jsonify({'message': 'Password has been successfully reset. Please log in with your new password.'})
        
    return jsonify({'error': 'Failed to reset password. Please try again.'}), 500


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.json
    if not data:
        return jsonify({'error': 'Missing JSON payload'}), 400
        
    identifier = data.get('identifier')
    password = data.get('password')
    device_token = data.get('device_token')
    trust_device = data.get('trust_device', False)
    
    if not identifier or not password:
        return jsonify({'error': 'Missing credentials'}), 400
        
    ip = get_client_ip()
    country = get_country(ip)
    user_agent_str = request.headers.get('User-Agent', '')
    user_agent_parsed = parse(user_agent_str)
    browser = f"{user_agent_parsed.browser.family} {user_agent_parsed.browser.version_string}"
    os_info = f"{user_agent_parsed.os.family} {user_agent_parsed.os.version_string}"
    ip_subnet = '.'.join(ip.split('.')[:3]) if '.' in ip else ip
    accept_lang = request.headers.get('Accept-Language', '')
    fingerprint = _generate_backend_fingerprint(user_agent_str, accept_lang, ip_subnet)
    
    if '@' not in identifier:
        return jsonify({'error': 'Please login using your email address, not your username.'}), 400
    
    user_data = db_manager.get_user_by_identifier(identifier)
    if not user_data:
        db_manager.log_login_activity(
            'api_login_failed', username=identifier, user_id=None,
            ip_address=ip, country=country, user_agent=user_agent_str, browser=browser, os=os_info)
        return jsonify({'error': 'Invalid credentials'}), 401
        
    # Check Lockout
    if user_data.get('locked_until') and user_data['locked_until'] > datetime.utcnow():
        return jsonify({'error': 'Account is temporarily locked due to too many failed attempts. Try again later.'}), 429
        
    if verify_and_upgrade_password(user_data, password):
        db_manager.reset_failed_login(user_data['id'])
        
        # Check Trusted Device Token (bypasses OTP for known devices)
        mfa_bypassed = False
        if device_token:
            try:
                dt_payload = jwt.decode(device_token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
                if dt_payload.get('type') == 'trusted_device' and str(dt_payload.get('sub')) == str(user_data['id']):
                    if dt_payload.get('fingerprint') == fingerprint:
                        mfa_bypassed = True
            except Exception:
                pass
        
        # Always require OTP after password verification (unless trusted device)
        if not mfa_bypassed:
            code = _generate_otp()
            expires_at = time.time() + Config.OTP_EXPIRY_SECONDS
            db_manager.store_otp(user_data['id'], _hash_otp(code), expires_at)
            try:
                _send_otp_email(code, user_data.get('email'))
            except Exception as e:
                app.logger.error(f"Failed to send login OTP email: {e}")
            
            temp_payload = {
                'sub': str(user_data['id']),
                'type': 'email_otp_pending',
                'exp': datetime.utcnow() + timedelta(minutes=5),
                'iat': datetime.utcnow(),
                'trust_device': trust_device
            }
            temp_token = jwt.encode(temp_payload, Config.JWT_SECRET_KEY, algorithm='HS256')
            
            masked = _mask_email(user_data.get('email') or '')
            return jsonify({
                'message': 'OTP sent to your email',
                'require_otp': True,
                'temp_token': temp_token,
                'masked_email': masked,
                'cooldown': Config.OTP_RESEND_COOLDOWN_SECONDS
            })
            
        # Trusted device — complete login without OTP
        return _complete_login_flow(user_data, trust_device)
    else:
        attempts = db_manager.increment_failed_login(user_data['id'])
        db_manager.log_login_activity(
            'api_login_failed', username=identifier, user_id=user_data['id'],
            ip_address=ip, country=country, user_agent=user_agent_str, browser=browser, os=os_info)
        return jsonify({'error': f'Invalid credentials. {5 - attempts} attempts remaining.' if attempts < 5 else 'Account locked for 15 minutes.'}), 401


@app.route('/api/auth/login-2fa', methods=['POST'])
def api_login_2fa():
    """Passwordless login using TOTP (Authenticator App) for users who have it enabled."""
    data = request.json
    if not data:
        return jsonify({'error': 'Missing JSON payload'}), 400

    identifier = data.get('identifier')
    if not identifier:
        return jsonify({'error': 'Username or email is required'}), 400

    ip = get_client_ip()
    country = get_country(ip)
    user_agent_str = request.headers.get('User-Agent', '')
    user_agent_parsed = parse(user_agent_str)
    browser = f"{user_agent_parsed.browser.family} {user_agent_parsed.browser.version_string}"
    os_info = f"{user_agent_parsed.os.family} {user_agent_parsed.os.version_string}"
    ip_subnet = '.'.join(ip.split('.')[:3]) if '.' in ip else ip
    accept_lang = request.headers.get('Accept-Language', '')

    if '@' not in identifier:
        return jsonify({'error': 'Please login using your email address, not your username.'}), 400

    user_data = db_manager.get_user_by_identifier(identifier)
    if not user_data:
        # User doesn't exist
        return jsonify({'error': 'No account found with this email address.'}), 401

    if not user_data.get('mfa_enabled'):
        # User exists but hasn't enabled 2FA
        return jsonify({'error': 'Authenticator App login is not enabled for this account'}), 403

    # Issue temp token for TOTP verification
    temp_payload = {
        'sub': str(user_data['id']),
        'type': 'mfa_pending',
        'exp': datetime.utcnow() + timedelta(minutes=5),
        'iat': datetime.utcnow(),
        'trust_device': False
    }
    temp_token = jwt.encode(temp_payload, Config.JWT_SECRET_KEY, algorithm='HS256')

    return jsonify({
        'message': 'Enter your Authenticator App code to log in',
        'require_totp': True,
        'temp_token': temp_token
    })

@app.route('/api/auth/verify-otp', methods=['POST'])
def api_verify_otp():
    data = request.json
    temp_token = data.get('temp_token')
    otp = data.get('otp') or data.get('code')
    if not temp_token or not otp:
        return jsonify({'error': 'temp_token and otp are required'}), 400
        
    try:
        payload = jwt.decode(temp_token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
        if payload.get('type') not in ['email_otp_pending', 'mfa_pending']:
            return jsonify({'error': 'Invalid token type'}), 401
        user_id = int(payload['sub'])
    except Exception:
        return jsonify({'error': 'Invalid or expired temporary token'}), 401
        
    user_data = db_manager.get_user_by_id(user_id)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
        
    active_otp = db_manager.get_active_otp(user_id)
    if not active_otp:
        return jsonify({'error': 'OTP has expired. Please login again.'}), 401
        
    ip = get_client_ip()
    country = get_country(ip)
    user_agent_str = request.headers.get('User-Agent', '')
    user_agent_parsed = parse(user_agent_str)
    browser = f"{user_agent_parsed.browser.family} {user_agent_parsed.browser.version_string}"
    os_info = f"{user_agent_parsed.os.family} {user_agent_parsed.os.version_string}"
    
    if active_otp['attempts'] >= Config.OTP_MAX_ATTEMPTS:
        db_manager.clear_otp(user_id)
        db_manager.log_login_activity(
            'api_otp_failed', username=user_data['username'], user_id=user_id,
            ip_address=ip, country=country, user_agent=user_agent_str, browser=browser, os=os_info)
        return jsonify({'error': 'Too many incorrect attempts. Please login again.'}), 401
        
    if not hmac.compare_digest(active_otp['otp_hash'], _hash_otp(otp)):
        db_manager.increment_otp_attempts(active_otp['id'])
        return jsonify({'error': 'Invalid verification code'}), 401
        
    # Success
    db_manager.clear_otp(user_id)
    return _complete_login_flow(user_data, payload.get('trust_device'))


@app.route('/api/auth/resend-otp', methods=['POST'])
def api_resend_otp():
    """Resend the email login OTP for a pending 2FA session.

    Requires the temp_token issued by /api/auth/login. Rate limited by a short
    cooldown so the endpoint cannot be used to spam the recipient inbox.
    """
    data = request.json or {}
    temp_token = data.get('temp_token')
    if not temp_token:
        return jsonify({'error': 'temp_token is required'}), 400

    try:
        payload = jwt.decode(temp_token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
        if payload.get('type') != 'email_otp_pending':
            return jsonify({'error': 'Invalid token type'}), 401
        user_id = int(payload['sub'])
    except Exception:
        return jsonify({'error': 'Your session has expired. Please login again.'}), 401

    user_data = db_manager.get_user_by_id(user_id)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404

    # Cooldown: block rapid re-requests. get_active_otp().created_at is the DB
    # time the current code was issued; compare against UTC now.
    active_otp = db_manager.get_active_otp(user_id)
    if active_otp and active_otp.get('created_at'):
        try:
            elapsed = (datetime.utcnow() - active_otp['created_at']).total_seconds()
            remaining = int(Config.OTP_RESEND_COOLDOWN_SECONDS - elapsed)
            if 0 < remaining <= Config.OTP_RESEND_COOLDOWN_SECONDS:
                return jsonify({
                    'error': f'Please wait {remaining}s before requesting a new code.',
                    'retry_after': remaining
                }), 429
        except Exception:
            pass  # never block a legitimate resend on a clock/parse issue

    # Issue and send a fresh OTP (store_otp clears the previous one and resets attempts)
    code = _generate_otp()
    expires_at = time.time() + Config.OTP_EXPIRY_SECONDS
    db_manager.store_otp(user_id, _hash_otp(code), expires_at)
    try:
        _send_otp_email(code, user_data.get('email'))
    except Exception as e:
        app.logger.error(f"Failed to resend login OTP email: {e}")
        return jsonify({'error': 'Could not send the code. Please try again.'}), 500

    ip = get_client_ip()
    db_manager.log_login_activity(
        'api_otp_sent', username=user_data['username'], user_id=user_id,
        ip_address=ip, country=get_country(ip),
        user_agent=request.headers.get('User-Agent', ''))

    # Refresh the pending window so it matches the new code's lifetime
    new_temp_token = jwt.encode({
        'sub': str(user_id),
        'type': 'email_otp_pending',
        'exp': datetime.utcnow() + timedelta(minutes=5),
        'iat': datetime.utcnow(),
        'trust_device': payload.get('trust_device')
    }, Config.JWT_SECRET_KEY, algorithm='HS256')

    return jsonify({
        'message': 'A new code has been sent to your email.',
        'temp_token': new_temp_token,
        'masked_email': _mask_email(user_data.get('email') or ''),
        'cooldown': Config.OTP_RESEND_COOLDOWN_SECONDS
    })


@app.route('/api/auth/refresh', methods=['POST'])
def api_refresh():
    data = request.json
    refresh_token = data.get('refresh_token')
    if not refresh_token:
        return jsonify({'error': 'Refresh token is required'}), 400
        
    # Verify the refresh token in the database
    if not db_manager.connection:
        db_manager.connect()
    
    cursor = db_manager.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT * FROM user_sessions WHERE session_token = %s", (refresh_token,))
    session_data = cursor.fetchone()
    cursor.close()
    
    if not session_data:
        return jsonify({'error': 'Invalid refresh token'}), 401
        
    if session_data['expires_at'] < datetime.utcnow():
        return jsonify({'error': 'Refresh token has expired'}), 401
        
    user_data = db_manager.get_user_by_id(session_data['user_id'])
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
        
    # Generate new JWT Access Token
    access_payload = {
        'sub': user_data['id'],
        'username': user_data['username'],
        'email': user_data.get('email'),
        'exp': datetime.utcnow() + timedelta(seconds=Config.JWT_ACCESS_EXPIRY),
        'iat': datetime.utcnow()
    }
    access_token = jwt.encode(access_payload, Config.JWT_SECRET_KEY, algorithm='HS256')
    
    # Rotate Refresh Token
    new_refresh_token = secrets.token_hex(64)
    cursor = db_manager.connection.cursor()
    cursor.execute("""
        UPDATE user_sessions 
        SET session_token = %s, last_active = CURRENT_TIMESTAMP 
        WHERE id = %s
    """, (new_refresh_token, session_data['id']))
    db_manager.connection.commit()
    cursor.close()
    
    return jsonify({
        'access_token': access_token,
        'refresh_token': new_refresh_token,
        'expires_in': Config.JWT_ACCESS_EXPIRY
    })

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

@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """Revoke a specific refresh token."""
    data = request.json or {}
    refresh_token = data.get('refresh_token')
    if not refresh_token:
        return jsonify({'error': 'refresh_token required'}), 400
    success = db_manager.revoke_session_by_token(refresh_token)
    return jsonify({'success': success})

@app.route('/api/auth/sessions', methods=['GET'])
@api_require_auth
def api_get_sessions():
    """Get all active sessions for the user."""
    sessions = db_manager.get_active_sessions(request.user_id)
    return jsonify({'sessions': sessions})

@app.route('/api/auth/sessions/<int:session_id>', methods=['DELETE'])
@api_require_auth
def api_revoke_session(session_id):
    """Revoke a specific session."""
    success = db_manager.revoke_session(request.user_id, session_id)
    if success:
        return jsonify({'message': 'Session revoked successfully'})
    return jsonify({'error': 'Failed to revoke session'}), 400

@app.route('/api/auth/sessions', methods=['DELETE'])
@api_require_auth
def api_revoke_all_sessions():
    """Revoke all sessions (Global Logout)."""
    success = db_manager.revoke_all_sessions(request.user_id)
    if success:
        return jsonify({'message': 'All sessions revoked successfully'})
    return jsonify({'error': 'Failed to revoke sessions'}), 500

@app.route('/api/auth/mfa/status', methods=['GET'])
@api_require_auth
def api_mfa_status():
    """Get the current MFA status for the user."""
    user_data = db_manager.get_user_by_id(request.user_id)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({
        'two_factor_enabled': bool(user_data.get('two_factor_enabled')),
        'totp_enabled': bool(user_data.get('mfa_enabled'))
    })

@app.route('/api/auth/mfa/enable', methods=['POST'])
@api_require_auth
def api_mfa_enable():
    """Enable Email OTP for the user."""
    success = db_manager.set_mfa_status(request.user_id, True)
    if success:
        return jsonify({'message': 'Two-factor authentication enabled successfully'})
    return jsonify({'error': 'Failed to update MFA status'}), 500

@app.route('/api/auth/mfa/disable', methods=['POST'])
@api_require_auth
def api_mfa_disable():
    """Disable Email OTP for the user."""
    success = db_manager.set_mfa_status(request.user_id, False)
    if success:
        return jsonify({'message': 'Two-factor authentication disabled successfully'})
    return jsonify({'error': 'Failed to update MFA status'}), 500

@app.route('/api/auth/mfa/totp/setup', methods=['GET'])
@api_require_auth
def api_totp_setup():
    """Start TOTP enrollment."""
    user_data = db_manager.get_user_by_id(request.user_id)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
        
    secret = pyotp.random_base32()
    encrypted_secret = fernet.encrypt(secret.encode('utf-8')).decode('utf-8')
    
    if not db_manager.set_totp_secret(request.user_id, encrypted_secret):
        return jsonify({'error': 'Failed to save secret'}), 500
        
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user_data.get('email', user_data['username']), issuer_name=Config.APP_TITLE)
    
    img = qrcode.make(provisioning_uri)
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    return jsonify({
        'secret': secret,
        'qr_code': f"data:image/png;base64,{qr_base64}"
    })

@app.route('/api/auth/mfa/totp/verify-setup', methods=['POST'])
@api_require_auth
def api_totp_verify_setup():
    """Verify first code and enable TOTP."""
    data = request.json or {}
    code = data.get('code')
    if not code:
        return jsonify({'error': 'Code is required'}), 400
        
    user_data = db_manager.get_user_by_id(request.user_id)
    if not user_data or not user_data.get('google_auth_secret'):
        return jsonify({'error': 'Setup not initiated'}), 400
        
    try:
        secret = fernet.decrypt(user_data['google_auth_secret'].encode('utf-8')).decode('utf-8')
    except Exception:
        return jsonify({'error': 'Failed to decrypt secret'}), 500
        
    totp = pyotp.TOTP(secret)
    if not totp.verify(code):
        return jsonify({'error': 'Invalid code'}), 400
        
    # Generate 10 backup codes
    backup_codes = [secrets.token_hex(4) for _ in range(10)]
    encrypted_codes = [fernet.encrypt(bc.encode('utf-8')).decode('utf-8') for bc in backup_codes]
    
    if db_manager.enable_totp_mfa(request.user_id, encrypted_codes):
        return jsonify({
            'message': 'Authenticator enabled successfully',
            'backup_codes': backup_codes
        })
    return jsonify({'error': 'Failed to enable MFA'}), 500

@app.route('/api/auth/mfa/totp/disable', methods=['POST'])
@api_require_auth
def api_totp_disable():
    """Disable Authenticator."""
    if db_manager.disable_totp_mfa(request.user_id):
        return jsonify({'message': 'Authenticator disabled successfully'})
    return jsonify({'error': 'Failed to disable MFA'}), 500

@app.route('/api/auth/verify-totp', methods=['POST'])
def api_verify_totp():
    """Verify TOTP or backup code during login."""
    data = request.json or {}
    temp_token = data.get('temp_token')
    code = data.get('code')
    
    if not temp_token or not code:
        return jsonify({'error': 'temp_token and code are required'}), 400
        
    try:
        payload = jwt.decode(temp_token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
        if payload.get('type') not in ['totp_pending', 'mfa_pending']:
            return jsonify({'error': 'Invalid token type'}), 401
        user_id = int(payload['sub'])
    except Exception:
        return jsonify({'error': 'Invalid or expired temporary token'}), 401
        
    user_data = db_manager.get_user_by_id(user_id)
    if not user_data or not user_data.get('mfa_enabled') or not user_data.get('google_auth_secret'):
        return jsonify({'error': 'Authenticator not configured for this user'}), 400
        
    ip = get_client_ip()
    country = get_country(ip)
    user_agent_str = request.headers.get('User-Agent', '')
    user_agent_parsed = parse(user_agent_str)
    browser = f"{user_agent_parsed.browser.family} {user_agent_parsed.browser.version_string}"
    os_info = f"{user_agent_parsed.os.family} {user_agent_parsed.os.version_string}"
    
    is_valid = False
    
    # Check if code is a backup code (8 chars) or TOTP (6 chars)
    if len(code) > 6 and user_data.get('backup_codes'):
        encrypted_codes = user_data['backup_codes']
        remaining_codes = []
        
        for ec in encrypted_codes:
            try:
                decrypted = fernet.decrypt(ec.encode('utf-8')).decode('utf-8')
                if decrypted == code and not is_valid:
                    is_valid = True
                else:
                    remaining_codes.append(ec)
            except Exception:
                pass
                
        if is_valid:
            db_manager.update_backup_codes(user_id, remaining_codes)
    else:
        try:
            secret = fernet.decrypt(user_data['google_auth_secret'].encode('utf-8')).decode('utf-8')
            totp = pyotp.TOTP(secret)
            is_valid = totp.verify(code)
        except Exception:
            pass
            
    if not is_valid:
        db_manager.log_login_activity(
            'api_totp_failed', username=user_data['username'], user_id=user_id,
            ip_address=ip, country=country, user_agent=user_agent_str, browser=browser, os=os_info)
        return jsonify({'error': 'Invalid code'}), 401
        
    # Success
    return _complete_login_flow(user_data, payload.get('trust_device'))


@app.route('/api/auth/history', methods=['GET'])
@api_require_auth
def api_login_history():
    """Get login history for the current user."""
    user_data = db_manager.get_user_by_id(request.user_id)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    history = db_manager.get_login_history(limit=50, username=user_data['username'])
    return jsonify({'history': history})

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

@app.route('/api/properties/<property_id>', methods=['GET'])
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

@app.route('/api/properties/<property_id>/group', methods=['GET'])
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

@app.route('/api/properties/recalculate-groups', methods=['POST'])
@login_required
def recalculate_groups_endpoint():
    res = db_manager.recalculate_unique_property_groups()
    return jsonify(res)

@app.route('/api/tags', methods=['GET'])
@login_required
def get_tags_endpoint():
    tags = db_manager.get_all_tags()
    return jsonify({'tags': tags})

@app.route('/api/tags/global', methods=['GET'])
@login_required
def get_global_tags_endpoint():
    global_tags = db_manager.get_global_tags()
    return jsonify({'global_tags': global_tags})

@app.route('/api/tags/global', methods=['POST'])
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

@app.route('/api/tags/global/<tag_name>', methods=['DELETE'])
@login_required
def delete_global_tag_endpoint(tag_name):
    res = db_manager.delete_global_tag(tag_name)
    if not res.get('success'):
        return jsonify(res), 400
    return jsonify(res)

@app.route('/api/properties/bulk-tags', methods=['POST'])
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

@app.route('/api/properties/<property_id>/tags', methods=['PUT'])
@login_required
def update_property_tags_endpoint(property_id):
    data = request.json or {}
    tags = data.get('tags', [])
    res = db_manager.update_property_tags(property_id, tags)
    if not res.get('success'):
        return jsonify(res), 400
    return jsonify(res)

@app.route('/api/properties/tags/upload-csv', methods=['POST'])
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

@app.route('/api/properties/tags/sample-csv', methods=['GET', 'POST'])
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

@app.route('/api/properties/manual', methods=['POST'])
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

@app.route('/api/properties/manual/<property_id>', methods=['PUT'])
@login_required
def update_manual_property_endpoint(property_id):
    data = request.json or {}
    user_id = int(current_user.id) if hasattr(current_user, 'id') else 0
    res = db_manager.update_manual_property(property_id, data, user_id=user_id)
    if not res.get('success'):
        return jsonify(res), 400
    return jsonify(res)

@app.route('/api/properties/manual/<property_id>', methods=['DELETE'])
@login_required
def delete_manual_property_endpoint(property_id):
    res = db_manager.delete_manual_property(property_id)
    if not res.get('success'):
        return jsonify(res), 400
    return jsonify(res)

@app.route('/api/properties/<property_id>/documents', methods=['POST'])
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

@app.route('/api/properties/<property_id>/documents', methods=['GET'])
@login_required
def get_property_documents_endpoint(property_id):
    docs = db_manager.get_property_documents(property_id)
    for d in docs:
        if d.get('file_url'):
            d['display_url'] = s3_manager.get_image_url(d['file_url']) if not d['file_url'].startswith('http') else d['file_url']
    return jsonify({'documents': docs})

@app.route('/api/properties/documents/<int:doc_id>', methods=['DELETE'])
@login_required
def delete_property_document_endpoint(doc_id):
    res = db_manager.delete_property_document(doc_id)
    if not res.get('success'):
        return jsonify(res), 400
    doc = res.get('document', {})
    if doc.get('file_url') and not doc['file_url'].startswith('http'):
        s3_manager.delete_image(doc['file_url'])
    return jsonify(res)

@app.route('/reports')
@login_required
def reports():
    """Property status / market movement report page (spec section 6)."""
    return render_template('reports.html')


@app.route('/scraper-logs')
@login_required
def scraper_logs():
    """Live scraper activity + log console."""
    return render_template('scraper_logs.html')


@app.route('/api/scrapers/activity', methods=['GET'])
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


@app.route('/api/scrapers/logs/<int:run_id>', methods=['GET'])
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


@app.route('/api/reports/status', methods=['GET'])
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
        print(f"Error crawling missing details live for URL {url}: {e}")
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
                print(f"Excel DOM Parse Error: {e}")

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


@app.route('/api/export/pdf', methods=['POST'])
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


@app.route('/api/export/excel', methods=['POST'])
@login_required
def export_excel():
    data = request.json
    client_name = data.get('client_name', 'Client').strip() or 'Client'
    properties = data.get('properties', [])

    if not properties:
        return jsonify({'error': 'No properties selected'}), 400

    output, default_filename = generate_excel_report(properties, client_name)
    return send_file(output, as_attachment=True, download_name=default_filename, mimetype=EXCEL_MIMETYPE)


if __name__ == '__main__':
    app.run(debug=True, port=5002)
