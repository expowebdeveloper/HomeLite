#!/usr/bin/env python3
"""
Scraper Logs + Live Run Tracking Migration

Adds the shared channel the scraper uses to publish its progress and log output,
so the SARDO360 portal can show — live — which scrapers are running, what they
are doing, and whether they completed or failed.

Adds to `scrape_runs`:
    last_heartbeat_at  -- updated periodically while a run is alive. A 'running'
                          row with a stale heartbeat is a CRASHED run, not a live
                          one. Without this, a killed scraper stays "running"
                          forever (runs #1 and #2 already did exactly that).
    progress_current   -- e.g. 20   ("Scraping 20/174")
    progress_total     -- e.g. 174
    triggered_by       -- 'manual' | 'schedule' | ...

Creates `scrape_logs`: one row per log line, streamed by the scraper.

ADDITIVE AND IDEMPOTENT. Deletes nothing.
"""

import psycopg2
import sys
import os
from dotenv import load_dotenv

STEPS = [
    ("Adding live-progress columns to `scrape_runs`", """
        ALTER TABLE scrape_runs
            ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS progress_current  INTEGER,
            ADD COLUMN IF NOT EXISTS progress_total    INTEGER,
            ADD COLUMN IF NOT EXISTS triggered_by      VARCHAR(50);
    """),

    ("Creating `scrape_logs` table", """
        CREATE TABLE IF NOT EXISTS scrape_logs (
            id            BIGSERIAL PRIMARY KEY,
            scrape_run_id BIGINT REFERENCES scrape_runs(id) ON DELETE CASCADE,
            source_name   VARCHAR(255),
            level         VARCHAR(10) NOT NULL DEFAULT 'INFO',
            message       TEXT NOT NULL,
            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """),

    ("Indexing `scrape_logs` for fast incremental tailing", """
        CREATE INDEX IF NOT EXISTS idx_scrape_logs_run_id     ON scrape_logs (scrape_run_id, id);
        CREATE INDEX IF NOT EXISTS idx_scrape_logs_created_at ON scrape_logs (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_scrape_logs_level      ON scrape_logs (level);
    """),

    ("Indexing `scrape_runs` for the live activity view", """
        CREATE INDEX IF NOT EXISTS idx_scrape_runs_status    ON scrape_runs (run_status);
        CREATE INDEX IF NOT EXISTS idx_scrape_runs_heartbeat ON scrape_runs (last_heartbeat_at DESC);
    """),

    # Runs #1 and #2 were left 'running' forever by a crashed scraper. Seed a
    # heartbeat for any existing live-looking row so the stale check has a basis.
    ("Backfilling heartbeat for existing rows", """
        UPDATE scrape_runs
           SET last_heartbeat_at = COALESCE(last_heartbeat_at, completed_at, started_at)
         WHERE last_heartbeat_at IS NULL;
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

        cursor.execute("SELECT COUNT(*) FROM scrape_logs;")
        print(f"\n📊 scrape_logs rows: {cursor.fetchone()[0]}")
        cursor.execute("SELECT run_status, COUNT(*) FROM scrape_runs GROUP BY run_status;")
        print("📊 scrape_runs by status:")
        for status, n in cursor.fetchall():
            print(f"   {status}: {n}")

        print("\n✅ Migration completed successfully!")
        print("ℹ️  The portal can now display live scraper activity — but the SCRAPER")
        print("   must publish to these tables. See SCRAPER_LOGGING_SPEC.md.")

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
