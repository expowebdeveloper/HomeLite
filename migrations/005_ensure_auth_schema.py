#!/usr/bin/env python3
"""
Auth Schema Bootstrap Migration

These schema checks used to run inside DatabaseManager.__init__, i.e. on every
single app start. That is dangerous: each one issues DDL (ALTER TABLE users ...),
which needs an ACCESS EXCLUSIVE lock. If any connection is sitting
"idle in transaction" (which the manager used to do after every SELECT), the
ALTER blocks forever, and every subsequent query against `users` queues behind
it — hanging login for everyone.

They now live here and are run explicitly, once, as a migration.

Usage:
    python migrations/005_ensure_auth_schema.py
"""

import os
import sys

# Allow importing DatabaseManager when run from the repo root or from migrations/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DatabaseManager  # noqa: E402


def run_migration():
    print("🔌 Connecting to database...")
    db = DatabaseManager()
    if not db.connection:
        print("❌ Could not connect to the database.")
        sys.exit(1)

    steps = [
        ("Ensuring `login_activity` table", db.ensure_login_activity_table),
        ("Ensuring security columns on `users`", db.ensure_security_columns),
        ("Ensuring `user_sessions` table", db.ensure_user_sessions_table),
    ]

    failed = False
    for description, step in steps:
        print(f"🔄 {description}...")
        try:
            if step() is False:
                print(f"   ⚠️  {description} reported failure (see logs).")
                failed = True
        except Exception as e:
            print(f"   ❌ {description} raised: {e}")
            failed = True

    db.disconnect()

    if failed:
        print("\n⚠️  Migration finished with warnings.")
        sys.exit(1)

    print("\n✅ Auth schema bootstrap completed successfully!")


if __name__ == "__main__":
    run_migration()
