#!/usr/bin/env python3

import os
import sys

# Run directly from the project root: python scripts/<name>.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg2
import os
from dotenv import load_dotenv

def run_migration():
    load_dotenv()
    db_params = {
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT', '5432'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD')
    }
    try:
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()
        
        cursor.execute("""
            ALTER TABLE users 
            ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP,
            ADD COLUMN IF NOT EXISTS trusted_devices JSONB DEFAULT '[]'::jsonb;
        """)
        
        conn.commit()
        print("✅ Security migration successful!")
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ Database error: {e}")

if __name__ == "__main__":
    run_migration()
