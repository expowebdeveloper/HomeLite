"""Transactional email: OTP codes, password resets, security alerts."""

from app.config import Config
from app.extensions import email_sender
from datetime import datetime, timedelta
from flask import current_app, request





def _get_sardo_logo_base64():
    """Returns base64 data URI of the official white SARDO logo."""
    try:
        import base64
        import os
        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'static', 'assets', 'sardo_logo_white.png'
        )
        if not os.path.exists(logo_path):
            logo_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                'logo.png'
            )
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('utf-8')
                return f"data:image/png;base64,{encoded}"
    except Exception:
        pass
    return "cid:sardo-logo"


def _get_sardo_email_base(title, badge_text, inner_html, footer_note=None, logo_src=None):
    """Base HTML wrapper matching SARDO360 executive luxury branding with client PNG logo."""
    effective_logo_src = logo_src or "cid:sardo-logo"
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
                    
                    <!-- Prestige Midnight Luxury Banner with Client Logo -->
                    <tr>
                        <td align="center" style="background: linear-gradient(135deg, #071A33 0%, #0B2545 60%, #163A63 100%); padding: 38px 30px 28px 30px; text-align: center;">
                            <table role="presentation" border="0" cellpadding="0" cellspacing="0" align="center" style="margin: 0 auto 16px auto;">
                                <tr>
                                    <td align="center">
                                        <img src="{effective_logo_src}" alt="SARDO - Property Buying Agency" width="220" style="display: block; width: 220px; max-width: 85%; height: auto; border: 0; outline: none; text-decoration: none;" />
                                    </td>
                                </tr>
                            </table>
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
        <h1 style="margin: 0 0 12px 0; font-size: 24px; font-weight: 800; color: #071A33; line-height: 1.3; letter-spacing: -0.3px;">
            Two-Factor Verification Code
        </h1>
        <p style="margin: 0 0 22px 0; font-size: 14.5px; line-height: 1.65; color: #475569;">
            Enter the following one-time verification code to complete your secure sign-in to the <strong>SARDO360 Property Insight</strong> portal:
        </p>

        <!-- Big OTP Display in Executive Gold & Navy Card -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 24px 0;">
            <tr>
                <td align="center">
                    <div style="display: inline-block; background: linear-gradient(135deg, #FAF5EB 0%, #F5E8D0 100%); border: 2px solid #D3A24A; border-radius: 14px; padding: 16px 36px; box-shadow: 0 6px 18px rgba(211, 162, 74, 0.18);">
                        <span style="font-family: 'SFMono-Regular', Consolas, 'Courier New', monospace; font-size: 34px; font-weight: 800; color: #071A33; letter-spacing: 8px;">
                            {code}
                        </span>
                    </div>
                </td>
            </tr>
        </table>

        <p style="text-align: center; font-size: 13.5px; color: #64748B; margin: 0 0 20px 0;">
            This one-time passcode expires in <strong style="color: #071A33;">{minutes} minute(s)</strong>.
        </p>
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px 16px; margin: 0;">
            <tr>
                <td>
                    <p style="font-size: 12px; color: #64748B; line-height: 1.55; margin: 0;">
                        <strong style="color: #071A33;">Security Note:</strong> Never share this code with anyone. SARDO administrators will never ask for your verification code. If you did not initiate this login, please contact your administrator immediately.
                    </p>
                </td>
            </tr>
        </table>
    """
    return _get_sardo_email_base(
        title="Your SARDO360 Login Code",
        badge_text="Security Verification",
        inner_html=inner_html,
        footer_note="If you did not request this login code, please contact sardorealestate@gmail.com."
    )


def _build_password_reset_html(reset_link):
    """HTML template for password reset."""
    inner_html = f"""
        <h1 style="margin: 0 0 14px 0; font-size: 24px; font-weight: 800; color: #071A33; line-height: 1.3; letter-spacing: -0.3px;">
            Password Reset Request
        </h1>
        <p style="margin: 0 0 22px 0; font-size: 14.5px; line-height: 1.65; color: #475569;">
            We received an official request to reset the password for your <strong>SARDO360</strong> portal account. If you submitted this request, click the button below to choose your new password:
        </p>

        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 28px 0;">
            <tr>
                <td align="center">
                    <a href="{reset_link}" target="_blank" style="display: inline-block; background-color: #071A33; background: linear-gradient(135deg, #071A33 0%, #0B2545 60%, #163A63 100%); color: #ffffff !important; text-decoration: none; font-size: 14.5px; font-weight: 700; padding: 14px 38px; border-radius: 30px; letter-spacing: 0.5px; box-shadow: 0 6px 18px rgba(7, 26, 51, 0.25); text-align: center;">
                        Reset Your Password &rarr;
                    </a>
                </td>
            </tr>
        </table>

        <p style="text-align: center; font-size: 12.5px; color: #64748B; margin: 0 0 20px 0;">
            Or copy and paste this link into your browser:<br />
            <a href="{reset_link}" style="color: #071A33; font-weight: 600; text-decoration: underline; word-break: break-all;">{reset_link}</a>
        </p>

        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #FFFBEB; border: 1px solid #FDE68A; border-radius: 8px; padding: 12px 16px; margin: 0;">
            <tr>
                <td>
                    <p style="font-size: 12px; color: #92400E; line-height: 1.5; margin: 0;">
                        <strong>Note:</strong> This secure link will automatically expire in <strong>15 minutes</strong>. If you did not request a password reset, you can safely ignore this email.
                    </p>
                </td>
            </tr>
        </table>
    """
    return _get_sardo_email_base(
        title="Password Reset Request - SARDO360",
        badge_text="Password Reset",
        inner_html=inner_html,
        footer_note="If you did not request a password reset, please contact sardorealestate@gmail.com."
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


def _build_security_alert_html(reason_str, ip, country, browser, os_info, timestamp_str, login_url=None):
    """HTML template matching SARDO360 executive branding for login security alerts."""
    if not login_url:
        try:
            from flask import has_request_context, request
            if has_request_context():
                login_url = f"{request.host_url.rstrip('/')}/login"
            else:
                login_url = "https://360portal.sardorealestate.com/login"
        except Exception:
            login_url = "https://360portal.sardorealestate.com/login"

    inner_html = f"""
        <h1 style="margin: 0 0 14px 0; font-size: 24px; font-weight: 800; color: #071A33; line-height: 1.3; letter-spacing: -0.3px;">
            Security Alert: New Sign-In Detected
        </h1>
        <p style="margin: 0 0 24px 0; font-size: 14.5px; line-height: 1.65; color: #475569;">
            We detected a successful sign-in to your <strong>SARDO360</strong> account from a <strong>{reason_str}</strong>. Please review the access details below to confirm this activity was authorized by you.
        </p>

        <!-- Access Details Card -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #FAFAFC; border: 1px solid #E2E8F0; border-left: 4px solid #D3A24A; border-radius: 12px; margin: 0 0 26px 0; box-shadow: 0 3px 10px rgba(11, 37, 69, 0.03);">
            <tr>
                <td style="padding: 22px 24px;">
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-bottom: 1px solid #E8ECEF; padding-bottom: 12px; margin-bottom: 16px;">
                        <tr>
                            <td align="left">
                                <span style="font-size: 11px; font-weight: 800; color: #071A33; text-transform: uppercase; letter-spacing: 1px;">
                                    Session Details
                                </span>
                            </td>
                            <td align="right">
                                <span style="font-size: 11px; font-weight: 700; color: #B45309; background: #FEF3C7; border: 1px solid #FDE68A; padding: 3px 10px; border-radius: 12px; letter-spacing: 0.3px;">
                                    ● Unrecognized Origin
                                </span>
                            </td>
                        </tr>
                    </table>

                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                        <tr>
                            <td style="padding-bottom: 12px; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; width: 140px; vertical-align: middle;">
                                IP Address
                            </td>
                            <td style="padding-bottom: 12px; font-size: 14px; color: #071A33; font-weight: 700;">
                                <code style="font-family: 'SFMono-Regular', Consolas, 'Courier New', monospace; background: #EDF2F7; padding: 3px 8px; border-radius: 6px; font-size: 13px;">{ip}</code>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding-bottom: 12px; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; vertical-align: middle;">
                                Location
                            </td>
                            <td style="padding-bottom: 12px; font-size: 14px; color: #071A33; font-weight: 600;">
                                {country or 'Unknown'}
                            </td>
                        </tr>
                        <tr>
                            <td style="padding-bottom: 12px; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; vertical-align: middle;">
                                Browser
                            </td>
                            <td style="padding-bottom: 12px; font-size: 14px; color: #071A33; font-weight: 600;">
                                {browser or 'Unknown'}
                            </td>
                        </tr>
                        <tr>
                            <td style="padding-bottom: 12px; font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; vertical-align: middle;">
                                Operating System
                            </td>
                            <td style="padding-bottom: 12px; font-size: 14px; color: #071A33; font-weight: 600;">
                                {os_info or 'Unknown'}
                            </td>
                        </tr>
                        <tr>
                            <td style="font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; vertical-align: middle;">
                                Timestamp
                            </td>
                            <td style="font-size: 13.5px; color: #475569; font-weight: 600;">
                                {timestamp_str}
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>

        <!-- Security Action Guidance -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 0 0 28px 0;">
            <tr>
                <td style="background-color: #FEF2F2; border: 1px solid #FECACA; border-left: 4px solid #EF4444; border-radius: 8px; padding: 14px 18px;">
                    <div style="font-weight: 700; color: #991B1B; font-size: 13.5px; margin-bottom: 4px;">
                        Did not recognize this sign-in?
                    </div>
                    <div style="font-size: 12.5px; color: #B91C1C; line-height: 1.5;">
                        If this wasn't you, someone may have compromised your credentials. Please sign in immediately to change your password and revoke any active sessions from your Account Settings.
                    </div>
                </td>
            </tr>
        </table>

        <!-- Portal Action Button -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 0 0 24px 0;">
            <tr>
                <td align="center">
                    <a href="{login_url}" target="_blank" style="display: inline-block; background-color: #071A33; background: linear-gradient(135deg, #071A33 0%, #0B2545 60%, #163A63 100%); color: #ffffff !important; text-decoration: none; font-size: 14.5px; font-weight: 700; padding: 14px 38px; border-radius: 30px; letter-spacing: 0.5px; box-shadow: 0 6px 18px rgba(7, 26, 51, 0.25); text-align: center;">
                        Review Account &bull; Sign In &rarr;
                    </a>
                </td>
            </tr>
        </table>

        <p style="font-size: 12.5px; color: #94A3B8; line-height: 1.5; margin: 0; text-align: center;">
            If this was you, no action is required and you can safely ignore this alert.
        </p>
    """
    return _get_sardo_email_base(
        title=f"Security Alert: New Sign-In from a {reason_str} - SARDO360",
        badge_text="Security Alert",
        inner_html=inner_html,
        footer_note="If you suspect unauthorized activity, contact sardorealestate@gmail.com immediately."
    )


def _send_security_alert_email(user_email, is_new_device, is_new_location, ip, country, browser, os_info):
    """Send a security alert email when a new device or location is detected."""
    if not user_email:
        return
        
    reasons = []
    if is_new_device:
        reasons.append("new device")
    if is_new_location:
        reasons.append("new location")
        
    reason_str = " and ".join(reasons) if reasons else "new device"
    time_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    
    subject = f"Security Alert: New Login from a {reason_str}"
    body = (
        f"We detected a successful login to your SARDO360 account from a {reason_str}.\n\n"
        f"Details:\n"
        f"- IP Address: {ip}\n"
        f"- Location: {country or 'Unknown'}\n"
        f"- Browser: {browser or 'Unknown'}\n"
        f"- Operating System: {os_info or 'Unknown'}\n"
        f"- Time: {time_str}\n\n"
        f"If this was you, you can safely ignore this email.\n"
        f"If you do not recognize this activity, please contact the administrator immediately and change your password."
    )
    html_body = _build_security_alert_html(reason_str, ip, country, browser, os_info, time_str)
    try:
        email_sender.send(to=[user_email], subject=subject, body=body, html_body=html_body)
    except Exception as e:
        current_app.logger.error(f"Failed to send security alert email to {user_email}: {e}")

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
