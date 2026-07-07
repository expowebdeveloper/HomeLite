#!/usr/bin/env python3
"""
Login Tracking Migration Script

This script adds device_fingerprint to login_activity.
"""

import psycopg2
import sys
import os
from dotenv import load_dotenv

def run_migration():
    """Run the database schema migration."""
    load_dotenv()
    
    db_params = {
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT', '5432'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD')
    }
    
    try:
        print("🔌 Connecting to database...")
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()
        
        # Add device_fingerprint to login_activity
        print("🔄 Updating `login_activity` table...")
        cursor.execute("""
            ALTER TABLE login_activity 
            ADD COLUMN IF NOT EXISTS device_fingerprint VARCHAR(255);
        """)

        conn.commit()
        print("✅ Database migration completed successfully!")
        
        cursor.close()
        conn.close()
        
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
