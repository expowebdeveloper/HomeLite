"""Login sessions, trusted devices and the login activity audit trail.

Split out of the original database.DatabaseManager; the method bodies are
unchanged and are recomposed into a single class in __init__.py.
"""

import psycopg2
import psycopg2.extras
import logging
import datetime
from typing import List


class SessionsMixin:
    """Login sessions, trusted devices and the login activity audit trail."""



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
