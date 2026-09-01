import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # AWS Configuration
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
    S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
    
    # Database Configuration
    DB_HOST = os.getenv('DB_HOST')
    DB_PORT = os.getenv('DB_PORT', '5432')
    DB_NAME = os.getenv('DB_NAME')
    DB_USER = os.getenv('DB_USER')
    DB_PASSWORD = os.getenv('DB_PASSWORD')

    # SMTP / Email Configuration
    SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USERNAME = os.getenv('SMTP_USERNAME')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    SMTP_USE_TLS = os.getenv('SMTP_USE_TLS', 'True').lower() in ('1', 'true', 'yes')
    MAIL_FROM = os.getenv('MAIL_FROM') or os.getenv('SMTP_USERNAME')
    MAIL_FROM_NAME = os.getenv('MAIL_FROM_NAME', 'SARDO360')

    # Two-Factor Authentication (Email OTP)
    # OTP_RECIPIENT is the production/superadmin inbox used when deployed.
    OTP_RECIPIENT = os.getenv('OTP_RECIPIENT') or os.getenv('MAIL_FROM') or os.getenv('SMTP_USERNAME')
    # OTP_TEST_RECIPIENT overrides the destination during testing. While set, all
    # codes go here instead of OTP_RECIPIENT. Supports comma-separated addresses.
    # Leave blank/remove on deployment so codes go to OTP_RECIPIENT (superadmin).
    OTP_TEST_RECIPIENT = os.getenv('OTP_TEST_RECIPIENT', '')
    OTP_LENGTH = int(os.getenv('OTP_LENGTH', '6'))
    OTP_EXPIRY_SECONDS = int(os.getenv('OTP_EXPIRY_SECONDS', '300'))  # 5 minutes
    OTP_MAX_ATTEMPTS = int(os.getenv('OTP_MAX_ATTEMPTS', '5'))
    # Minimum wait between "resend code" requests, to protect the inbox from spam
    OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv('OTP_RESEND_COOLDOWN_SECONDS', '30'))
    # Best-effort country lookup from IP (uses a free public API). Set to False to skip.
    GEO_LOOKUP_ENABLED = os.getenv('GEO_LOOKUP_ENABLED', 'True').lower() in ('1', 'true', 'yes')

    # App Configuration
    APP_TITLE = "SARDO360 - PROPERTY INSIGHT"
    APP_WIDTH = 1500
    APP_HEIGHT = 900
    FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'default-dev-key')
    SECRET_KEY = os.getenv('SECRET_KEY', 'default-dev-key')
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:3000')
    
    # JWT Configuration
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', SECRET_KEY)
    JWT_ACCESS_EXPIRY = int(os.getenv('JWT_ACCESS_EXPIRY', '900')) # 15 minutes
    JWT_REFRESH_EXPIRY = int(os.getenv('JWT_REFRESH_EXPIRY', '604800')) # 7 days
    
    # MFA / TOTP Configuration (Fernet requires exactly 32 url-safe base64-encoded bytes)
    # E.g. cryptography.fernet.Fernet.generate_key().decode('utf-8')
    MFA_ENCRYPTION_KEY = os.getenv('MFA_ENCRYPTION_KEY', 'x_uJvYq82bW40P-ZfJ0o1W7aM8R3_59gXhT3iYf1cHg=')
    
    # Canonical SARDO360 property statuses.
    # Must stay in sync with the properties_property_status_chk DB constraint
    # (see migrations/004_property_status.py).
    PROPERTY_STATUSES = [
        "For Sale",
        "New Listing",
        "Reserved",
        "Under Offer",
        "Sold",
        "Exclusive",
        "Delisted",
        "Unknown",
        "Off Market",
        "Withdrawn",
    ]

    # Statuses that no longer represent live, sellable stock.
    INACTIVE_STATUSES = ["Sold", "Delisted", "Withdrawn"]

    # Property Types
    PROPERTY_TYPES = [
        "Villa",
        "Townhouse",
        "Apartment",
        "House",
        "Penthouse",
        "Studio",
        "Duplex",
        "Triplex",
        "Land",
    ]
    
    # Website Sources
    WEBSITE_SOURCES = [
        "Domain",
        "RealEstate",
        "AllHomes",
        "Manual / Off-Market",
    ]
    
    # Source Name Mapping (raw scraper `source` value -> Display name).
    # Keys must match the exact `source` strings written by the scrapers,
    # otherwise reports group under inconsistent agent labels.
    SOURCE_NAME_MAPPING = {
        # Currently present in the database
        "WaratahpropertiesScraper": "Waratah",
        "QuintaProperty": "QP Savills",
        "OlivehomesScraper": "Olive Homes",
        "MaproRealEstateScraper": "Mapro",
        "QuintadoLagoScraper": "Quinta Lago",
        "VendiciPropertiesScraper": "Vendici",
        "Manual / Off-Market": "Manual / Off-Market",

        # Legacy / historical spellings, kept so old rows still map correctly
        "QuintapropertyScraper": "QP Savills",
        "QuintadolagoScraper": "Quinta Lago",
        "LibertyrealestateScraper": "Liberty",
        "AlgarvePropScraper": "Gatehouse"
    }

    @staticmethod
    def normalize_property_status(raw_text: str = None, is_live_page: bool = True) -> str:
        """
        Properly canonicalize property status from live badge/raw text.
        
        Step 1: If the page was removed or dead (404/delisted), return 'Delisted'.
        Step 2: Check for explicit status badges (Sold, Reserved, Under Offer, Exclusive, New Listing, etc.).
        Step 3: If live and no special badge exists (or generic feature text), return 'For Sale'.
        """
        if not is_live_page:
            return "Delisted"

        if not raw_text:
            return "For Sale"

        txt = str(raw_text).strip().lower()

        # Check for inactive / sold badges first
        if any(k in txt for k in ["sold", "vendid", "vendido"]):
            return "Sold"
        if any(k in txt for k in ["withdrawn", "retirado"]):
            return "Withdrawn"
        if any(k in txt for k in ["off market", "private listing"]):
            return "Off Market"

        # Check for transaction / conditional badges
        if any(k in txt for k in ["under offer", "under contract", "sob proposta", "sale agreed", "under proposal", "promessa"]):
            return "Under Offer"
        if any(k in txt for k in ["reserved", "reservado", "reservation", "reserva"]):
            return "Reserved"
        if any(k in txt for k in ["exclusive", "exclusivo", "sole agency"]):
            return "Exclusive"
        if any(k in txt for k in ["new listing", "novo", "new development", "just listed", "newly built"]):
            return "New Listing"

        # Live property with standard features or unmapped badge -> For Sale
        return "For Sale"

