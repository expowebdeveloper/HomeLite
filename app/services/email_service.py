"""Transactional email: OTP codes, password resets, security alerts."""

from app.config import Config
from app.extensions import email_sender
from datetime import datetime, timedelta
from flask import current_app, request




def _otp_recipients(user_email=None):
    """Effective OTP destination(s): user's email if set, else the test override or superadmin inbox."""
    if user_email:
        return [user_email]
    raw = (Config.OTP_TEST_RECIPIENT or '').strip() or (Config.OTP_RECIPIENT or '')
    return [addr.strip() for addr in raw.split(',') if addr.strip()]

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
        current_app.logger.error(f"Failed to send password reset email: {e}")


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
