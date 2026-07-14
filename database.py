import psycopg2
import psycopg2.extras
from typing import List, Dict, Optional, Tuple
import logging
import time
import datetime
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
        
        return self._fetch_user("username = %s OR email = %s",
                                (identifier, identifier), f"by identifier {identifier!r}")

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
        
        try:
            base_query = """
                FROM (
                    SELECT *,
                           'SARDO' || (1099 + ROW_NUMBER() OVER(ORDER BY COALESCE(source, ''), COALESCE(image_filename, ''))) as sardo_reference
                    FROM properties
                ) as p
                WHERE 1=1
            """
            params = []
            
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
            if filters.get('min_beds') is not None:
                # If min_beds is provided, exclude NULL bedrooms and include properties with bedrooms >= min_beds
                base_query += " AND bedrooms >= %s AND bedrooms IS NOT NULL"
                params.append(filters['min_beds'])
            
            if filters.get('max_beds') is not None:
                # If max_beds is provided, exclude NULL bedrooms and include properties with bedrooms <= max_beds
                base_query += " AND bedrooms <= %s AND bedrooms IS NOT NULL"
                params.append(filters['max_beds'])
            
            # Bathrooms filtering with NULL handling
            if filters.get('min_baths') is not None:
                # If min_baths is provided, exclude NULL bathrooms and include properties with bathrooms >= min_baths
                base_query += " AND bathrooms >= %s AND bathrooms IS NOT NULL"
                params.append(filters['min_baths'])
            
            if filters.get('max_baths') is not None:
                # If max_baths is provided, exclude NULL bathrooms and include properties with bathrooms <= max_baths
                base_query += " AND bathrooms <= %s AND bathrooms IS NOT NULL"
                params.append(filters['max_baths'])

            # Property status filtering (canonical SARDO360 statuses only)
            statuses = filters.get('statuses') or filters.get('property_status')
            if statuses:
                if isinstance(statuses, str):
                    statuses = [statuses]
                statuses = [s for s in statuses if s in Config.PROPERTY_STATUSES]
                if statuses:
                    placeholders = ', '.join(['%s'] * len(statuses))
                    base_query += f" AND property_status IN ({placeholders})"
                    params.extend(statuses)

            # Hide delisted stock (opt-in, so existing callers are unaffected)
            if filters.get('exclude_delisted'):
                base_query += " AND property_status <> 'Delisted'"

            # Agent / source filtering (exact match on the raw source value)
            sources = filters.get('sources') or filters.get('source')
            if sources:
                if isinstance(sources, str):
                    sources = [sources]
                sources = [s.strip() for s in sources if s and s.strip()]
                if sources:
                    placeholders = ', '.join(['%s'] * len(sources))
                    base_query += f" AND source IN ({placeholders})"
                    params.extend(sources)

            # Date range: when the listing was first seen by the scraper
            if filters.get('first_seen_from'):
                base_query += " AND first_seen_at >= %s::timestamp"
                params.append(filters['first_seen_from'])
            if filters.get('first_seen_to'):
                # Inclusive of the whole end day
                base_query += " AND first_seen_at < (%s::date + INTERVAL '1 day')"
                params.append(filters['first_seen_to'])

            # Date range: when the status last changed
            if filters.get('status_changed_from'):
                base_query += " AND status_last_changed_at >= %s::timestamp"
                params.append(filters['status_changed_from'])
            if filters.get('status_changed_to'):
                base_query += " AND status_last_changed_at < (%s::date + INTERVAL '1 day')"
                params.append(filters['status_changed_to'])

            # First, get the total count for pagination
            count_query = "SELECT COUNT(*) " + base_query
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(count_query, params)
            total_count_row = cursor.fetchone()
            total_count = list(total_count_row.values())[0] if total_count_row else 0
            
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
                    reference,
                    property_url,
                    property_status,
                    previous_status,
                    first_seen_at,
                    last_seen_at,
                    status_last_changed_at,
                    created_at,
                    updated_at,
                    sardo_reference
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
                'source': 'source',
                'created_at': 'created_at',
                'property_status': 'property_status',
                'first_seen_at': 'first_seen_at',
                'last_seen_at': 'last_seen_at',
                'status_last_changed_at': 'status_last_changed_at'
            }
            
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
            
            # Add pagination
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
            if offset is not None:
                query += " OFFSET %s"
                params.append(offset)
            
            cursor.execute(query, params)
            properties = cursor.fetchall()
            cursor.close()
            
            # Log the search for debugging
            logging.info(f"Search executed with {len(params)} params, found {len(properties)} properties out of {total_count} total")
            
            return {
                'properties': [dict(prop) for prop in properties],
                'total_count': total_count
            }
            
        except Exception as e:
            logging.error(f"Error fetching properties: {e}")
            return {'properties': [], 'total_count': 0}
    
    def get_property_by_id(self, property_id: str) -> Optional[Dict]:
        """Get a specific property by ID"""
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
                    reference,
                    property_url,
                    property_status,
                    previous_status,
                    first_seen_at,
                    last_seen_at,
                    status_last_changed_at,
                    created_at,
                    updated_at
                FROM properties
                WHERE id = %s
            """
            
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(query, (property_id,))
            property_data = cursor.fetchone()
            cursor.close()
            
            return dict(property_data) if property_data else None
            
        except Exception as e:
            logging.error(f"Error fetching property {property_id}: {e}")
            return None
    
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

            cursor.close()
            self._set_cache('statistics', stats)
            return stats

        except Exception as e:
            logging.error(f"Error fetching statistics: {e}")
            return {}

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
