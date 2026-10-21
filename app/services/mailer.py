
import smtplib
import ssl
import logging
from email.message import EmailMessage

from app.config import Config


class EmailSender:
    """Sends emails (with optional attachments) over SMTP.

    Uses Python's standard library only. Configured via the SMTP_* variables
    in .env (see config.py). For Gmail, SMTP_PASSWORD must be a 16-character
    App Password, not the account password.
    """

    def __init__(self):
        self.host = Config.SMTP_HOST
        self.port = Config.SMTP_PORT
        self.username = Config.SMTP_USERNAME
        self.password = Config.SMTP_PASSWORD
        self.use_tls = Config.SMTP_USE_TLS
        self.mail_from = Config.MAIL_FROM or self.username
        self.mail_from_name = Config.MAIL_FROM_NAME

    def is_configured(self) -> bool:
        """True if the minimum SMTP settings are present."""
        return bool(self.host and self.username and self.password)

    def send(self, to, subject, body, attachments=None, html_body=None):
        """Send an email.

        Args:
            to: recipient email string (or list of strings)
            subject: subject line
            body: plain-text body
            attachments: optional list of dicts with keys
                'filename', 'content' (bytes) and 'mimetype' (e.g. 'application/pdf')
        """
        if not self.is_configured():
            raise RuntimeError(
                "SMTP is not configured. Set SMTP_HOST, SMTP_USERNAME and "
                "SMTP_PASSWORD in your .env file."
            )

        msg = EmailMessage()
        from_header = (
            f"{self.mail_from_name} <{self.mail_from}>"
            if self.mail_from_name else self.mail_from
        )
        msg['From'] = from_header
        msg['To'] = to if isinstance(to, str) else ', '.join(to)
        msg['Subject'] = subject
        msg.set_content(body)

        if not html_body and body:
            # Ensure every email sent throughout the application uses the SARDO360 executive template
            try:
                from app.services.email_service import _get_sardo_email_base
                paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]
                formatted_p = []
                for p in paragraphs:
                    lines = [l.strip() for l in p.split('\n') if l.strip()]
                    formatted_p.append('<p style="margin: 0 0 16px 0; font-size: 14.5px; line-height: 1.65; color: #475569;">' + '<br />'.join(lines) + '</p>')
                inner_html = f"""
                    <h1 style="margin: 0 0 16px 0; font-size: 22px; font-weight: 800; color: #071A33; line-height: 1.3;">
                        {subject}
                    </h1>
                    {''.join(formatted_p)}
                """
                html_body = _get_sardo_email_base(
                    title=subject,
                    badge_text="Notification",
                    inner_html=inner_html
                )
            except Exception as e:
                logging.warning(f"Could not wrap email body with SARDO luxury base template: {e}")

        if html_body:
            msg.add_alternative(html_body, subtype='html')

        for att in (attachments or []):
            mimetype = att.get('mimetype') or 'application/octet-stream'
            maintype, _, subtype = mimetype.partition('/')
            msg.add_attachment(
                att['content'],
                maintype=maintype,
                subtype=subtype or 'octet-stream',
                filename=att['filename'],
            )

        context = ssl.create_default_context()
        try:
            if int(self.port) == 465:
                # Implicit SSL
                with smtplib.SMTP_SSL(self.host, self.port, context=context, timeout=30) as server:
                    server.login(self.username, self.password)
                    server.send_message(msg)
            else:
                # STARTTLS (port 587)
                with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                    server.ehlo()
                    if self.use_tls:
                        server.starttls(context=context)
                        server.ehlo()
                    server.login(self.username, self.password)
                    server.send_message(msg)
        except Exception as e:
            logging.error(f"Failed to send email to {to}: {e}")
            raise

        logging.info(f"Email sent to {to}")
        return True
