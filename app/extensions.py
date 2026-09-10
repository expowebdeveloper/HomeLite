"""Shared singletons.

Instantiated once at import so blueprints, services and scripts all talk to the
same database connection, S3 client and mail sender — exactly as the original
module-level globals in app.py did.
"""

from cryptography.fernet import Fernet
from flask_login import LoginManager

from app.config import Config
from app.repositories import DatabaseManager
from app.services.mailer import EmailSender
from app.services.pdf_service import PDFGenerator
from app.services.storage_service import S3Manager

db_manager = DatabaseManager()
s3_manager = S3Manager()
pdf_generator = PDFGenerator()
email_sender = EmailSender()

fernet = Fernet(Config.MFA_ENCRYPTION_KEY)

# Ensure auth-related tables exist (best-effort; the method handles its own errors)
db_manager.ensure_login_activity_table()

login_manager = LoginManager()
