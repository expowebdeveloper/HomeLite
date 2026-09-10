"""User accounts, passwords, OTP and TOTP/MFA state.

Split out of the original database.DatabaseManager; the method bodies are
unchanged and are recomposed into a single class in __init__.py.
"""

import os

import psycopg2
import psycopg2.extras
import logging
import datetime
from typing import Dict, Optional


class UsersMixin:
    """User accounts, passwords, OTP and TOTP/MFA state."""

    
    def create_user(self, email: str, username: str, password_hash: str) -> bool:
        """Create a new user."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT INTO users (email, username, password_hash)
                VALUES (%s, %s, %s)
            """, (email, username, password_hash))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error creating user: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def get_user_by_identifier(self, identifier: str) -> Optional[Dict]:
        """Fetch a user by their username or email"""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return None
        
        ident = identifier.strip().lower()
        return self._fetch_user("LOWER(username) = %s OR LOWER(email) = %s",
                                (ident, ident), f"by identifier {ident!r}")

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Fetch a user by their ID"""
        return self._fetch_user("id = %s", (user_id,), f"by id {user_id}")

    def _fetch_user(self, where_sql: str, params: tuple, what: str) -> Optional[Dict]:
        """Run a single-row user lookup, retrying once if the connection died.

        This matters for login: a dropped connection makes the query raise, and if
        we just returned None the caller could not tell "database unreachable" apart
        from "no such user" �€� so a perfectly valid account gets rejected with
        'Invalid credentials'. A server-side disconnect is only detected when a query
        is actually attempted, so the first attempt can fail even though
        connection.closed was still 0.
        """
        for attempt in (1, 2):
            if not self.connection or self.connection.closed:
                if not self.connect():
                    return None
            try:
                cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute(f"SELECT * FROM users WHERE {where_sql}", params)
                user = cursor.fetchone()
                cursor.close()
                return dict(user) if user else None
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                # Connection-level failure: discard it and retry once on a fresh one.
                logging.warning(f"Connection lost fetching user {what} (attempt {attempt}): {e}")
                try:
                    self.connection.close()
                except Exception:
                    pass
                self.connection = None
                if attempt == 2:
                    logging.error(f"Error fetching user {what}: connection unrecoverable")
                    return None
            except Exception as e:
                logging.error(f"Error fetching user {what}: {e}")
                return None
        return None

    def store_otp(self, user_id: int, otp_hash: str, expires_at: float) -> bool:
        """Store a new OTP in the database, clearing any previous active ones."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            expires_dt = datetime.datetime.fromtimestamp(expires_at)
            cursor = self.connection.cursor()
            # Clear existing OTPs for the user
            cursor.execute("DELETE FROM user_otps WHERE user_id = %s", (user_id,))
            # Insert the new OTP
            cursor.execute("""
                INSERT INTO user_otps (user_id, otp_hash, expires_at, attempts)
                VALUES (%s, %s, %s, 0)
            """, (user_id, otp_hash, expires_dt))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error storing OTP: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def get_active_otp(self, user_id: int) -> Optional[Dict]:
        """Get the active OTP for a user, if it has not expired."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return None
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT id, user_id, otp_hash, expires_at, attempts, created_at
                FROM user_otps
                WHERE user_id = %s AND expires_at > CURRENT_TIMESTAMP
                ORDER BY created_at DESC LIMIT 1
            """, (user_id,))
            otp = cursor.fetchone()
            cursor.close()
            return dict(otp) if otp else None
        except Exception as e:
            logging.error(f"Error fetching active OTP: {e}")
            return None

    def increment_otp_attempts(self, otp_id: int) -> bool:
        """Increment the attempts counter for an OTP."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE user_otps
                SET attempts = attempts + 1
                WHERE id = %s
            """, (otp_id,))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error incrementing OTP attempts: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def clear_otp(self, user_id: int) -> bool:
        """Clear all OTPs for a user."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM user_otps WHERE user_id = %s", (user_id,))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error clearing OTP: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def ensure_security_columns(self):
        """Ensure security columns exist on the users table."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                ALTER TABLE users 
                ADD COLUMN IF NOT EXISTS email VARCHAR(255) UNIQUE,
                ADD COLUMN IF NOT EXISTS two_factor_enabled BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS google_auth_secret VARCHAR(255),
                ADD COLUMN IF NOT EXISTS backup_codes JSONB,
                ADD COLUMN IF NOT EXISTS last_login TIMESTAMP,
                ADD COLUMN IF NOT EXISTS last_login_ip VARCHAR(64),
                ADD COLUMN IF NOT EXISTS last_login_device VARCHAR(255),
                ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0,
                ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP,
                ADD COLUMN IF NOT EXISTS trusted_devices JSONB DEFAULT '[]'::jsonb;
            """)
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error ensuring security columns exist: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def increment_failed_login(self, user_id: int) -> int:
        if not self.connection or self.connection.closed:
            if not self.connect():
                return 0
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE users 
                SET failed_login_attempts = failed_login_attempts + 1,
                    locked_until = CASE WHEN failed_login_attempts + 1 >= 5 THEN NOW() + INTERVAL '15 minutes' ELSE locked_until END
                WHERE id = %s
                RETURNING failed_login_attempts
            """, (user_id,))
            attempts = cursor.fetchone()[0]
            self.connection.commit()
            cursor.close()
            return attempts
        except Exception as e:
            logging.error(f"Error incrementing failed logins: {e}")
            return 0

    def reset_failed_login(self, user_id: int):
        if not self.connection or self.connection.closed:
            if not self.connect():
                return
        try:
            cursor = self.connection.cursor()
            cursor.execute("UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE id = %s", (user_id,))
            self.connection.commit()
            cursor.close()
        except Exception as e:
            logging.error(f"Error resetting failed logins: {e}")

    def add_trusted_device(self, user_id: int, fingerprint: str):
        if not self.connection or self.connection.closed:
            if not self.connect():
                return
        try:
            cursor = self.connection.cursor()
            # Append fingerprint if not already in JSON array
            cursor.execute("""
                UPDATE users
                SET trusted_devices = (
                    CASE 
                        WHEN trusted_devices @> %s::jsonb THEN trusted_devices
                        ELSE trusted_devices || %s::jsonb
                    END
                )
                WHERE id = %s
            """, (psycopg2.extras.Json([fingerprint]), psycopg2.extras.Json([fingerprint]), user_id))
            self.connection.commit()
            cursor.close()
        except Exception as e:
            logging.error(f"Error adding trusted device: {e}")

    def is_new_device_for_user(self, user_id: int, fingerprint: str, browser: str, os_info: str) -> bool:
        """Check if this device fingerprint or browser/OS has been successfully used by this user before."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False  # Fail open/silent
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT 1 FROM login_activity 
                WHERE user_id = %s 
                  AND event_type IN ('login_success', 'api_login_success')
                  AND (device_fingerprint = %s OR (browser = %s AND os = %s))
                LIMIT 1
            """, (user_id, fingerprint, browser, os))
            result = cursor.fetchone()
            cursor.close()
            return result is None
        except Exception as e:
            logging.error(f"Error checking new device: {e}")
            return False

    def is_new_location_for_user(self, user_id: int, country: str) -> bool:
        """Check if the user has successfully logged in from this country before."""
        if not country or country == 'Local':
            return False
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT 1 FROM login_activity 
                WHERE user_id = %s 
                  AND event_type IN ('login_success', 'api_login_success')
                  AND country = %s
                LIMIT 1
            """, (user_id, country))
            result = cursor.fetchone()
            cursor.close()
            return result is None
        except Exception as e:
            logging.error(f"Error checking new location: {e}")
            return False
            return False

    def set_mfa_status(self, user_id: int, status: bool) -> bool:
        """Enable or disable MFA for a user."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE users
                SET two_factor_enabled = %s
                WHERE id = %s
            """, (status, user_id))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error updating MFA status: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def set_totp_secret(self, user_id: int, encrypted_secret: str) -> bool:
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("UPDATE users SET google_auth_secret = %s WHERE id = %s", (encrypted_secret, user_id))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error setting TOTP secret: {e}")
            return False

    def enable_totp_mfa(self, user_id: int, encrypted_backup_codes) -> bool:
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE users 
                SET mfa_enabled = TRUE, backup_codes = %s 
                WHERE id = %s
            """, (psycopg2.extras.Json(encrypted_backup_codes), user_id))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error enabling TOTP: {e}")
            return False

    def disable_totp_mfa(self, user_id: int) -> bool:
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE users 
                SET mfa_enabled = FALSE, google_auth_secret = NULL, backup_codes = NULL 
                WHERE id = %s
            """, (user_id,))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error disabling TOTP: {e}")
            return False

    def update_backup_codes(self, user_id: int, encrypted_backup_codes) -> bool:
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("UPDATE users SET backup_codes = %s WHERE id = %s", (psycopg2.extras.Json(encrypted_backup_codes), user_id))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error updating backup codes: {e}")
            return False

    def update_user_password(self, user_id: int, new_password_hash: str) -> bool:
        """Update a user's password hash."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE users
                SET password_hash = %s
                WHERE id = %s
            """, (new_password_hash, user_id))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error updating password hash: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def update_last_login(self, user_id: int, ip: str, device: str) -> bool:
        """Update last login details."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE users
                SET last_login = CURRENT_TIMESTAMP,
                    last_login_ip = %s,
                    last_login_device = %s
                WHERE id = %s
            """, (ip, device, user_id))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error updating last login: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False
