#!/usr/bin/env python3
"""
Property Status Tracking Migration Script

Adds the property status + lifecycle columns to `properties`, and creates the
`scrape_runs` and `property_status_history` tables.

This migration is ADDITIVE AND IDEMPOTENT. It does not delete or rewrite any
existing property data.

Deliberately NOT included (owned by the scraper team, requires manual review):
  * De-duplicating rows that share (source, property_url)  -- deletes data
  * The UNIQUE constraint on (source, property_url)        -- fails while dupes exist
See SCRAPER_STATUS_TRACKING_SPEC.md sections 2 and 3.

Note: properties.id is a UUID, so property_status_history.property_id is UUID
(the original spec's BIGINT is wrong for this database).
"""

import psycopg2
import sys
import os
from dotenv import load_dotenv

VALID_STATUSES = (
    'For Sale', 'New Listing', 'Reserved', 'Under Offer',
    'Sold', 'Exclusive', 'Delisted', 'Unknown',
)

STEPS = [
    ("Adding status + lifecycle columns to `properties`", """
        ALTER TABLE properties
            ADD COLUMN IF NOT EXISTS property_status        VARCHAR(50) NOT NULL DEFAULT 'For Sale',
            ADD COLUMN IF NOT EXISTS previous_status        VARCHAR(50),
            ADD COLUMN IF NOT EXISTS raw_status_text        VARCHAR(255),
            ADD COLUMN IF NOT EXISTS first_seen_at          TIMESTAMP,
            ADD COLUMN IF NOT EXISTS last_seen_at           TIMESTAMP,
            ADD COLUMN IF NOT EXISTS status_last_changed_at TIMESTAMP;
    """),

    # Existing stock is "For Sale" (the column default), never "New Listing".
    ("Backfilling first_seen_at / last_seen_at from created_at / updated_at", """
        UPDATE properties
           SET first_seen_at = COALESCE(first_seen_at, created_at),
               last_seen_at  = COALESCE(last_seen_at, updated_at, created_at)
         WHERE first_seen_at IS NULL OR last_seen_at IS NULL;
    """),

    ("Constraining property_status to the canonical vocabulary", """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname = 'properties_property_status_chk'
            ) THEN
                ALTER TABLE properties
                    ADD CONSTRAINT properties_property_status_chk
                    CHECK (property_status IN (
                        'For Sale','New Listing','Reserved','Under Offer',
                        'Sold','Exclusive','Delisted','Unknown'
                    ));
            END IF;
        END$$;
    """),

    ("Creating indexes for status + date-range reporting", """
        CREATE INDEX IF NOT EXISTS idx_properties_property_status ON properties (property_status);
        CREATE INDEX IF NOT EXISTS idx_properties_first_seen_at   ON properties (first_seen_at);
        CREATE INDEX IF NOT EXISTS idx_properties_last_seen_at    ON properties (last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_properties_status_changed  ON properties (status_last_changed_at);
        CREATE INDEX IF NOT EXISTS idx_properties_source_status   ON properties (source, property_status);
    """),

    # Created before property_status_history: it is referenced by a foreign key.
    ("Creating `scrape_runs` table", """
        CREATE TABLE IF NOT EXISTS scrape_runs (
            id                  BIGSERIAL PRIMARY KEY,
            source_name         VARCHAR(255) NOT NULL,
            started_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at        TIMESTAMP,
            run_status          VARCHAR(20) NOT NULL DEFAULT 'running',
            properties_found    INTEGER DEFAULT 0,
            new_properties      INTEGER DEFAULT 0,
            updated_properties  INTEGER DEFAULT 0,
            status_changes      INTEGER DEFAULT 0,
            delisted_properties INTEGER DEFAULT 0,
            errors_count        INTEGER DEFAULT 0,
            notes               TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_scrape_runs_source_started
            ON scrape_runs (source_name, started_at DESC);
    """),

    ("Creating `property_status_history` table (property_id is UUID)", """
        CREATE TABLE IF NOT EXISTS property_status_history (
            id              BIGSERIAL PRIMARY KEY,
            property_id     UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
            previous_status VARCHAR(50),
            new_status      VARCHAR(50) NOT NULL,
            changed_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_url      TEXT,
            raw_status_text VARCHAR(255),
            scrape_run_id   BIGINT REFERENCES scrape_runs(id),
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_psh_property_id ON property_status_history (property_id);
        CREATE INDEX IF NOT EXISTS idx_psh_changed_at  ON property_status_history (changed_at);
        CREATE INDEX IF NOT EXISTS idx_psh_new_status  ON property_status_history (new_status);
    """),
]


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

    conn = None
    try:
        print("🔌 Connecting to database...")
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()

        for description, sql in STEPS:
            print(f"🔄 {description}...")
            cursor.execute(sql)

        conn.commit()

        # Report what we ended up with.
        cursor.execute("""
            SELECT property_status, COUNT(*) FROM properties
            GROUP BY property_status ORDER BY 2 DESC;
        """)
        print("\n📊 Properties by status:")
        for status, count in cursor.fetchall():
            print(f"   {status}: {count}")

        print("\n✅ Database migration completed successfully!")
        print("⚠️  Reminder: de-duplication + the UNIQUE (source, property_url) constraint")
        print("   are NOT applied here. See SCRAPER_STATUS_TRACKING_SPEC.md §2.")

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
