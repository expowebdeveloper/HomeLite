#!/usr/bin/env python3
"""
Authentication Database Migration Script

This script migrates the existing database to the new authentication schema,
maintaining backward compatibility.
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
        
        # 1. Update existing `users` table
        print("🔄 Updating `users` table...")
        cursor.execute("""
            ALTER TABLE users 
            ADD COLUMN IF NOT EXISTS email VARCHAR(255) UNIQUE,
            ADD COLUMN IF NOT EXISTS two_factor_enabled BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS google_auth_secret VARCHAR(255),
            ADD COLUMN IF NOT EXISTS backup_codes JSONB,
            ADD COLUMN IF NOT EXISTS last_login TIMESTAMP,
            ADD COLUMN IF NOT EXISTS last_login_ip VARCHAR(64),
            ADD COLUMN IF NOT EXISTS last_login_device VARCHAR(255);
        """)
        
        # 2. Update `login_activity` table (Ensure it has everything, backward compatible)
        print("🔄 Verifying `login_activity` table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_activity (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                username VARCHAR(100),
                ip_address VARCHAR(64),
                country VARCHAR(100),
                user_agent TEXT,
                event_type VARCHAR(30) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 3. Create `user_otps` table
        print("📋 Creating `user_otps` table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_otps (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                otp_hash VARCHAR(255) NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                attempts INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_otps_user ON user_otps(user_id);")

        # 4. Create `user_sessions` table
        print("📋 Creating `user_sessions` table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                session_token VARCHAR(255) UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                ip_address VARCHAR(64),
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON user_sessions(session_token);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);")

        # 5. Create `trusted_devices` table
        print("📋 Creating `trusted_devices` table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trusted_devices (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                device_id VARCHAR(255) UNIQUE NOT NULL,
                device_name VARCHAR(255),
                ip_address VARCHAR(64),
                user_agent TEXT,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trusted_devices_user ON trusted_devices(user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trusted_devices_id ON trusted_devices(device_id);")

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
