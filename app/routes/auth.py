"""Authentication, MFA and session management endpoints."""

from flask import Blueprint, current_app
import base64
import bcrypt
import hmac
import io
import jwt
import os
import psycopg2
import psycopg2.extras
import pyotp
import qrcode
import secrets
import time
from app.config import Config
from app.extensions import db_manager
from app.extensions import fernet
from app.models.user import User
from app.services.auth_service import _complete_login_flow
from app.services.auth_service import api_require_auth
from app.services.email_service import _send_otp_email
from app.services.email_service import _send_password_reset_email
from app.utils.request_utils import get_client_ip
from app.utils.request_utils import get_country
from app.utils.security import _generate_backend_fingerprint
from app.utils.security import _generate_otp
from app.utils.security import _hash_otp
from app.utils.security import _mask_email
from app.utils.security import is_strong_password
from app.utils.security import verify_and_upgrade_password
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, redirect, url_for, session
from flask_login import current_user, login_required, login_user, logout_user
from user_agents import parse

bp = Blueprint('auth', __name__)




@bp.route('/forgot-password', methods=['GET'])
@bp.route('/reset-password', methods=['GET'])
@bp.route('/login', methods=['GET'])
def auth_portal():
    if current_user.is_authenticated:
        return redirect(url_for('pages.index'))
    return render_template('pages/auth_portal.html')




@bp.route('/login-history')
@login_required
def login_history():
    history = db_manager.get_login_history(limit=100, username=current_user.username)
    return render_template('pages/login_history.html', history=history)


@bp.route('/logout')
@login_required
def logout():
    db_manager.log_login_activity(
        'logout', username=current_user.username, user_id=current_user.id,
        ip_address=get_client_ip(), country=None,
        user_agent=request.headers.get('User-Agent', ''))
    logout_user()
    return redirect(url_for('auth.auth_portal'))

# ---------------------------------------------------------------------------
# API Authentication Routes
# ---------------------------------------------------------------------------

@bp.route('/api/auth/register', methods=['POST'])
def api_register():
    # Registration via web is disabled. Use create_user.py from the command line.
    return jsonify({'error': 'Registration is not available. Contact your administrator.'}), 403

@bp.route('/api/auth/sync-cookie', methods=['POST'])
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
        current_app.logger.error(f"JWT Decode Error: {e}")
        return jsonify({'error': 'Invalid access token'}), 401
        
    user_data = db_manager.get_user_by_id(user_id)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
        
    user = User(id=user_data['id'], username=user_data['username'], email=user_data.get('email'))
    login_user(user)
    session['refresh_token'] = refresh_token
    return jsonify({'message': 'Cookie synced successfully'})


@bp.route('/api/auth/forgot-password', methods=['POST'])
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


@bp.route('/api/auth/reset-password', methods=['POST'])
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


@bp.route('/api/auth/login', methods=['POST'])
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
                current_app.logger.error(f"Failed to send login OTP email: {e}")
            
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


@bp.route('/api/auth/login-2fa', methods=['POST'])
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

@bp.route('/api/auth/verify-otp', methods=['POST'])
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


@bp.route('/api/auth/resend-otp', methods=['POST'])
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
        current_app.logger.error(f"Failed to resend login OTP email: {e}")
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


@bp.route('/api/auth/refresh', methods=['POST'])
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

@bp.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """Revoke a specific refresh token."""
    data = request.json or {}
    refresh_token = data.get('refresh_token')
    if not refresh_token:
        return jsonify({'error': 'refresh_token required'}), 400
    success = db_manager.revoke_session_by_token(refresh_token)
    return jsonify({'success': success})

@bp.route('/api/auth/sessions', methods=['GET'])
@api_require_auth
def api_get_sessions():
    """Get all active sessions for the user."""
    sessions = db_manager.get_active_sessions(request.user_id)
    return jsonify({'sessions': sessions})

@bp.route('/api/auth/sessions/<int:session_id>', methods=['DELETE'])
@api_require_auth
def api_revoke_session(session_id):
    """Revoke a specific session."""
    success = db_manager.revoke_session(request.user_id, session_id)
    if success:
        return jsonify({'message': 'Session revoked successfully'})
    return jsonify({'error': 'Failed to revoke session'}), 400

@bp.route('/api/auth/sessions', methods=['DELETE'])
@api_require_auth
def api_revoke_all_sessions():
    """Revoke all sessions (Global Logout)."""
    success = db_manager.revoke_all_sessions(request.user_id)
    if success:
        return jsonify({'message': 'All sessions revoked successfully'})
    return jsonify({'error': 'Failed to revoke sessions'}), 500

@bp.route('/api/auth/mfa/status', methods=['GET'])
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

@bp.route('/api/auth/mfa/enable', methods=['POST'])
@api_require_auth
def api_mfa_enable():
    """Enable Email OTP for the user."""
    success = db_manager.set_mfa_status(request.user_id, True)
    if success:
        return jsonify({'message': 'Two-factor authentication enabled successfully'})
    return jsonify({'error': 'Failed to update MFA status'}), 500

@bp.route('/api/auth/mfa/disable', methods=['POST'])
@api_require_auth
def api_mfa_disable():
    """Disable Email OTP for the user."""
    success = db_manager.set_mfa_status(request.user_id, False)
    if success:
        return jsonify({'message': 'Two-factor authentication disabled successfully'})
    return jsonify({'error': 'Failed to update MFA status'}), 500

@bp.route('/api/auth/mfa/totp/setup', methods=['GET'])
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

@bp.route('/api/auth/mfa/totp/verify-setup', methods=['POST'])
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

@bp.route('/api/auth/mfa/totp/disable', methods=['POST'])
@api_require_auth
def api_totp_disable():
    """Disable Authenticator."""
    if db_manager.disable_totp_mfa(request.user_id):
        return jsonify({'message': 'Authenticator disabled successfully'})
    return jsonify({'error': 'Failed to disable MFA'}), 500

@bp.route('/api/auth/verify-totp', methods=['POST'])
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


@bp.route('/api/auth/history', methods=['GET'])
@api_require_auth
def api_login_history():
    """Get login history for the current user."""
    user_data = db_manager.get_user_by_id(request.user_id)
    if not user_data:
        return jsonify({'error': 'User not found'}), 404
    history = db_manager.get_login_history(limit=50, username=user_data['username'])
    return jsonify({'history': history})
