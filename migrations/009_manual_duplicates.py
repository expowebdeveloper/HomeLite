#!/usr/bin/env python3
"""
Migration 009: Manual duplicate links

The grouping engine rebuilds property_groups / property_group_members from
scratch after every scrape, so anything a user marks by hand has to live in its
own table. Creates:
- manual_duplicate_links: one row per pair of properties a user marked as the
  same physical property. The rebuild never deletes from it.
- property_groups.match_type: 'automatic', 'manual' or 'mixed', so the UI can
  show which groups were added manually.

Run from the project root: python migrations/009_manual_duplicates.py
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
    logging.info(f"Connecting to Database {config.DB_NAME} at {config.DB_HOST}:{config.DB_PORT} as {config.DB_USER}...")

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

        logging.info("Creating manual_duplicate_links table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manual_duplicate_links (
                id SERIAL PRIMARY KEY,
                property_id_a UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                property_id_b UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                created_by VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                -- Each pair is stored once, smallest id first.
                CONSTRAINT manual_duplicate_links_ordered CHECK (property_id_a < property_id_b),
                CONSTRAINT manual_duplicate_links_pair_key UNIQUE (property_id_a, property_id_b)
            );

            CREATE INDEX IF NOT EXISTS idx_manual_duplicate_links_b
                ON manual_duplicate_links (property_id_b);
        """)

        logging.info("Adding match_type to property_groups...")
        cursor.execute("""
            ALTER TABLE property_groups
                ADD COLUMN IF NOT EXISTS match_type VARCHAR(20) NOT NULL DEFAULT 'automatic';
        """)

        conn.commit()
        cursor.close()
        conn.close()
        logging.info("Migration 009 completed successfully.")
        return True

    except Exception as e:
        logging.error(f"Migration 009 failed: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
