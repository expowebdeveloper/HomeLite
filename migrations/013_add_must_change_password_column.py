#!/usr/bin/env python3
"""
Migration 013: Add must_change_password Column to Users Table

Ensures newly created users with temporary passwords are required to reset
their password on first login.
"""
import os
import sys
import logging
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def run_migration():
    config = Config()
    logging.info(f"Connecting to database {config.DB_NAME} at {config.DB_HOST}:{config.DB_PORT} as {config.DB_USER}...")
    try:
        conn = psycopg2.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            database=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            connect_timeout=10
        )
        conn.autocommit = False
        cursor = conn.cursor()

        logging.info("Adding must_change_password column to users table if missing...")
        cursor.execute("""
            ALTER TABLE users
                ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE;
        """)

        conn.commit()
        cursor.close()
        conn.close()
        logging.info("Migration 013 completed successfully.")
        return True

    except Exception as e:
        logging.error(f"Migration 013 failed: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        return False

if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
