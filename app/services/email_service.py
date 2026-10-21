"""Transactional email: OTP codes, password resets, security alerts."""

from app.config import Config
from app.extensions import email_sender
from datetime import datetime, timedelta
from flask import current_app, request





def _get_sardo_email_base(title, badge_text, inner_html, footer_note=None):
    """Base HTML wrapper matching SARDO360 executive luxury branding."""
    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet" />
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f1f5f9; padding: 44px 14px;">
        <tr>
            <td align="center">
                <!-- Main Card Container -->
                <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #ffffff; border-radius: 20px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 20px 45px -10px rgba(7, 26, 51, 0.16);">
                    
                    <!-- Prestige Midnight Luxury Banner -->
                    <tr>
                        <td align="center" style="background: linear-gradient(135deg, #071A33 0%, #0B2545 60%, #163A63 100%); padding: 40px 30px 32px 30px; text-align: center;">
                            <div style="font-family: 'Playfair Display', Didot, 'Bodoni MT', Georgia, serif; font-size: 38px; font-weight: 700; letter-spacing: 10px; color: #ffffff; text-transform: uppercase; line-height: 1.1; margin: 0 0 6px 0;">
                                SARDO
                            </div>
                            <div style="font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 10px; font-weight: 700; letter-spacing: 4px; color: #D3A24A; text-transform: uppercase; margin: 0 0 16px 0;">
                                PROPERTY BUYING AGENCY
                            </div>
                            <div style="width: 50px; height: 2px; background: linear-gradient(90deg, rgba(211,162,74,0.15) 0%, #D3A24A 50%, rgba(211,162,74,0.15) 100%); margin: 0 auto 12px auto;"></div>
                            <div style="font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 10.5px; font-weight: 600; letter-spacing: 2.2px; color: #8299B2; text-transform: uppercase;">
                                SARDO360 &bull; PROPERTY INSIGHT
                            </div>
                        </td>
                    </tr>

                    <!-- Main Content Body -->
                    <tr>
                        <td style="padding: 38px 40px;">
                            {f'<div style="display: inline-block; background-color: #FAF5EB; border: 1px solid #E6D2AA; color: #8A6519; font-size: 10.5px; font-weight: 800; padding: 5px 14px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 20px;">✦ &nbsp; {badge_text}</div>' if badge_text else ''}
                            {inner_html}
                        </td>
                    </tr>

                    <!-- Prestige Footer -->
                    <tr>
                        <td style="background-color: #071A33; padding: 30px 36px; text-align: center; color: #8299B2; font-size: 12px; line-height: 1.6; border-top: 2px solid #D3A24A;">
                            <div style="font-family: 'Playfair Display', Georgia, serif; font-size: 15px; font-weight: 700; color: #ffffff; letter-spacing: 3px; text-transform: uppercase; margin-bottom: 3px;">
                                SARDO360
                            </div>
                            <div style="font-size: 10.5px; font-weight: 600; color: #D3A24A; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 8px;">
                                Quinta do Lago &bull; Vale do Lobo &bull; Algarve Luxury Real Estate
                            </div>
                            <div style="font-size: 11px; color: #64748B; max-width: 480px; margin: 0 auto;">
                                {footer_note or 'If you did not expect this message, please contact sardorealestate@gmail.com.'}<br />
                                &copy; 2026 SARDO360 &bull; All rights reserved.
                            </div>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


def _build_temporary_password_html(username, user_email, temp_password, login_url):
    """HTML template for user creation with temporary credentials."""
    inner_html = f"""
        <h1 style="margin: 0 0 14px 0; font-size: 24px; font-weight: 800; color: #071A33; line-height: 1.3; letter-spacing: -0.3px;">
            Welcome to SARDO360
        </h1>
        <p style="margin: 0 0 24px 0; font-size: 14.5px; line-height: 1.65; color: #475569;">
            Hello <strong style="color: #071A33;">{username or 'there'}</strong>,<br />
            Your executive access account has been activated on the <strong>SARDO360 Property Insight</strong> platform. You can now monitor live Algarve property stock, track exclusive listings, and analyze real-time market movements.
        </p>

        <!-- Executive Credentials Pass -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #FAFAFC; border: 1px solid #E2E8F0; border-left: 4px solid #D3A24A; border-radius: 12px; margin: 0 0 26px 0; box-shadow: 0 3px 10px rgba(11, 37, 69, 0.03);">
            <tr>
                <td style="padding: 22px 24px;">
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-bottom: 1px solid #E8ECEF; padding-bottom: 12px; margin-bottom: 16px;">
                        <tr>
                            <td align="left">
                                <span style="font-size: 11px; font-weight: 800; color: #071A33; text-transform: uppercase; letter-spacing: 1px;">
                                    Sign-In Credentials
                                </span>
                            </td>
                            <td align="right">
                                <span style="font-size: 11px; font-weight: 700; color: #047857; background: #ECFDF5; border: 1px solid #A7F3D0; padding: 3px 10px; border-radius: 12px; letter-spacing: 0.3px;">
                                    ● Account Active
                                </span>
                            </td>
                        </tr>
                    </table>

                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                        <tr>
                            <td style="padding-bottom: 14px; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; width: 145px; vertical-align: middle;">
                                Account Email
                            </td>
                            <td style="padding-bottom: 14px; font-size: 14.5px; color: #071A33; font-weight: 700;">
                                {user_email}
                            </td>
                        </tr>
                        <tr>
                            <td style="font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; vertical-align: middle;">
                                Temporary Password
                            </td>
                            <td>
                                <div style="display: inline-block; background-color: #FFFFFF; border: 1.5px solid #CBD5E1; border-radius: 8px; padding: 10px 18px; box-shadow: inset 0 1px 3px rgba(0,0,0,0.03);">
                                    <span style="font-family: 'SFMono-Regular', Consolas, 'Courier New', monospace; font-size: 17px; font-weight: 800; color: #071A33; letter-spacing: 2.5px;">
                                        {temp_password}
                                    </span>
                                </div>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>

        <!-- Primary Action Button -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 0 0 12px 0;">
            <tr>
                <td align="center">
                    <a href="{login_url}" target="_blank" style="display: inline-block; background: linear-gradient(135deg, #071A33 0%, #0B2545 100%); color: #ffffff !important; text-decoration: none; font-size: 14.5px; font-weight: 700; padding: 15px 42px; border-radius: 30px; letter-spacing: 0.8px; text-transform: uppercase; box-shadow: 0 8px 22px rgba(7, 26, 51, 0.28); text-align: center; border: 1px solid #163A63;">
                        Sign In to SARDO360 &nbsp;&rarr;
                    </a>
                </td>
            </tr>
        </table>
        <p style="text-align: center; font-size: 12px; color: #94A3B8; margin: 0 0 28px 0;">
            Direct portal link: <a href="{login_url}" style="color: #4F7196; text-decoration: underline; font-weight: 500;">{login_url}</a>
        </p>

        <!-- 3-Step Simple Onboarding Guide (Visual & User-Friendly) -->
        <div style="margin-bottom: 24px;">
            <div style="font-size: 11.5px; font-weight: 800; color: #071A33; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px;">
                Quick Start in 3 Easy Steps
            </div>
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: separate; border-spacing: 0 8px;">
                <tr>
                    <td style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 12px 16px;">
                        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td width="30" valign="middle">
                                    <div style="width: 24px; height: 24px; border-radius: 50%; background: #071A33; color: #ffffff; font-size: 11.5px; font-weight: 800; text-align: center; line-height: 24px;">
                                        1
                                    </div>
                                </td>
                                <td style="padding-left: 10px; vertical-align: middle;">
                                    <strong style="font-size: 13.5px; color: #071A33;">Sign In:</strong>
                                    <span style="font-size: 13px; color: #475569;"> Click the button above and enter your temporary credentials.</span>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
                <tr>
                    <td style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 12px 16px;">
                        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td width="30" valign="middle">
                                    <div style="width: 24px; height: 24px; border-radius: 50%; background: #D3A24A; color: #ffffff; font-size: 11.5px; font-weight: 800; text-align: center; line-height: 24px;">
                                        2
                                    </div>
                                </td>
                                <td style="padding-left: 10px; vertical-align: middle;">
                                    <strong style="font-size: 13.5px; color: #071A33;">Set Your Password:</strong>
                                    <span style="font-size: 13px; color: #475569;"> The portal will automatically prompt you to create your permanent password.</span>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
                <tr>
                    <td style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 12px 16px;">
                        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td width="30" valign="middle">
                                    <div style="width: 24px; height: 24px; border-radius: 50%; background: #059669; color: #ffffff; font-size: 11.5px; font-weight: 800; text-align: center; line-height: 24px;">
                                        3
                                    </div>
                                </td>
                                <td style="padding-left: 10px; vertical-align: middle;">
                                    <strong style="font-size: 13.5px; color: #071A33;">Access Dashboard:</strong>
                                    <span style="font-size: 13px; color: #475569;"> Explore live listings, market KPIs, duplicate tracking, and reports.</span>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </div>

        <!-- Two-Factor Authentication Security Notice -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #F0FDF4; border: 1px solid #BBF7D0; border-left: 4px solid #10B981; border-radius: 8px;">
            <tr>
                <td style="padding: 14px 18px;">
                    <div style="font-weight: 700; color: #065F46; font-size: 13px; margin-bottom: 2px;">
                        Two-Factor Authentication (2FA) Protected
                    </div>
                    <div style="font-size: 12px; color: #047857; line-height: 1.45;">
                        Your account is safeguarded with email OTP verification. A one-time code will be sent to your registered inbox whenever you log in.
                    </div>
                </td>
            </tr>
        </table>
    """
    return _get_sardo_email_base(
        title="Your New Account & Temporary Password - SARDO360",
        badge_text="Executive Invitation",
        inner_html=inner_html
    )


def _build_otp_html(code, minutes):
    """HTML template for 2FA verification code."""
    inner_html = f"""
        <h1 style="margin: 0 0 12px 0; font-size: 22px; font-weight: 700; color: #0f172a; line-height: 1.3;">
            Two-Factor Verification Code
        </h1>
        <p style="margin: 0 0 20px 0; font-size: 14.5px; line-height: 1.6; color: #475569;">
            Enter the following one-time verification code to complete your SARDO360 sign-in:
        </p>

        <!-- Big OTP Display -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 24px 0;">
            <tr>
                <td align="center">
                    <div style="display: inline-block; background-color: #eef2ff; border: 2px solid #6366f1; border-radius: 12px; padding: 14px 28px; font-family: 'Courier New', Courier, monospace; font-size: 32px; font-weight: 800; color: #4338ca; letter-spacing: 6px;">
                        {code}
                    </div>
                </td>
            </tr>
        </table>

        <p style="text-align: center; font-size: 13px; color: #64748b; margin: 0 0 16px 0;">
            This code expires in <strong>{minutes} minute(s)</strong>.
        </p>
        <p style="font-size: 12px; color: #94a3b8; line-height: 1.5; margin: 0;">
            If you did not attempt to log in to your account, someone may be trying to access it. You can safely ignore this email, or contact your administrator if you suspect unauthorized activity.
        </p>
    """
    return _get_sardo_email_base(
        title="Your SARDO360 Login Code",
        badge_text="Security Verification",
        inner_html=inner_html
    )


def _build_password_reset_html(reset_link):
    """HTML template for password reset."""
    inner_html = f"""
        <h1 style="margin: 0 0 12px 0; font-size: 22px; font-weight: 700; color: #0f172a; line-height: 1.3;">
            Password Reset Request
        </h1>
        <p style="margin: 0 0 20px 0; font-size: 14.5px; line-height: 1.6; color: #475569;">
            We received a request to reset your password for SARDO360. If you did not make this request, you can safely ignore this email.
        </p>
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 28px 0;">
            <tr>
                <td align="center">
                    <a href="{reset_link}" target="_blank" style="display: inline-block; background-color: #6366f1; background-image: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%); color: #ffffff !important; text-decoration: none; font-size: 14.5px; font-weight: 700; padding: 13px 34px; border-radius: 25px; box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35); text-align: center;">
                        Reset Password &rarr;
                    </a>
                </td>
            </tr>
        </table>
        <p style="text-align: center; font-size: 12px; color: #94a3b8; margin: 0 0 20px 0;">
            Or copy and paste this link: <a href="{reset_link}" style="color: #6366f1; text-decoration: underline;">{reset_link}</a>
        </p>
        <p style="font-size: 12px; color: #94a3b8; margin: 0;">
            This link will expire in 15 minutes.
        </p>
    """
    return _get_sardo_email_base(
        title="Password Reset Request - SARDO360",
        badge_text="Password Reset",
        inner_html=inner_html
    )

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
    html_body = _build_password_reset_html(reset_link)
    try:
        email_sender.send(user_email, subject, body, html_body=html_body)
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
    html_body = _build_otp_html(code, minutes)
    email_sender.send(to=_otp_recipients(user_email), subject=subject, body=body, html_body=html_body)


def _send_temporary_password_email(user_email, username, temp_password, login_url=None):
    """Send an onboarding email containing the user's email, temporary password, and portal link."""
    if not user_email:
        return False

    if not login_url:
        try:
            from flask import has_request_context, request
            if has_request_context():
                login_url = f"{request.host_url.rstrip('/')}/login"
            else:
                login_url = "http://localhost:5000/login"
        except Exception:
            login_url = "http://localhost:5000/login"

    subject = f"Your New Account & Temporary Password - {Config.APP_TITLE}"
    body = f"""Hello {username or 'there'},

Your account has been created on {Config.APP_TITLE}.

Below are your initial sign-in credentials:
==================================================
Email:              {user_email}
Temporary Password: {temp_password}
Sign-In Portal:     {login_url}
==================================================

IMPORTANT FIRST LOGIN STEP:
When you sign in using this temporary password, you will be prompted to create your own permanent password (minimum 8 characters). Once created, you will use your new password for all future logins.

If you have any questions or did not expect this invitation, please contact your system administrator.

Best regards,
The {Config.APP_TITLE} Team
"""
    html_body = _build_temporary_password_html(username, user_email, temp_password, login_url)
    try:
        email_sender.send(to=[user_email], subject=subject, body=body, html_body=html_body)
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send temporary password email to {user_email}: {e}")
        return False
