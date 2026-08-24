"""
Migration 007: Property Tags Support

Adds:
- `tags` column (TEXT[] DEFAULT '{}') to `properties` table.
- GIN index `idx_properties_tags` on `properties USING GIN (tags)` for rapid array filtering.
"""

import logging
import os
import sys
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_migration():
    logger.info("Connecting to database...")
    conn = psycopg2.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        dbname=Config.DB_NAME,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        connect_timeout=10
    )
    conn.autocommit = True

    try:
        with conn.cursor() as cursor:
            logger.info("Checking if 'tags' column exists on 'properties' table...")
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'properties' AND column_name = 'tags';
            """)
            if not cursor.fetchone():
                logger.info("Adding 'tags' column (TEXT[] DEFAULT '{}') to 'properties' table...")
                cursor.execute("""
                    ALTER TABLE properties 
                    ADD COLUMN tags TEXT[] DEFAULT '{}';
                """)
                logger.info("Added 'tags' column successfully.")
            else:
                logger.info("'tags' column already exists.")

            logger.info("Creating GIN index 'idx_properties_tags'...")
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_properties_tags 
                ON properties USING GIN (tags);
            """)
            logger.info("GIN index verified successfully.")

        logger.info("✅ Migration 007 (Property Tags) completed successfully!")
    finally:
        conn.close()

if __name__ == '__main__':
    run_migration()
