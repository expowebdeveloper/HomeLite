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
        self.ensure_login_activity_table()
        self.ensure_security_columns()
        self.ensure_user_sessions_table()

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
                password=self.config.DB_PASSWORD
            )
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

        if not self.connection:
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

        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
            if not self.connect():
                return None
        
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM users WHERE username = %s OR email = %s", (identifier, identifier))
            user = cursor.fetchone()
            cursor.close()
            return dict(user) if user else None
        except Exception as e:
            logging.error(f"Error fetching user by identifier: {e}")
            return None

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Fetch a user by their ID"""
        if not self.connection:
            if not self.connect():
                return None
        
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            cursor.close()
            return dict(user) if user else None
        except Exception as e:
            logging.error(f"Error fetching user by ID: {e}")
            return None

    def store_otp(self, user_id: int, otp_hash: str, expires_at: float) -> bool:
        """Store a new OTP in the database, clearing any previous active ones."""
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
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
        if not self.connection:
            if not self.connect():
                return {'properties': [], 'total_count': 0}
        
        try:
            base_query = """
                FROM properties 
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
                    created_at,
                    updated_at
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
                'created_at': 'created_at'
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
        if not self.connection:
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

        if not self.connection:
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
            
            cursor.close()
            self._set_cache('statistics', stats)
            return stats
            
        except Exception as e:
            logging.error(f"Error fetching statistics: {e}")
            return {}
