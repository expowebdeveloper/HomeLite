"""Password, OTP and device-fingerprint primitives."""

from flask import current_app

import bcrypt
import hashlib
import hmac
import re
import secrets
from app.config import Config
from app.extensions import db_manager
from werkzeug.security import check_password_hash




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

def _hash_otp(code):
    """Hash an OTP with the app secret so the raw code is never stored."""
    secret = current_app.config.get('SECRET_KEY', '') or 'default-dev-key'
    return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()


def _generate_otp():
    """Generate a zero-padded numeric OTP of the configured length."""
    length = Config.OTP_LENGTH
    return f"{secrets.randbelow(10 ** length):0{length}d}"

def is_strong_password(password):
    return bool(re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$', password))

def _generate_backend_fingerprint(user_agent, accept_language, ip_subnet):
    """Generate a pseudo-fingerprint string from headers and subnet."""
    raw = f"{user_agent}|{accept_language}|{ip_subnet}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


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
