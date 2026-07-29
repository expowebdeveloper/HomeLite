#!/usr/bin/env python3
"""
Manual Off-Market Property Migration Script

Adds source_type, market_visibility, and optional off-market metadata columns to `properties`,
and creates the `property_documents` table for media uploads.

ADDITIVE AND IDEMPOTENT. Deletes nothing.
"""

import psycopg2
import sys
import os
from dotenv import load_dotenv

STEPS = [
    ("Adding manual off-market columns to `properties`", """
        ALTER TABLE properties
            ADD COLUMN IF NOT EXISTS source_type VARCHAR(50) DEFAULT 'scraped' NOT NULL,
            ADD COLUMN IF NOT EXISTS market_visibility VARCHAR(50) DEFAULT 'public' NOT NULL,
            ADD COLUMN IF NOT EXISTS resort_area VARCHAR(50),
            ADD COLUMN IF NOT EXISTS sub_area VARCHAR(50),
            ADD COLUMN IF NOT EXISTS address VARCHAR(100),
            ADD COLUMN IF NOT EXISTS coordinates VARCHAR(100),
            ADD COLUMN IF NOT EXISTS construction_year VARCHAR(10),
            ADD COLUMN IF NOT EXISTS renovation_year VARCHAR(10),
            ADD COLUMN IF NOT EXISTS energy_rating VARCHAR(10),
            ADD COLUMN IF NOT EXISTS source_contact_name VARCHAR(50),
            ADD COLUMN IF NOT EXISTS source_contact_email VARCHAR(50),
            ADD COLUMN IF NOT EXISTS source_contact_phone VARCHAR(50),
            ADD COLUMN IF NOT EXISTS source_agent VARCHAR(50),
            ADD COLUMN IF NOT EXISTS date_introduced TIMESTAMP,
            ADD COLUMN IF NOT EXISTS introduced_by VARCHAR(50),
            ADD COLUMN IF NOT EXISTS notes TEXT,
            ADD COLUMN IF NOT EXISTS sold_at TIMESTAMP WITHOUT TIME ZONE NULL;
    """),

    ("Creating indexes on source_type, market_visibility, and sold_at", """
        CREATE INDEX IF NOT EXISTS idx_properties_source_type ON properties (source_type);
        CREATE INDEX IF NOT EXISTS idx_properties_market_visibility ON properties (market_visibility);
        CREATE INDEX IF NOT EXISTS idx_properties_sold_at ON properties (sold_at);
    """),

    ("Creating `property_documents` table for media uploads", """
        CREATE TABLE IF NOT EXISTS property_documents (
            id BIGSERIAL PRIMARY KEY,
            property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
            document_type VARCHAR(100) DEFAULT 'Image',
            file_name VARCHAR(255) NOT NULL,
            file_url TEXT NOT NULL,
            uploaded_by BIGINT,
            uploaded_at TIMESTAMP DEFAULT now(),
            notes TEXT
        );
    """),

    ("Indexing `property_documents` table", """
        CREATE INDEX IF NOT EXISTS idx_prop_docs_property_id ON property_documents (property_id);
    """),
]


def run_migration():
    load_dotenv()
    db_params = {
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT', '5432'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
    }

    conn = None
    try:
        print("🔌 Connecting to database...")
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()

        for description, sql in STEPS:
            print(f"🔄 {description}...")
            cursor.execute(sql)

        conn.commit()

        cursor.execute("SELECT count(*) FROM properties WHERE source_type = 'manual';")
        print(f"\n📊 Manual off-market properties: {cursor.fetchone()[0]}")
        cursor.execute("SELECT count(*) FROM property_documents;")
        print(f"📊 Property documents: {cursor.fetchone()[0]}")

        print("\n✅ Migration 007 completed successfully!")
        cursor.close()
        conn.close()

    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        print(f"❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_migration()
