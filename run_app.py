#!/usr/bin/env python3
"""
Property Insight Desktop Application Launcher

This script launches the Property Insight desktop application with proper
error handling and environment validation.
"""

import sys
import os
import logging
from pathlib import Path

def check_environment():
    """Check if required environment variables are set"""
    required_vars = [
        'AWS_ACCESS_KEY_ID',
        'AWS_SECRET_ACCESS_KEY', 
        'S3_BUCKET_NAME',
        'DB_HOST',
        'DB_NAME',
        'DB_USER',
        'DB_PASSWORD'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print("❌ Error: Missing required environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\nPlease create a .env file with your configuration.")
        print("See env_example.txt for the required format.")
        return False
    
    return True

def check_dependencies():
    """Check if required Python packages are installed"""
    required_packages = [
        'boto3',
        'psycopg2',
        'PIL',
        'reportlab',
        'pandas',
        'matplotlib'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ Error: Missing required Python packages:")
        for package in missing_packages:
            print(f"   - {package}")
        print("\nPlease install dependencies with:")
        print("   pip install -r requirements.txt")
        return False
    
    return True

def main():
    """Main launcher function"""
    print("🏠 Property Insight Desktop Application")
    print("=" * 50)
    
    # Check if .env file exists
    if not os.path.exists('.env'):
        print("❌ Error: .env file not found!")
        print("Please create a .env file with your configuration.")
        print("See env_example.txt for the required format.")
        sys.exit(1)
    
    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ Environment variables loaded")
    except ImportError:
        print("⚠️  Warning: python-dotenv not installed, using system environment")
    
    # Check environment variables
    if not check_environment():
        sys.exit(1)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    print("✅ All checks passed")
    print("\n🚀 Starting Property Insight application...")
    print("-" * 50)
    
    try:
        # Import and run the application
        from property_app import PropertyApp
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Create and run the application
        app = PropertyApp()
        app.run()
        
    except ImportError as e:
        print(f"❌ Error importing application: {e}")
        print("Please ensure all files are in the correct location.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error starting application: {e}")
        print("Please check the console output for more details.")
        sys.exit(1)

if __name__ == "__main__":
    main()
