import psycopg2
import psycopg2.extras
from typing import List, Dict, Optional, Tuple
import logging
import time
import datetime
import uuid
import re
from config import Config

class DatabaseManager:
    def __init__(self):
        self.config = Config()
        self.connection = None
        self._cache = {}
        self._cache_ttl = 300 # 5 minutes
        self.connect()
        # NOTE: schema bootstrap (ensure_login_activity_table / ensure_security_columns /
        # ensure_user_sessions_table) deliberately does NOT run here. Issuing DDL on every
        # app start takes an ACCESS EXCLUSIVE lock on `users`; if any connection is sitting
        # idle-in-transaction, the ALTER blocks forever and every later `users` query queues
        # behind it, which hangs login. Run migrations/005_ensure_auth_schema.py instead.

    def _get_cached(self, key):
        if key in self._cache:
            if time.time() - self._cache[key]['time'] < self._cache_ttl:
                return self._cache[key]['data']
        return None

    def _set_cache(self, key, data):
        self._cache[key] = {'time': time.time(), 'data': data}
        
    def connect(self):
        """Establish connection to PostgreSQL database"""
        try:
            self.connection = psycopg2.connect(
                host=self.config.DB_HOST,
                port=self.config.DB_PORT,
                database=self.config.DB_NAME,
                user=self.config.DB_USER,
                password=self.config.DB_PASSWORD,
                # Detect connections dropped by RDS/network instead of letting them
                # linger as half-open sockets that only fail on the next query.
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5,
            )
            # This manager holds one long-lived connection and is overwhelmingly
            # read-only. Without autocommit, psycopg2 opens a transaction on the
            # first SELECT and never closes it, so the connection sits
            # "idle in transaction" holding locks indefinitely — which blocks any
            # later ALTER TABLE (and therefore login). Explicit commit()/rollback()
            # calls elsewhere in this class become harmless no-ops.
            self.connection.autocommit = True
            logging.info("Database connection established successfully")
            return True
        except Exception as e:
            logging.error(f"Database connection failed: {e}")
            return False
    
    def disconnect(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            logging.info("Database connection closed")
    
    def get_locations(self) -> List[str]:
        """
        Get all unique locations from the database for the location selector
        
        Returns:
            List of unique location strings
        """
        cached = self._get_cached('locations')
        if cached is not None:
            return cached

        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        
        try:
            query = """
                SELECT DISTINCT location 
                FROM properties 
                WHERE location IS NOT NULL AND location != '' AND location != 'N/A'
                ORDER BY location
            """
            
            cursor = self.connection.cursor()
            cursor.execute(query)
            locations = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            self._set_cache('locations', locations)
            return locations
            
        except Exception as e:
            logging.error(f"Error fetching locations: {e}")
            return []
    
    def get_property_types(self) -> List[str]:
        """
        Get all unique property types from the database for the property type selector
        
        Returns:
            List of unique property type strings
        """
        cached = self._get_cached('property_types')
        if cached is not None:
            return cached

        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        
        try:
            query = """
                SELECT DISTINCT property_type 
                FROM properties 
                WHERE property_type IS NOT NULL AND property_type != '' AND property_type != 'N/A'
                ORDER BY property_type
            """
            
            cursor = self.connection.cursor()
            cursor.execute(query)
            property_types = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            self._set_cache('property_types', property_types)
            return property_types
            
        except Exception as e:
            logging.error(f"Error fetching property types: {e}")
            return []
    
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
        from "no such user" — so a perfectly valid account gets rejected with
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


    def ensure_login_activity_table(self):
        """Create the login_activity table if it does not exist."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS login_activity (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    username VARCHAR(100),
                    ip_address VARCHAR(64),
                    country VARCHAR(100),
                    user_agent TEXT,
                    event_type VARCHAR(30) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                ALTER TABLE login_activity
                ADD COLUMN IF NOT EXISTS browser VARCHAR(100),
                ADD COLUMN IF NOT EXISTS os VARCHAR(100),
                ADD COLUMN IF NOT EXISTS device_fingerprint VARCHAR(255);
            """)
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error ensuring login_activity table: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def ensure_user_sessions_table(self):
        """Create the user_sessions table if it does not exist."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    session_token VARCHAR(255) UNIQUE,
                    expires_at TIMESTAMP,
                    ip_address VARCHAR(45),
                    user_agent TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error ensuring user_sessions table: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def log_login_activity(self, event_type, username=None, user_id=None,
                           ip_address=None, country=None, user_agent=None,
                           browser=None, os=None, device_fingerprint=None):
        """Insert a login activity record. Best-effort: never raises."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT INTO login_activity
                    (user_id, username, ip_address, country, user_agent, event_type, browser, os, device_fingerprint)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, username, ip_address, country, user_agent, event_type, browser, os, device_fingerprint))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error logging login activity: {e}")
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

    def create_user_session(self, user_id: int, session_token: str, expires_at: float, 
                            ip_address: str, user_agent: str) -> bool:
        """Create a persistent user session (refresh token)."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            expires_dt = datetime.datetime.fromtimestamp(expires_at)
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT INTO user_sessions (user_id, session_token, expires_at, ip_address, user_agent)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, session_token, expires_dt, ip_address, user_agent))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error creating user session: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def validate_session_token(self, token: str) -> bool:
        """Check if a session token (refresh token) exists and is valid."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT id FROM user_sessions WHERE session_token = %s AND expires_at > CURRENT_TIMESTAMP", (token,))
            row = cursor.fetchone()
            cursor.close()
            return bool(row)
        except Exception as e:
            logging.error(f"Error validating session token: {e}")
            return False

    def cleanup_expired_sessions(self) -> bool:
        """Delete sessions that have expired."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE expires_at < CURRENT_TIMESTAMP")
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error cleaning up expired sessions: {e}")
            return False

    def get_active_sessions(self, user_id: int) -> List[Dict]:
        """Fetch all active sessions for a user."""
        self.cleanup_expired_sessions()
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT id, session_token, expires_at, ip_address, user_agent, created_at, last_active
                FROM user_sessions
                WHERE user_id = %s
                ORDER BY last_active DESC
            """, (user_id,))
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logging.error(f"Error fetching active sessions: {e}")
            return []

    def revoke_session(self, user_id: int, session_id: int) -> bool:
        """Revoke a specific session by ID (ensuring it belongs to the user)."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE id = %s AND user_id = %s", (session_id, user_id))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error revoking session: {e}")
            return False

    def revoke_all_sessions(self, user_id: int) -> bool:
        """Revoke all sessions for a user (Global Logout)."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error revoking all sessions: {e}")
            return False

    def revoke_session_by_token(self, token: str) -> bool:
        """Revoke a session by its token string."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE session_token = %s", (token,))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error revoking session by token: {e}")
            return False

    def get_login_history(self, limit: int = 100, username: str = None) -> List[Dict]:
        """Fetch recent login activity, newest first."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if username:
                cursor.execute("""
                    SELECT id, user_id, username, ip_address, country,
                           user_agent, event_type, created_at
                    FROM login_activity
                    WHERE username = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (username, limit))
            else:
                cursor.execute("""
                    SELECT id, user_id, username, ip_address, country,
                           user_agent, event_type, created_at
                    FROM login_activity
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (limit,))
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logging.error(f"Error fetching login history: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return []

    def get_properties(self, filters: Dict, limit: int = None, offset: int = None) -> Dict:
        """
        Get properties based on filters with pagination support
        
        Args:
            filters: Dictionary containing filter criteria
            limit: Maximum number of records to return
            offset: Number of records to skip
            
        Returns:
            Dictionary containing 'properties' list and 'total_count' int
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'properties': [], 'total_count': 0}
        
        base_query = """
                FROM (
                    SELECT p_inner.*,
                           'SARDO' || (1099 + ROW_NUMBER() OVER(ORDER BY COALESCE(p_inner.source, ''), COALESCE(p_inner.image_filename, ''))) as sardo_reference,
                           pgm.id as member_id,
                           pgm.group_id,
                           pgm.is_representative,
                           pg.group_code,
                           (SELECT COUNT(*) FROM property_group_members WHERE group_id = pgm.group_id) as duplicate_count
                    FROM properties p_inner
                    LEFT JOIN property_group_members pgm ON pgm.property_id = p_inner.id
                    LEFT JOIN property_groups pg ON pg.id = pgm.group_id
                ) as p
                WHERE 1=1
            """
        params = []

        # We defer stock_mode filtering to AFTER the count query, so the count query can dynamically return both active and unique stats.
        stock_mode = filters.get('stock_mode', 'active')
        # Price range filtering with NULL handling
        if filters.get('min_price') is not None:
            # If min_price is provided, exclude NULL prices and include properties with price >= min_price
            base_query += " AND price >= %s AND price IS NOT NULL"
            params.append(filters['min_price'])
        
        if filters.get('max_price') is not None:
            # If max_price is provided, exclude NULL prices and include properties with price <= max_price
            base_query += " AND price <= %s AND price IS NOT NULL"
            params.append(filters['max_price'])

        # Reference / SARDO ID search
        if filters.get('reference'):
            ref_query = f"%{filters['reference'].strip()}%"
            base_query += " AND (reference ILIKE %s OR sardo_reference ILIKE %s OR title ILIKE %s)"
            params.extend([ref_query, ref_query, ref_query])
        
        # Location filtering - handle both single location and multiple locations
        if filters.get('location'):
            # Single location (backward compatibility)
            location = filters['location'].strip()
            base_query += " AND (LOWER(location) LIKE LOWER(%s) OR LOWER(location) LIKE LOWER(%s))"
            params.append(f"%{location}%")
            params.append(f"{location}%")
        elif filters.get('locations'):
            # Multiple locations
            locations = filters['locations']
            if locations:
                location_conditions = []
                for location in locations:
                    location_conditions.append("(LOWER(location) LIKE LOWER(%s) OR LOWER(location) LIKE LOWER(%s))")
                    params.append(f"%{location.strip()}%")
                    params.append(f"{location.strip()}%")
                base_query += f" AND ({' OR '.join(location_conditions)})"
        
        # Property type filtering
        if filters.get('property_type'):
            base_query += " AND property_type = %s"
            params.append(filters['property_type'])
        
        # Bedrooms filtering with NULL handling
        if filters.get('na_beds'):
            base_query += " AND (bedrooms IS NULL OR TRIM(bedrooms) IN ('', 'N/A', 'None'))"
        else:
            if filters.get('min_beds') is not None:
                # If min_beds is provided, exclude NULL bedrooms and include properties with bedrooms >= min_beds
                base_query += " AND CAST(NULLIF(regexp_replace(bedrooms::text, '[^0-9.]', '', 'g'), '') AS numeric) >= %s AND bedrooms IS NOT NULL"
                params.append(filters['min_beds'])
            
            if filters.get('max_beds') is not None:
                # If max_beds is provided, exclude NULL bedrooms and include properties with bedrooms <= max_beds
                base_query += " AND CAST(NULLIF(regexp_replace(bedrooms::text, '[^0-9.]', '', 'g'), '') AS numeric) <= %s AND bedrooms IS NOT NULL"
                params.append(filters['max_beds'])
        
        # Bathrooms filtering with NULL handling
        if filters.get('na_baths'):
            base_query += " AND (bathrooms IS NULL OR TRIM(bathrooms) IN ('', 'N/A', 'None'))"
        else:
            if filters.get('min_baths') is not None:
                # If min_baths is provided, exclude NULL bathrooms and include properties with bathrooms >= min_baths
                base_query += " AND CAST(NULLIF(regexp_replace(bathrooms::text, '[^0-9.]', '', 'g'), '') AS numeric) >= %s AND bathrooms IS NOT NULL"
                params.append(filters['min_baths'])
            
            if filters.get('max_baths') is not None:
                # If max_baths is provided, exclude NULL bathrooms and include properties with bathrooms <= max_baths
                base_query += " AND CAST(NULLIF(regexp_replace(bathrooms::text, '[^0-9.]', '', 'g'), '') AS numeric) <= %s AND bathrooms IS NOT NULL"
                params.append(filters['max_baths'])

        # Property status filtering (canonical SARDO360 statuses only)
        statuses = filters.get('statuses') or filters.get('property_status')
        if statuses:
            if isinstance(statuses, str):
                statuses = [statuses]
            statuses = [s for s in statuses if s in Config.PROPERTY_STATUSES]
            if statuses:
                query_statuses = list(statuses)
                if 'For Sale' in query_statuses and 'Unknown' not in query_statuses:
                    query_statuses.append('Unknown')
                placeholders = ', '.join(['%s'] * len(query_statuses))
                base_query += f" AND (property_status IN ({placeholders})"
                if 'For Sale' in query_statuses:
                    base_query += " OR property_status IS NULL)"
                else:
                    base_query += ")"
                params.extend(query_statuses)

        # Hide delisted stock (opt-in, so existing callers are unaffected)
        if filters.get('exclude_delisted'):
            base_query += " AND (property_status IS NULL OR property_status <> 'Delisted')"

        # Hide sold stock (opt-in)
        if filters.get('exclude_sold'):
            base_query += " AND (property_status IS NULL OR property_status <> 'Sold')"

        # Market visibility filtering
        vis = filters.get('market_visibility')
        if vis and str(vis).strip().lower() in ('public', 'off_market'):
            base_query += " AND market_visibility = %s"
            params.append(str(vis).strip().lower())

        # Source type filtering
        stype = filters.get('source_type')
        if stype and str(stype).strip().lower() in ('scraped', 'manual'):
            base_query += " AND source_type = %s"
            params.append(str(stype).strip().lower())

        # Agent / source filtering (exact match on the raw source or friendly name)
        sources = filters.get('sources') or filters.get('source')
        if sources:
            if isinstance(sources, str):
                sources = [sources]
            sources = [s.strip() for s in sources if s and s.strip()]
            if sources:
                expanded_sources = []
                for s in sources:
                    expanded_sources.append(s)
                    for raw_key, friendly_name in Config.SOURCE_NAME_MAPPING.items():
                        if friendly_name == s:
                            expanded_sources.append(raw_key)
                    if not s.endswith("Scraper"):
                        expanded_sources.append(s + "Scraper")
                        
                # Remove duplicates
                expanded_sources = list(set(expanded_sources))
                placeholders = ', '.join(['%s'] * len(expanded_sources))
                base_query += f" AND source IN ({placeholders})"
                params.extend(expanded_sources)

        # Tags filtering (match properties containing ANY of the selected tags)
        tags = filters.get('tags')
        if tags:
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(',') if t.strip()]
            tags = [t.strip() for t in tags if t and t.strip()]
            if tags:
                base_query += " AND tags && %s::text[]"
                params.append(tags)

        # Date range: when the property was first seen
        if filters.get('first_seen_from'):
            base_query += " AND first_seen_at >= %s::timestamp"
            params.append(filters['first_seen_from'])
        if filters.get('first_seen_to'):
            base_query += " AND first_seen_at < (%s::date + INTERVAL '1 day')"
            params.append(filters['first_seen_to'])

        # Date range: when the status last changed
        if filters.get('status_changed_from'):
            base_query += " AND status_last_changed_at >= %s::timestamp"
            params.append(filters['status_changed_from'])
        if filters.get('status_changed_to'):
            base_query += " AND status_last_changed_at < (%s::date + INTERVAL '1 day')"
            params.append(filters['status_changed_to'])

        try:
            # Get the dynamic stats for the current filters
            count_query = "SELECT COUNT(*) as active_properties, COUNT(*) FILTER (WHERE p.member_id IS NULL OR p.is_representative = TRUE) as unique_properties " + base_query
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(count_query, params)
            stats_row = cursor.fetchone()
            
            active_properties = stats_row['active_properties'] if stats_row else 0
            unique_properties = stats_row['unique_properties'] if stats_row else 0
            
            # Now append stock mode for the actual paginated query
            if stock_mode == 'unique':
                base_query += " AND (p.member_id IS NULL OR p.is_representative = TRUE)"
                
            total_count = unique_properties if stock_mode == 'unique' else active_properties
            
            # Then get the actual paginated records
            query = """
                SELECT 
                    id,
                    title,
                    property_type,
                    location,
                    price as property_price,
                    bedrooms as num_beds,
                    bathrooms as num_baths,
                    living_area,
                    land_area,
                    source as website_source,
                    image_filename,
                    image_filename_2,
                    image_filename_3,
                    map_filename,
                    reference,
                    property_url,
                    property_status,
                    previous_status,
                    first_seen_at,
                    last_seen_at,
                    status_last_changed_at,
                    created_at,
                    updated_at,
                    sardo_reference,
                    group_id,
                    group_code,
                    is_representative,
                    COALESCE(duplicate_count, 1) as duplicate_count,
                    COALESCE(tags, '{}') as tags,
                    source_type,
                    market_visibility,
                    resort_area,
                    sub_area,
                    address,
                    coordinates,
                    construction_year,
                    renovation_year,
                    energy_rating,
                    source_contact_name,
                    source_contact_email,
                    source_contact_phone,
                    source_agent,
                    introduced_by,
                    date_introduced,
                    notes
            """ + base_query
            
            # Add sorting with multiple criteria
            sort_by = filters.get('sort_by', 'created_at')
            sort_dir = filters.get('sort_dir', 'DESC').upper()
            
            # Map frontend columns to db columns
            sort_column_map = {
                'price': 'price',
                'location': 'location',
                'property_type': 'property_type',
                'bedrooms': 'bedrooms',
                'bathrooms': 'bathrooms',
                'living_area': 'living_area',
                'land_area': 'land_area',
                'website_source': 'source',
                'property_status': 'property_status',
                'first_seen_at': 'first_seen_at',
                'last_seen_at': 'last_seen_at',
                'status_last_changed_at': 'status_last_changed_at',
                'created_at': 'created_at'
            }
            
            # Default to created_at if invalid sort column
            db_sort_col = sort_column_map.get(sort_by, 'created_at')
            if sort_dir not in ['ASC', 'DESC']:
                sort_dir = 'DESC'
                
            if db_sort_col == 'created_at':
                query += f" ORDER BY {db_sort_col} {sort_dir}, price ASC"
            elif db_sort_col == 'price':
                # Push P.O.A. prices (-1, 0, NULL) to the bottom regardless of direction
                query += f" ORDER BY CASE WHEN price IS NULL OR price <= 0 THEN 1 ELSE 0 END ASC, price {sort_dir}, created_at DESC"
            else:
                # Push nulls to the bottom regardless of direction
                query += f" ORDER BY {db_sort_col} {sort_dir} NULLS LAST, created_at DESC"
            
            # Add secondary sort by id for consistent pagination
            query += ", id DESC"
            
            # Add pagination
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
                
            if offset is not None:
                query += " OFFSET %s"
                params.append(offset)
                
            cursor.execute(query, params)
            records = cursor.fetchall()
            cursor.close()
            
            return {
                'properties': [dict(record) for record in records],
                'total_count': total_count,
                'stats': {
                    'active_properties': active_properties,
                    'unique_properties': unique_properties,
                    'duplicate_listings': max(0, active_properties - unique_properties)
                }
            }
            
        except Exception as e:
            logging.error(f"Error fetching properties: {e}")
            return {'properties': [], 'total_count': 0}
    
    def get_property_by_id(self, property_id: str) -> Optional[Dict]:
        """
        Get a single property by its ID
        
        Args:
            property_id: ID of the property
            
        Returns:
            Property dictionary or None if not found
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return None
        
        try:
            query = """
                SELECT 
                    id,
                    title,
                    property_type,
                    location,
                    price as property_price,
                    bedrooms as num_beds,
                    bathrooms as num_baths,
                    living_area,
                    land_area,
                    source as website_source,
                    image_filename,
                    image_filename_2,
                    image_filename_3,
                    map_filename,
                    reference,
                    property_url,
                    property_status,
                    previous_status,
                    first_seen_at,
                    last_seen_at,
                    status_last_changed_at,
                    created_at,
                    updated_at,
                    source_type,
                    market_visibility,
                    resort_area,
                    sub_area,
                    address,
                    coordinates,
                    construction_year,
                    renovation_year,
                    energy_rating,
                    source_contact_name,
                    source_contact_email,
                    source_contact_phone,
                    source_agent,
                    introduced_by,
                    date_introduced,
                    COALESCE(tags, '{}') as tags,
                    notes
                FROM properties
                WHERE id = %s
            """
            
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(query, (property_id,))
            property_data = cursor.fetchone()
            cursor.close()
            
            if not property_data:
                return None
            data = dict(property_data)
            data['documents'] = self.get_property_documents(property_id)
            return data
            
        except Exception as e:
            logging.error(f"Error fetching property {property_id}: {e}")
            return None

    def get_all_tags(self) -> List[Dict]:
        """Get all distinct tags in use across all properties, sorted with counts."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT tag, COUNT(*) as count
                FROM (
                    SELECT unnest(tags) as tag FROM properties WHERE tags IS NOT NULL AND array_length(tags, 1) > 0
                ) t
                WHERE tag IS NOT NULL AND tag != ''
                GROUP BY tag
                ORDER BY count DESC, tag ASC;
            """)
            rows = cursor.fetchall()
            cursor.close()
            return [{'tag': row[0], 'count': row[1]} for row in rows]
        except Exception as e:
            logging.error(f"Error fetching tags: {e}")
            return []

    def get_global_tags(self) -> List[Dict]:
        """Get all curated global tags with real-time property usage counts."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT 
                    gt.id,
                    gt.name,
                    gt.category,
                    gt.color,
                    gt.description,
                    COALESCE(u.usage_count, 0) as usage_count
                FROM global_tags gt
                LEFT JOIN (
                    SELECT unnest(tags) as tag_name, COUNT(*) as usage_count
                    FROM properties
                    WHERE tags IS NOT NULL AND array_length(tags, 1) > 0
                    GROUP BY unnest(tags)
                ) u ON LOWER(gt.name) = LOWER(u.tag_name)
                ORDER BY 
                    CASE 
                        WHEN gt.category = 'Views & Location' THEN 1
                        WHEN gt.category = 'Features & Amenities' THEN 2
                        WHEN gt.category = 'Investment & Legal' THEN 3
                        WHEN gt.category = 'Style & Quality' THEN 4
                        ELSE 5
                    END,
                    u.usage_count DESC,
                    gt.name ASC;
            """)
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logging.error(f"Error fetching global tags: {e}")
            return []

    def create_global_tag(self, name: str, category: str = 'General', color: str = '#4f46e5', description: str = '') -> Dict:
        """Create a new global tag in the library."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
        clean_name = str(name).strip()
        if not clean_name:
            return {'success': False, 'error': 'Tag name cannot be empty'}
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                INSERT INTO global_tags (name, category, color, description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE
                SET category = EXCLUDED.category,
                    color = EXCLUDED.color,
                    description = EXCLUDED.description
                RETURNING id, name, category, color, description;
            """, (clean_name, category.strip() or 'General', color.strip() or '#4f46e5', description.strip()))
            row = cursor.fetchone()
            self.connection.commit()
            cursor.close()
            return {'success': True, 'tag': dict(row)}
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            logging.error(f"Error creating global tag {name}: {e}")
            return {'success': False, 'error': str(e)}

    def delete_global_tag(self, name: str) -> Dict:
        """Delete a global tag from the library."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
        clean_name = str(name).strip()
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM global_tags WHERE LOWER(name) = LOWER(%s);", (clean_name,))
            self.connection.commit()
            cursor.close()
            return {'success': True}
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            logging.error(f"Error deleting global tag {name}: {e}")
            return {'success': False, 'error': str(e)}

    def bulk_assign_tag_to_properties(self, property_ids: List[str], tag: str, action: str = 'add') -> Dict:
        """
        Add or remove a tag from multiple properties simultaneously.
        
        Args:
            property_ids: List of property IDs.
            tag: Tag name to add/remove.
            action: 'add' to append tag, 'remove' to remove tag.
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}

        clean_tag = str(tag).strip()
        if not clean_tag:
            return {'success': False, 'error': 'Tag cannot be empty'}
        if not property_ids:
            return {'success': False, 'error': 'No properties selected'}

        try:
            cursor = self.connection.cursor()
            
            # If adding, ensure it exists in global_tags library
            if action == 'add':
                cursor.execute("""
                    INSERT INTO global_tags (name, category, color)
                    VALUES (%s, 'Custom', '#6366f1')
                    ON CONFLICT (name) DO NOTHING;
                """, (clean_tag,))

            # Fetch current tags of target properties
            cursor.execute("""
                SELECT id::text, COALESCE(tags, '{}') as tags 
                FROM properties 
                WHERE id::text = ANY(%s::text[]);
            """, (property_ids,))
            rows = cursor.fetchall()

            updates = []
            for row in rows:
                p_id, cur_tags = row[0], row[1]
                cur_tags = list(cur_tags or [])
                
                if action == 'add':
                    # Add if not already present
                    if not any(t.lower() == clean_tag.lower() for t in cur_tags):
                        cur_tags.append(clean_tag)
                        updates.append((cur_tags, p_id))
                elif action == 'remove':
                    # Remove if present
                    new_tags = [t for t in cur_tags if t.lower() != clean_tag.lower()]
                    if len(new_tags) != len(cur_tags):
                        updates.append((new_tags, p_id))

            if updates:
                psycopg2.extras.execute_batch(
                    cursor,
                    "UPDATE properties SET tags = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                    updates
                )
                self.connection.commit()

            cursor.close()
            self._cache.pop('statistics', None)
            return {
                'success': True,
                'action': action,
                'tag': clean_tag,
                'updated_count': len(updates),
                'total_selected': len(property_ids)
            }
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            logging.error(f"Error in bulk_assign_tag_to_properties: {e}")
            return {'success': False, 'error': str(e)}

    def update_property_tags(self, property_id: str, tags: List[str]) -> Dict:
        """Update tags array for a single property."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
        try:
            clean_tags = []
            seen_lower = set()
            for t in (tags or []):
                t_clean = str(t).strip()
                if t_clean and t_clean.lower() not in seen_lower:
                    clean_tags.append(t_clean)
                    seen_lower.add(t_clean.lower())

            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE properties 
                SET tags = %s, updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s;
            """, (clean_tags, property_id))
            self.connection.commit()
            cursor.close()
            self._cache.pop('statistics', None)
            return {'success': True, 'tags': clean_tags}
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            logging.error(f"Error updating property tags for {property_id}: {e}")
            return {'success': False, 'error': str(e)}

    def bulk_update_tags_from_csv(self, csv_rows: List[Dict], mode: str = 'replace') -> Dict:
        """
        Bulk update property tags from parsed CSV rows.
        
        Args:
            csv_rows: List of dicts with property identifier and tags.
            mode: 'replace' to overwrite existing tags, 'append' to merge with existing tags.
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}

        if not csv_rows:
            return {'success': False, 'error': 'CSV file is empty or contains no rows'}

        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Build an in-memory lookup map of all active properties
            cursor.execute("""
                SELECT 
                    id, 
                    reference, 
                    'SARDO' || (1099 + ROW_NUMBER() OVER(ORDER BY COALESCE(source, ''), COALESCE(image_filename, ''))) as sardo_reference,
                    COALESCE(tags, '{}') as current_tags
                FROM properties;
            """)
            all_props = cursor.fetchall()
            
            id_map = {}
            ref_map = {}
            sardo_map = {}
            numeric_sardo_map = {}
            
            for p in all_props:
                p_id = str(p['id'])
                id_map[p_id.lower()] = p
                
                if p.get('reference'):
                    ref_map[str(p['reference']).strip().lower()] = p
                    
                sardo_ref = str(p.get('sardo_reference', '')).strip().lower()
                if sardo_ref:
                    sardo_map[sardo_ref] = p
                    digits = ''.join(c for c in sardo_ref if c.isdigit())
                    if digits:
                        numeric_sardo_map[digits] = p

            matched_count = 0
            updated_count = 0
            unmatched_rows = []
            all_distinct_tags = set()
            updates_to_perform = []

            for row_idx, row in enumerate(csv_rows, start=1):
                prop_key = None
                for candidate in ['property_id', 'property id', 'id', 'sardo_reference', 'sardo ref', 'reference', 'ref']:
                    for k in row.keys():
                        if k and k.strip().lower() == candidate and row[k] is not None:
                            prop_key = str(row[k]).strip()
                            break
                    if prop_key:
                        break
                
                if not prop_key and len(row) > 0:
                    first_val = list(row.values())[0]
                    if first_val:
                        prop_key = str(first_val).strip()

                if not prop_key:
                    unmatched_rows.append({'row': row_idx, 'identifier': '(empty)', 'reason': 'Missing Property ID'})
                    continue

                raw_tags_str = None
                for candidate in ['tags', 'tag', 'property_tags', 'property tags', 'categories']:
                    for k in row.keys():
                        if k and k.strip().lower() == candidate and row[k] is not None:
                            raw_tags_str = str(row[k]).strip()
                            break
                    if raw_tags_str is not None:
                        break

                if raw_tags_str is None and len(row) > 1:
                    second_val = list(row.values())[1]
                    if second_val is not None:
                        raw_tags_str = str(second_val).strip()

                if raw_tags_str is None:
                    raw_tags_str = ''

                norm_key = prop_key.lower()
                matched_prop = (
                    id_map.get(norm_key) or 
                    sardo_map.get(norm_key) or 
                    ref_map.get(norm_key) or 
                    numeric_sardo_map.get(norm_key)
                )

                if not matched_prop:
                    unmatched_rows.append({'row': row_idx, 'identifier': prop_key, 'reason': f"No property found matching ID '{prop_key}'"})
                    continue

                matched_count += 1

                parsed_tags = []
                for part in re.split(r'[,;\n\r]+', raw_tags_str):
                    t = part.strip().strip('"').strip("'")
                    if t:
                        parsed_tags.append(t)

                new_tags = []
                seen_lower = set()
                
                if mode == 'append':
                    for existing_t in matched_prop.get('current_tags', []):
                        if existing_t and existing_t.lower() not in seen_lower:
                            new_tags.append(existing_t)
                            seen_lower.add(existing_t.lower())

                for t in parsed_tags:
                    if t.lower() not in seen_lower:
                        new_tags.append(t)
                        seen_lower.add(t.lower())
                        all_distinct_tags.add(t)

                updates_to_perform.append((new_tags, matched_prop['id']))

            if updates_to_perform:
                psycopg2.extras.execute_batch(
                    cursor,
                    "UPDATE properties SET tags = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                    updates_to_perform
                )
                self.connection.commit()
                updated_count = len(updates_to_perform)

            cursor.close()
            self._cache.pop('statistics', None)

            return {
                'success': True,
                'total_rows': len(csv_rows),
                'matched_count': matched_count,
                'updated_count': updated_count,
                'unmatched_rows': unmatched_rows,
                'distinct_tags_count': len(all_distinct_tags)
            }
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            logging.error(f"Error in bulk_update_tags_from_csv: {e}")
            return {'success': False, 'error': str(e)}

    def update_property_scraped_details(self, property_id: str, construction_year: str, energy_rating: str) -> bool:
        """Update construction year and energy rating in the database for a property"""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE properties 
                SET construction_year = %s, energy_rating = %s, updated_at = NOW()
                WHERE id = %s
            """, (construction_year, energy_rating, property_id))
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error updating scraped details for property {property_id}: {e}")
            return False
    
    def get_statistics(self) -> Dict:
        """Get basic statistics about the property database"""
        cached = self._get_cached('statistics')
        if cached is not None:
            return cached

        if not self.connection or self.connection.closed:
            if not self.connect():
                return {}
        
        try:
            stats = {}
            cursor = self.connection.cursor()
            
            # Combine total, avg, min, and max into a single query to reduce network latency
            cursor.execute("""
                SELECT 
                    COUNT(*),
                    AVG(CASE WHEN price > 0 THEN price ELSE NULL END),
                    MIN(CASE WHEN price > 0 THEN price ELSE NULL END),
                    MAX(CASE WHEN price > 0 THEN price ELSE NULL END)
                FROM properties
            """)
            total, avg_price, min_price, max_price = cursor.fetchone()
            
            stats['total_properties'] = total
            stats['avg_price'] = avg_price or 0
            stats['price_range'] = (min_price or 0, max_price or 0)
            
            # Properties by type
            cursor.execute("SELECT property_type, COUNT(*) FROM properties GROUP BY property_type")
            stats['by_type'] = {k if k is not None else 'Unknown': v for k, v in cursor.fetchall()}
            
            # Properties by source
            cursor.execute("SELECT source, COUNT(*) FROM properties GROUP BY source")
            stats['by_source'] = {k if k is not None else 'Unknown': v for k, v in cursor.fetchall()}

            # Properties by status
            cursor.execute("SELECT property_status, COUNT(*) FROM properties GROUP BY property_status")
            stats['by_status'] = {k if k is not None else 'Unknown': v for k, v in cursor.fetchall()}

            # Active stock excludes Sold and Delisted listings
            cursor.execute(
                "SELECT COUNT(*) FROM properties WHERE property_status <> ALL(%s)",
                (Config.INACTIVE_STATUSES,)
            )
            stats['active_properties'] = cursor.fetchone()[0]

            # Unique stock calculation (active stock minus duplicate surplus)
            cursor.execute("""
                SELECT COALESCE(COUNT(m.id) - COUNT(DISTINCT m.group_id), 0)
                FROM property_group_members m
                JOIN properties p ON p.id = m.property_id
                WHERE p.property_status <> ALL(%s);
            """, (Config.INACTIVE_STATUSES,))
            duplicate_surplus = cursor.fetchone()[0] or 0
            stats['unique_properties'] = max(0, stats['active_properties'] - duplicate_surplus)
            stats['duplicate_listings'] = duplicate_surplus

            cursor.close()
            self._set_cache('statistics', stats)
            return stats

        except Exception as e:
            logging.error(f"Error fetching statistics: {e}")
            return {}

    def get_property_group_info(self, property_id: str) -> Optional[Dict]:
        """Get duplicate group metadata and all agency listings for a property."""
        from grouping_engine import GroupingEngine
        engine = GroupingEngine(self.connection)
        return engine.get_property_group_info(property_id)

    def recalculate_unique_property_groups(self) -> Dict:
        """Run the grouping engine to refresh all duplicate groups."""
        from grouping_engine import GroupingEngine
        engine = GroupingEngine(self.connection)
        res = engine.run_grouping()
        self._cache.pop('statistics', None)
        return res

    def get_sources(self) -> List[str]:
        """Get the distinct agent/source values, for the source filter."""
        cached = self._get_cached('sources')
        if cached is not None:
            return cached

        if not self.connection or self.connection.closed:
            if not self.connect():
                return []

        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT DISTINCT source FROM properties
                WHERE source IS NOT NULL AND source != '' AND source != 'N/A'
                ORDER BY source
            """)
            sources = [row[0] for row in cursor.fetchall()]
            cursor.close()
            self._set_cache('sources', sources)
            return sources
        except Exception as e:
            logging.error(f"Error fetching sources: {e}")
            return []

    def get_status_report(self, date_from: str = None, date_to: str = None) -> Dict:
        """Build the property status report (spec section 6).

        Current-state figures (active stock, status breakdown) always reflect
        "right now". Movement figures (new listings, sold, delisted) are scoped
        to the supplied date range when one is given.

        `property_status_history` is written by the scraper; until it runs, the
        movement figures are legitimately zero.
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {}

        # Build a reusable date-range predicate for the history table
        history_clause = ""
        history_params = []
        if date_from:
            history_clause += " AND h.changed_at >= %s::timestamp"
            history_params.append(date_from)
        if date_to:
            history_clause += " AND h.changed_at < (%s::date + INTERVAL '1 day')"
            history_params.append(date_to)

        seen_clause = ""
        seen_params = []
        if date_from:
            seen_clause += " AND first_seen_at >= %s::timestamp"
            seen_params.append(date_from)
        if date_to:
            seen_clause += " AND first_seen_at < (%s::date + INTERVAL '1 day')"
            seen_params.append(date_to)

        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            report = {'date_from': date_from, 'date_to': date_to}

            # Current status counts per source
            cursor.execute("""
                SELECT source, property_status, COUNT(*) AS n
                FROM properties GROUP BY source, property_status
            """)
            per_source = {}
            for row in cursor.fetchall():
                src = row['source'] or 'Unknown'
                per_source.setdefault(src, {})[row['property_status']] = row['n']

            # New listings per source (by first_seen_at, within range)
            cursor.execute(f"""
                SELECT source, COUNT(*) AS n FROM properties
                WHERE 1=1 {seen_clause}
                GROUP BY source
            """, seen_params)
            new_by_source = {(r['source'] or 'Unknown'): r['n'] for r in cursor.fetchall()}

            # Status movements per source, from the history table (within range)
            cursor.execute(f"""
                SELECT p.source, h.new_status, COUNT(*) AS n
                FROM property_status_history h
                JOIN properties p ON p.id = h.property_id
                WHERE 1=1 {history_clause}
                GROUP BY p.source, h.new_status
            """, history_params)
            moves = {}
            for row in cursor.fetchall():
                src = row['source'] or 'Unknown'
                moves.setdefault(src, {})[row['new_status']] = row['n']

            # Assemble the per-agent rows
            inactive = set(Config.INACTIVE_STATUSES)
            rows = []
            for src in sorted(set(per_source) | set(new_by_source) | set(moves)):
                statuses = per_source.get(src, {})
                moved = moves.get(src, {})
                rows.append({
                    'source': src,
                    'active_stock': sum(n for s, n in statuses.items() if s not in inactive),
                    'total_stock': sum(statuses.values()),
                    'new_listings': new_by_source.get(src, 0),
                    'reserved': statuses.get('Reserved', 0),
                    'under_offer': statuses.get('Under Offer', 0),
                    'exclusive': statuses.get('Exclusive', 0),
                    'sold': statuses.get('Sold', 0),
                    'delisted': statuses.get('Delisted', 0),
                    'moved_to_sold': moved.get('Sold', 0),
                    'moved_to_delisted': moved.get('Delisted', 0),
                    'moved_to_reserved': moved.get('Reserved', 0),
                    'moved_to_under_offer': moved.get('Under Offer', 0),
                })
            report['by_source'] = rows

            # Overall status breakdown (current)
            cursor.execute("SELECT property_status, COUNT(*) AS n FROM properties GROUP BY property_status")
            report['by_status'] = {r['property_status']: r['n'] for r in cursor.fetchall()}

            # Average days from first_seen_at to Sold / Delisted
            for target, key in (('Sold', 'avg_days_to_sold'), ('Delisted', 'avg_days_to_delisted')):
                cursor.execute(f"""
                    SELECT AVG(EXTRACT(EPOCH FROM (h.changed_at - p.first_seen_at)) / 86400.0) AS days
                    FROM property_status_history h
                    JOIN properties p ON p.id = h.property_id
                    WHERE h.new_status = %s AND p.first_seen_at IS NOT NULL {history_clause}
                """, [target] + history_params)
                value = cursor.fetchone()['days']
                report[key] = round(float(value), 1) if value is not None else None

            # Recent status changes (most recent first)
            cursor.execute(f"""
                SELECT h.changed_at, h.previous_status, h.new_status,
                       p.source, p.location, p.reference, p.property_url
                FROM property_status_history h
                JOIN properties p ON p.id = h.property_id
                WHERE 1=1 {history_clause}
                ORDER BY h.changed_at DESC
                LIMIT 100
            """, history_params)
            report['recent_changes'] = [dict(r) for r in cursor.fetchall()]

            # Properties sold within date range (client reporting requirement)
            sold_clause = ""
            sold_params = []
            if date_from:
                sold_clause += " AND sold_at >= %s::timestamp"
                sold_params.append(date_from)
            if date_to:
                sold_clause += " AND sold_at < (%s::date + INTERVAL '1 day')"
                sold_params.append(date_to)

            try:
                cursor.execute(f"""
                    SELECT reference, title, price, location, source, sold_at, property_url
                    FROM properties
                    WHERE property_status = 'Sold' AND sold_at IS NOT NULL {sold_clause}
                    ORDER BY sold_at DESC
                    LIMIT 500
                """, sold_params)
                report['sold_properties'] = [dict(r) for r in cursor.fetchall()]
            except Exception as ex:
                logging.warning(f"Could not query sold_properties: {ex}")
                report['sold_properties'] = []

            cursor.close()
            return report

        except Exception as e:
            logging.error(f"Error building status report: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return {}

    def get_scrape_runs(self, limit: int = 20) -> List[Dict]:
        """Recent scrape runs, for the audit view."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT id, source_name, started_at, completed_at, run_status,
                       properties_found, new_properties, updated_properties,
                       status_changes, delisted_properties, errors_count, notes
                FROM scrape_runs
                ORDER BY started_at DESC
                LIMIT %s
            """, (limit,))
            rows = [dict(r) for r in cursor.fetchall()]
            cursor.close()
            return rows
        except Exception as e:
            logging.error(f"Error fetching scrape runs: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return []

    # ------------------------------------------------------------------
    # Live scraper activity (Scraper Logs page)
    # ------------------------------------------------------------------

    # A run flagged 'running' whose heartbeat has gone quiet for longer than this
    # is treated as dead, not live. Without this a crashed scraper would show as
    # "running" forever — which is exactly what happened to runs #1 and #2.
    STALE_HEARTBEAT_SECONDS = 180

    def get_scraper_activity(self, limit: int = 25) -> Dict:
        """Current state of every scraper, plus the most recent runs.

        Returns {'runs': [...], 'active_count': int, 'server_time': datetime}.

        Each run carries a derived `live_status`:
            running   - flagged running and heart still beating
            stalled   - flagged running but the heartbeat went quiet (crashed)
            completed / failed / suspect - terminal states as recorded
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'runs': [], 'active_count': 0, 'server_time': None}

        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT
                    r.id, r.source_name, r.run_status, r.started_at, r.completed_at,
                    r.last_heartbeat_at, r.progress_current, r.progress_total,
                    r.triggered_by, r.properties_found, r.new_properties,
                    r.updated_properties, r.status_changes, r.delisted_properties,
                    r.errors_count, r.notes,
                    EXTRACT(EPOCH FROM (
                        now() - COALESCE(r.last_heartbeat_at, r.started_at)
                    )) AS seconds_since_heartbeat,
                    EXTRACT(EPOCH FROM (
                        COALESCE(r.completed_at, now()) - r.started_at
                    )) AS duration_seconds,
                    (SELECT COUNT(*) FROM scrape_logs l WHERE l.scrape_run_id = r.id) AS log_count,
                    (SELECT COUNT(*) FROM scrape_logs l
                      WHERE l.scrape_run_id = r.id AND l.level = 'ERROR') AS error_log_count
                FROM scrape_runs r
                ORDER BY r.started_at DESC
                LIMIT %s
            """, (limit,))
            rows = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT now() AS now;")
            server_time = cursor.fetchone()['now']
            cursor.close()

            active = 0
            for r in rows:
                quiet = r.get('seconds_since_heartbeat') or 0
                if r['run_status'] == 'running':
                    if quiet > self.STALE_HEARTBEAT_SECONDS:
                        r['live_status'] = 'stalled'
                        r['stale_reason'] = (
                            f"No heartbeat for {int(quiet)}s — the scraper most likely "
                            f"crashed or was killed."
                        )
                    else:
                        r['live_status'] = 'running'
                        active += 1
                else:
                    r['live_status'] = r['run_status']

                # Progress bar. Be defensive: NEVER render a half-filled bar for a run
                # that has already finished. Scrapers routinely forget to set
                # progress_current = progress_total on the final update (run #18 finished
                # having only ever written 1/2), and a 50% bar on a completed run reads
                # as "stuck" to the user. The run_status is the source of truth for
                # whether work is still happening; progress_* is only a hint.
                total = r.get('progress_total') or 0
                current = r.get('progress_current') or 0
                raw_pct = round(min(current / total * 100, 100), 1) if total > 0 else None

                if r['live_status'] == 'completed':
                    r['progress_percent'] = 100.0     # finished == 100% by definition
                    r['progress_state'] = 'done'
                elif r['live_status'] == 'running':
                    r['progress_percent'] = raw_pct
                    r['progress_state'] = 'active'
                elif r['live_status'] == 'suspect':
                    # A 'suspect' run did NOT crash. It scraped fine and then deliberately
                    # SKIPPED the delist sweep because the safety guard tripped. Rendering
                    # it like a failure ("Stopped at…", red) makes a healthy run look broken.
                    # It's a warning, not an error — and `notes` says exactly why.
                    r['progress_percent'] = 100.0 if r['run_status'] == 'suspect' else raw_pct
                    r['progress_state'] = 'warning'
                else:
                    # failed / stalled — genuinely died partway.
                    r['progress_percent'] = raw_pct
                    r['progress_state'] = 'stopped'

                # Surface the discrepancy where a run clearly did work (it has progress and
                # log output) but reported zero counters — that means the uploader never
                # wrote its totals back, not that the scrape found nothing.
                r['counters_missing'] = bool(
                    (r.get('properties_found') or 0) == 0
                    and ((r.get('progress_current') or 0) > 0 or (r.get('log_count') or 0) > 0)
                    and r['live_status'] in ('completed', 'suspect')
                )

            return {'runs': rows, 'active_count': active, 'server_time': server_time}

        except Exception as e:
            logging.error(f"Error fetching scraper activity: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return {'runs': [], 'active_count': 0, 'server_time': None}

    def get_scrape_logs(self, run_id: int, after_id: int = 0, before_id: int = None,
                        level: str = None, limit: int = 500) -> Dict:
        """Fetch log lines for one run.

        Three modes, mirroring how a real terminal behaves:

        * `after_id > 0`  -> incremental poll: only lines newer than what we already
                             have. Used while a scrape is streaming.
        * `before_id`     -> "load earlier": the chunk immediately preceding a line
                             we already have (scrolling back up).
        * neither         -> **tail**: the MOST RECENT `limit` lines.

        The tail default matters. A run can have thousands of lines (run #26 had
        1,985); loading the *first* 500 would leave the user staring at the start of
        the scrape and never showing the "Scraping completed" line at the end — which
        looks like the scrape is stuck partway.
        """
        empty = {'logs': [], 'total': 0, 'first_id': None, 'last_id': after_id, 'has_more_before': False}
        if not self.connection or self.connection.closed:
            if not self.connect():
                return empty
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            level_sql, level_params = "", []
            if level and level.upper() in ('INFO', 'WARNING', 'ERROR', 'DEBUG'):
                level_sql = " AND level = %s"
                level_params = [level.upper()]

            # Total matching lines, so the UI can say "showing last 500 of 1985"
            cursor.execute(
                f"SELECT COUNT(*) AS n FROM scrape_logs WHERE scrape_run_id = %s{level_sql}",
                [run_id] + level_params)
            total = cursor.fetchone()['n']

            if after_id and after_id > 0:
                # Incremental: new lines only, oldest-first.
                cursor.execute(f"""
                    SELECT id, scrape_run_id, source_name, level, message, created_at
                    FROM scrape_logs
                    WHERE scrape_run_id = %s AND id > %s{level_sql}
                    ORDER BY id ASC LIMIT %s
                """, [run_id, after_id] + level_params + [limit])
                rows = [dict(r) for r in cursor.fetchall()]
            else:
                # Tail (or "load earlier" when before_id is given): take the newest
                # `limit` rows with DESC, then flip back to chronological order.
                bound_sql, bound_params = "", []
                if before_id:
                    bound_sql = " AND id < %s"
                    bound_params = [before_id]
                cursor.execute(f"""
                    SELECT id, scrape_run_id, source_name, level, message, created_at
                    FROM scrape_logs
                    WHERE scrape_run_id = %s{bound_sql}{level_sql}
                    ORDER BY id DESC LIMIT %s
                """, [run_id] + bound_params + level_params + [limit])
                rows = [dict(r) for r in cursor.fetchall()][::-1]   # back to ASC

            cursor.close()

            first_id = rows[0]['id'] if rows else None
            last_id = rows[-1]['id'] if rows else after_id
            return {
                'logs': rows,
                'total': total,
                'first_id': first_id,
                'last_id': last_id,
                # Are there older lines above what we just returned?
                'has_more_before': bool(first_id) and len(rows) == limit,
            }
        except Exception as e:
            logging.error(f"Error fetching scrape logs: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return empty

    def mark_stalled_runs_failed(self) -> int:
        """Close out runs whose scraper died without finalising them.

        A crashed scraper leaves its row at 'running' forever, which poisons the
        delist guard's "last successful run" baseline. Returns rows updated.
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return 0
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE scrape_runs
                   SET run_status = 'failed',
                       completed_at = COALESCE(completed_at, now()),
                       notes = COALESCE(notes, '') ||
                               ' [auto-closed: no heartbeat, scraper presumed dead]'
                 WHERE run_status = 'running'
                   AND now() - COALESCE(last_heartbeat_at, started_at)
                       > (%s * INTERVAL '1 second')
            """, (self.STALE_HEARTBEAT_SECONDS,))
            n = cursor.rowcount
            self.connection.commit()
            cursor.close()
            if n:
                logging.warning(f"Auto-closed {n} stalled scrape run(s) as failed")
            return n
        except Exception as e:
            logging.error(f"Error closing stalled runs: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return 0

    def create_manual_property(self, data: Dict, user_id: int, force: bool = False) -> Dict:
        """Create a new manual off-market property with duplicate detection."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            property_type = data.get('property_type', 'Villa')
            bedrooms = data.get('bedrooms')
            try:
                bedrooms_int = int(bedrooms) if bedrooms is not None and str(bedrooms).strip() != '' else None
            except ValueError:
                bedrooms_int = None
                
            price = data.get('price')
            try:
                price = int(float(price)) if price is not None and str(price).strip() != '' else None
            except ValueError:
                price = None

            location = data.get('location', '').strip()
            coordinates = data.get('coordinates', '').strip()

            # Duplicate listing detection (spec section 5)
            if not force and not data.get('confirm_duplicate'):
                dup_conditions = ["property_type = %s", "source_type = 'scraped'"]
                dup_params = [property_type]
                
                if bedrooms_int is not None:
                    dup_conditions.append("bedrooms::varchar = %s")
                    dup_params.append(str(bedrooms_int))
                    
                if price is not None and price > 0:
                    dup_conditions.append("price >= %s AND price <= %s")
                    dup_params.extend([int(price * 0.95), int(price * 1.05)])
                    
                loc_conds = []
                if location:
                    loc_conds.append("location ILIKE %s")
                    dup_params.append(f"%{location}%")
                if coordinates:
                    loc_conds.append("coordinates = %s")
                    dup_params.append(coordinates)
                if loc_conds:
                    dup_conditions.append(f"({' OR '.join(loc_conds)})")
                    
                if len(dup_conditions) > 2:  # Ensure we have more than just type + source
                    dup_query = f"SELECT id, title, location, price, property_url FROM properties WHERE {' AND '.join(dup_conditions)} LIMIT 5"
                    cursor.execute(dup_query, dup_params)
                    matches = cursor.fetchall()
                    if matches:
                        cursor.close()
                        return {
                            'success': False,
                            'duplicate_warning': True,
                            'matches': [dict(m) for m in matches],
                            'message': f"Notice: {len(matches)} similar public listing(s) exist in this area. Proceed with creation?"
                        }

            # Generate synthetic URL and unique reference
            prop_uuid = str(uuid.uuid4())
            property_url = f"sardo://manual/{prop_uuid}"
            
            reference = data.get('reference', '').strip()
            if not reference:
                reference = f"SARDO-OM-{prop_uuid[:8].upper()}"

            # Helper for numeric conversion
            def to_int(val):
                try: return int(float(val)) if val is not None and str(val).strip() != '' else None
                except: return None

            def to_str(val):
                if val is None: return None
                s = str(val).strip()
                if s == '' or s == 'None': return None
                try:
                    f = float(s)
                    if f == int(f): return str(int(f))
                except:
                    pass
                return s

            now_dt = datetime.datetime.now()
            status = data.get('property_status', 'Off Market')
            sold_at = now_dt if status == 'Sold' else None
            
            insert_query = """
                INSERT INTO properties (
                    id, title, property_type, location, price, bedrooms, bathrooms,
                    living_area, land_area, source, reference, property_url,
                    property_status, raw_status_text, source_type, market_visibility,
                    resort_area, sub_area, address, coordinates, construction_year,
                    renovation_year, energy_rating, source_contact_name,
                    source_contact_email, source_contact_phone, source_agent,
                    introduced_by, date_introduced, notes, created_at, updated_at,
                    first_seen_at, last_seen_at, status_last_changed_at, sold_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                ) RETURNING id;
            """
            
            params = (
                prop_uuid,
                data.get('title', 'Untitled Off-Market Opportunity'),
                property_type,
                location,
                to_int(price),
                to_str(bedrooms),
                to_str(data.get('bathrooms')),
                to_str(data.get('living_area') or data.get('build_size')),
                to_str(data.get('land_area') or data.get('plot_size')),
                'Manual / Off-Market',
                reference,
                property_url,
                status,
                'Manual Off-Market Creation',
                'manual',
                data.get('market_visibility', 'off_market'),
                data.get('resort_area'),
                data.get('sub_area'),
                data.get('address'),
                coordinates,
                str(data.get('construction_year')) if data.get('construction_year') else None,
                str(data.get('renovation_year')) if data.get('renovation_year') else None,
                str(data.get('energy_rating')) if data.get('energy_rating') else None,
                data.get('source_contact_name'),
                data.get('source_contact_email'),
                data.get('source_contact_phone'),
                data.get('source_agent'),
                data.get('introduced_by'),
                data.get('date_introduced') or now_dt,
                data.get('notes'),
                now_dt, now_dt, now_dt, now_dt, now_dt, sold_at
            )
            
            cursor.execute(insert_query, params)
            ret_id = cursor.fetchone()['id']
            cursor.close()
            
            self._cache.pop('locations', None)
            self._cache.pop('property_types', None)
            self._cache.pop('statistics', None)
            
            logging.info(f"Created manual property {ret_id} ({reference}) by user {user_id}")
            return {'success': True, 'property_id': str(ret_id), 'reference': reference}
            
        except Exception as e:
            logging.error(f"Error creating manual property: {e}")
            return {'success': False, 'error': str(e)}

    def update_manual_property(self, property_id: str, data: Dict, user_id: int) -> Dict:
        """Update an existing manual property and audit status/price changes."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
            existing = cursor.fetchone()
            if not existing:
                cursor.close()
                return {'success': False, 'error': 'Property not found'}
                
            if existing.get('source_type') != 'manual':
                cursor.close()
                return {'success': False, 'error': 'Only manual properties can be updated via this endpoint'}
                
            old_status = existing.get('property_status')
            new_status = data.get('property_status', old_status)
            
            old_price = existing.get('price')
            try:
                new_price = float(data.get('price')) if data.get('price') is not None and str(data.get('price')).strip() != '' else None
            except ValueError:
                new_price = old_price

            now_dt = datetime.datetime.now()
            
            status_changed = (old_status != new_status)
            price_changed = (old_price != new_price)
            
            if status_changed or price_changed:
                audit_text = 'Manual Admin Update'
                if price_changed:
                    audit_text += f" (Price: {old_price} -> {new_price})"
                if status_changed:
                    audit_text += f" (Status: {old_status} -> {new_status})"
                    
                audit_sql = """
                    INSERT INTO property_status_history (
                        property_id, previous_status, new_status, changed_at, raw_status_text, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """
                cursor.execute(audit_sql, (property_id, old_status, new_status, now_dt, audit_text, now_dt))

            def to_int(val):
                try: return int(float(val)) if val is not None and str(val).strip() != '' else None
                except: return None

            def to_str(val):
                if val is None: return None
                s = str(val).strip()
                if s == '' or s == 'None': return None
                try:
                    f = float(s)
                    if f == int(f): return str(int(f))
                except:
                    pass
                return s

            update_sql = """
                UPDATE properties SET
                    title = %s,
                    property_type = %s,
                    location = %s,
                    price = %s,
                    bedrooms = %s,
                    bathrooms = %s,
                    living_area = %s,
                    land_area = %s,
                    property_status = %s,
                    previous_status = CASE WHEN %s THEN %s ELSE previous_status END,
                    status_last_changed_at = CASE WHEN %s THEN %s ELSE status_last_changed_at END,
                    sold_at = CASE WHEN %s THEN %s ELSE sold_at END,
                    market_visibility = %s,
                    resort_area = %s,
                    sub_area = %s,
                    address = %s,
                    coordinates = %s,
                    construction_year = %s,
                    renovation_year = %s,
                    energy_rating = %s,
                    source_contact_name = %s,
                    source_contact_email = %s,
                    source_contact_phone = %s,
                    source_agent = %s,
                    introduced_by = %s,
                    notes = %s,
                    updated_at = %s
                WHERE id = %s
            """
            
            params = (
                data.get('title', existing.get('title')),
                data.get('property_type', existing.get('property_type')),
                data.get('location', existing.get('location')),
                new_price,
                to_str(data.get('bedrooms', existing.get('bedrooms'))),
                to_str(data.get('bathrooms', existing.get('bathrooms'))),
                to_str(data.get('living_area', existing.get('living_area')) or data.get('build_size')),
                to_str(data.get('land_area', existing.get('land_area')) or data.get('plot_size')),
                new_status,
                status_changed, old_status,
                status_changed, now_dt,
                status_changed and new_status == 'Sold' and not existing.get('sold_at'), now_dt,
                data.get('market_visibility', existing.get('market_visibility') or 'off_market'),
                data.get('resort_area', existing.get('resort_area')),
                data.get('sub_area', existing.get('sub_area')),
                data.get('address', existing.get('address')),
                data.get('coordinates', existing.get('coordinates')),
                str(data.get('construction_year')) if data.get('construction_year') else existing.get('construction_year'),
                str(data.get('renovation_year')) if data.get('renovation_year') else existing.get('renovation_year'),
                str(data.get('energy_rating')) if data.get('energy_rating') else existing.get('energy_rating'),
                data.get('source_contact_name', existing.get('source_contact_name')),
                data.get('source_contact_email', existing.get('source_contact_email')),
                data.get('source_contact_phone', existing.get('source_contact_phone')),
                data.get('source_agent', existing.get('source_agent')),
                data.get('introduced_by', existing.get('introduced_by')),
                data.get('notes', existing.get('notes')),
                now_dt,
                property_id
            )
            
            cursor.execute(update_sql, params)
            cursor.close()
            
            self._cache.pop('locations', None)
            self._cache.pop('property_types', None)
            self._cache.pop('statistics', None)
            
            logging.info(f"Updated manual property {property_id} by user {user_id}")
            return {'success': True, 'property_id': property_id}
            
        except Exception as e:
            logging.error(f"Error updating manual property {property_id}: {e}")
            return {'success': False, 'error': str(e)}

    def delete_manual_property(self, property_id: str) -> Dict:
        """Delete a manual off-market property."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
            existing = cursor.fetchone()
            if not existing:
                cursor.close()
                return {'success': False, 'error': 'Property not found'}
                
            if existing.get('source_type') != 'manual':
                cursor.close()
                return {'success': False, 'error': 'Cannot delete scraped listings manually'}
                
            cursor.execute("DELETE FROM properties WHERE id = %s AND source_type = 'manual'", (property_id,))
            cursor.close()
            
            self._cache.pop('locations', None)
            self._cache.pop('property_types', None)
            self._cache.pop('statistics', None)
            
            logging.info(f"Deleted manual property {property_id}")
            return {'success': True}
            
        except Exception as e:
            logging.error(f"Error deleting manual property {property_id}: {e}")
            return {'success': False, 'error': str(e)}

    def add_property_document(self, property_id: str, doc_type: str, file_name: str, file_url: str, user_id: int, notes: str = None) -> Dict:
        """Add a media/document record for a property."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            cursor.execute("SELECT image_filename FROM properties WHERE id = %s", (property_id,))
            prop = cursor.fetchone()
            if not prop:
                cursor.close()
                return {'success': False, 'error': 'Property not found'}
                
            insert_sql = """
                INSERT INTO property_documents (
                    property_id, document_type, file_name, file_url, uploaded_by, uploaded_at, notes
                ) VALUES (%s, %s, %s, %s, %s, now(), %s)
                RETURNING id
            """
            cursor.execute(insert_sql, (property_id, doc_type or 'Image', file_name, file_url, user_id, notes))
            doc_id = cursor.fetchone()['id']
            
            if doc_type == 'Image' or not doc_type or not prop.get('image_filename'):
                cursor.execute("UPDATE properties SET image_filename = %s WHERE id = %s", (file_url, property_id))
                
            cursor.close()
            return {'success': True, 'doc_id': doc_id, 'file_url': file_url, 'file_name': file_name}
            
        except Exception as e:
            logging.error(f"Error adding property document: {e}")
            return {'success': False, 'error': str(e)}

    def get_property_documents(self, property_id: str) -> List[Dict]:
        """Get all uploaded documents/media for a property."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM property_documents WHERE property_id = %s ORDER BY uploaded_at DESC", (property_id,))
            docs = cursor.fetchall()
            cursor.close()
            return [dict(d) for d in docs]
        except Exception as e:
            logging.error(f"Error fetching property documents for {property_id}: {e}")
            return []

    def delete_property_document(self, doc_id: int) -> Dict:
        """Delete a property document record."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM property_documents WHERE id = %s", (doc_id,))
            doc = cursor.fetchone()
            if not doc:
                cursor.close()
                return {'success': False, 'error': 'Document not found'}
                
            cursor.execute("DELETE FROM property_documents WHERE id = %s", (doc_id,))
            cursor.close()
            return {'success': True, 'document': dict(doc)}
        except Exception as e:
            logging.error(f"Error deleting property document {doc_id}: {e}")
            return {'success': False, 'error': str(e)}
