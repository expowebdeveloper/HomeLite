import os
import sys
import logging
import psycopg2

sys.path.insert(0, os.path.abspath(r'..\HomeLite'))
from app.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def run():
    config = Config()
    if config.DB_HOST not in ('localhost', '127.0.0.1'):
        logging.error(f"ABORTING: Expected local database, but DB_HOST is '{config.DB_HOST}'")
        return False

    logging.info(f"Connecting to LOCAL database {config.DB_NAME} at {config.DB_HOST}:{config.DB_PORT}...")
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

        logging.info("Creating custom_roles table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS custom_roles (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                role_key VARCHAR(100) NOT NULL UNIQUE,
                description TEXT,
                is_system BOOLEAN DEFAULT FALSE,
                can_view_dashboard BOOLEAN DEFAULT TRUE,
                can_view_reports BOOLEAN DEFAULT TRUE,
                can_export_reports BOOLEAN DEFAULT TRUE,
                can_view_scrapers BOOLEAN DEFAULT TRUE,
                can_run_scrapers BOOLEAN DEFAULT FALSE,
                can_manage_users BOOLEAN DEFAULT FALSE,
                can_manage_settings BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        logging.info("Seeding system built-in roles...")
        cursor.execute("""
            INSERT INTO custom_roles (
                name, role_key, description, is_system,
                can_view_dashboard, can_view_reports, can_export_reports,
                can_view_scrapers, can_run_scrapers, can_manage_users, can_manage_settings
            ) VALUES
            (
                'Super admin', 'super_admin',
                'Full permissions across all modules. Cannot be changed or deleted.', TRUE,
                TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE
            ),
            (
                'Sub-Admin', 'sub_admin',
                'Works applications end to end: reports, scrapers, and pipeline monitoring.', TRUE,
                TRUE, TRUE, TRUE, TRUE, TRUE, FALSE, FALSE
            ),
            (
                'Restricted User', 'restricted_user',
                'Access limited to Dashboard and Market Intelligence overview.', TRUE,
                TRUE, FALSE, FALSE, FALSE, FALSE, FALSE, FALSE
            )
            ON CONFLICT (role_key) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                is_system = EXCLUDED.is_system;
        """)

        conn.commit()
        cursor.close()
        conn.close()
        logging.info("Migration 012 completed successfully on local database.")

        # Also write the migration file to HomeLite/migrations/012_add_custom_roles_table.py
        migration_file = os.path.abspath(r'..\HomeLite\migrations\012_add_custom_roles_table.py')
        with open(__file__, 'r', encoding='utf-8') as src:
            code = src.read()
        with open(migration_file, 'w', encoding='utf-8') as dst:
            dst.write(code)
        logging.info(f"Saved migration script to {migration_file}")
        return True

    except Exception as e:
        logging.error(f"Migration failed: {e}")
        return False

if __name__ == '__main__':
    run()
