#!/usr/bin/env python3
"""
Migration 011: Add Role, Permission and Account Status Columns to Users Table

Adds support for Role-Based Access Control (RBAC):
- role: VARCHAR(50) DEFAULT 'sub_admin' (e.g. 'super_admin', 'sub_admin', 'restricted_user')
- is_active: BOOLEAN NOT NULL DEFAULT TRUE
- can_view_scrapers: BOOLEAN DEFAULT TRUE
- can_view_reports: BOOLEAN DEFAULT TRUE
- can_manage_users: BOOLEAN DEFAULT FALSE
- Creates password_requests table for tracking reset requests

Applies strictly to the local database configured in .env.

Run from project root: python migrations/011_add_user_roles_and_permissions.py
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

        logging.info("Adding role, permission and status columns to users table...")
        cursor.execute("""
            ALTER TABLE users
                ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'sub_admin',
                ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS can_view_scrapers BOOLEAN DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS can_view_reports BOOLEAN DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS can_manage_users BOOLEAN DEFAULT FALSE;
        """)

        logging.info("Creating password_requests table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_requests (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                email VARCHAR(255) NOT NULL,
                status VARCHAR(50) DEFAULT 'waiting',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                temp_password VARCHAR(255)
            );
        """)

        logging.info("Updating existing administrator accounts to super_admin...")
        cursor.execute("""
            UPDATE users
            SET role = 'super_admin',
                can_manage_users = TRUE,
                can_view_scrapers = TRUE,
                can_view_reports = TRUE,
                is_active = TRUE
            WHERE LOWER(username) IN ('admin', 'expoweb', 'sardorealestate@gmail.com')
               OR LOWER(email) IN ('admin@example.com', 'expowebdeveloper@gmail.com', 'sardorealestate@gmail.com');
        """)

        conn.commit()
        cursor.close()
        conn.close()
        logging.info("Migration 011 completed successfully.")
        return True

    except Exception as e:
        logging.error(f"Migration 011 failed: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
