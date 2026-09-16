#!/usr/bin/env python3
"""
Migration 010: Flag which group members were matched automatically

A group can mix both kinds of match: listings the scraper matched on price, plot
and bedrooms, plus listings a user linked by hand. Without a per-member flag the
UI cannot tell them apart inside the same group, so it cannot show the "+N"
badge only for automatically matched listings.

Run from the project root: python migrations/010_member_auto_match_flag.py
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
    logging.info(f"Connecting to Database {config.DB_NAME} at {config.DB_HOST}:{config.DB_PORT}...")

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

        logging.info("Adding is_auto_matched to property_group_members...")
        cursor.execute("""
            ALTER TABLE property_group_members
                ADD COLUMN IF NOT EXISTS is_auto_matched BOOLEAN NOT NULL DEFAULT TRUE;
        """)
        # Existing rows pre-date manual links, so they are all automatic matches;
        # the next grouping run sets the flag correctly for every member.

        conn.commit()
        cursor.close()
        conn.close()
        logging.info("Migration 010 completed successfully.")
        return True

    except Exception as e:
        logging.error(f"Migration 010 failed: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
