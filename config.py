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
    
    # App Configuration
    APP_TITLE = "SARDO360 - PROPERTY INSIGHT"
    APP_WIDTH = 1500
    APP_HEIGHT = 900
    FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'default-dev-key')
    SECRET_KEY = os.getenv('SECRET_KEY', 'default-dev-key')
    
    # Property Types
    PROPERTY_TYPES = [
        "Villa",
        "Townhouse", 
        "Apartment",
        "House",
        "Penthouse",
        "Studio",
        "Duplex",
        "Triplex"
    ]
    
    # Website Sources
    WEBSITE_SOURCES = [
        "Domain",
        "RealEstate",
        "AllHomes"
    ]
    
    # Source Name Mapping (Full name to Display name)
    SOURCE_NAME_MAPPING = {
        "WaratahpropertiesScraper": "Waratah",
        "QuintapropertyScraper": "Quinta", 
        "LibertyrealestateScraper": "Liberty",
        "MaproRealEstateScraper": "Mapro",
        "VendiciPropertiesScraper": "Vendici",
        "QuintadolagoScraper": "Quinta Lago",
        "AlgarvePropScraper": "Algarve"
    }
