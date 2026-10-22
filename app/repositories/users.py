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

PROTECTED_SUPERADMIN_EMAILS = {
    'expowebdeveloper@gmail.com',
    'sardorealestate@gmail.com',
}

PROTECTED_SUPERADMIN_USERNAMES = {
    'expoweb',
    'sardorealestate',
    'sardorealestate@gmail.com',
}

CAN_DELETE_USERS_IDENTIFIERS = {
    'expoweb',
    'expowebdeveloper@gmail.com',
    'sardorealestate',
    'sardorealestate@gmail.com',
}


def is_protected_superadmin(user_info) -> bool:
    """Check if a user dict, object, email, or username represents an immutable root superadmin."""
    if not user_info:
        return False
    if isinstance(user_info, dict):
        email = (user_info.get('email') or '').strip().lower()
        username = (user_info.get('username') or '').strip().lower()
    elif hasattr(user_info, 'email') or hasattr(user_info, 'username'):
        email = (getattr(user_info, 'email', '') or '').strip().lower()
        username = (getattr(user_info, 'username', '') or '').strip().lower()
    else:
        s = str(user_info).strip().lower()
        return s in PROTECTED_SUPERADMIN_EMAILS or s in PROTECTED_SUPERADMIN_USERNAMES
    return email in PROTECTED_SUPERADMIN_EMAILS or username in PROTECTED_SUPERADMIN_USERNAMES


def can_delete_users(user_info) -> bool:
    """Check if the user has permission to delete users.
    Strictly limited to Expoweb and Sardo Real Estate Super Admins.
    """
    if not user_info:
        return False
    if isinstance(user_info, dict):
        email = (user_info.get('email') or '').strip().lower()
        username = (user_info.get('username') or '').strip().lower()
        role = (user_info.get('role') or '').strip().lower()
    elif hasattr(user_info, 'email') or hasattr(user_info, 'username'):
        email = (getattr(user_info, 'email', '') or '').strip().lower()
        username = (getattr(user_info, 'username', '') or '').strip().lower()
        role = (getattr(user_info, 'role', '') or '').strip().lower()
    else:
        s = str(user_info).strip().lower()
        return s in CAN_DELETE_USERS_IDENTIFIERS

    if role != 'super_admin':
        return False

    return email in CAN_DELETE_USERS_IDENTIFIERS or username in CAN_DELETE_USERS_IDENTIFIERS


class UsersMixin:
    """User accounts, passwords, OTP and TOTP/MFA state."""

    
    def create_user(
        self,
        email: str,
        username: str,
        password_hash: str,
        role: str = 'user',
        can_view_scrapers: bool = True,
        can_view_reports: bool = True,
        can_manage_users: bool = False,
        two_factor_enabled: bool = False,
        is_active: bool = True,
        must_change_password: bool = False
    ) -> bool:
        """Create a new user with role and permission configurations."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT INTO users (
                    email, username, password_hash, role,
                    can_view_scrapers, can_view_reports, can_manage_users,
                    two_factor_enabled, mfa_enabled, is_active, must_change_password
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                email, username, password_hash, role,
                can_view_scrapers, can_view_reports, can_manage_users,
                two_factor_enabled, False, is_active, must_change_password
            ))
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
                if not user:
                    return None
                u_dict = dict(user)
                if is_protected_superadmin(u_dict):
                    u_dict['role'] = 'super_admin'
                    u_dict['is_active'] = True
                    u_dict['can_view_scrapers'] = True
                    u_dict['can_view_reports'] = True
                    u_dict['can_manage_users'] = True
                return u_dict
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
                ADD COLUMN IF NOT EXISTS trusted_devices JSONB DEFAULT '[]'::jsonb,
                ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'user',
                ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS can_view_scrapers BOOLEAN DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS can_view_reports BOOLEAN DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS can_manage_users BOOLEAN DEFAULT FALSE;
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
            """, (user_id, fingerprint, browser, os_info))
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

    def update_user_password(self, user_id: int, new_password_hash: str, must_change_password: Optional[bool] = None) -> bool:
        """Update a user's password hash, optionally setting must_change_password flag."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            if must_change_password is not None:
                cursor.execute("""
                    UPDATE users
                    SET password_hash = %s, must_change_password = %s
                    WHERE id = %s
                """, (new_password_hash, must_change_password, user_id))
            else:
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

    def get_all_users(self) -> list:
        """Fetch all users without exposing password hashes."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT id, username, email, role, is_active,
                       can_view_scrapers, can_view_reports, can_manage_users,
                       two_factor_enabled, mfa_enabled, last_login, created_at
                FROM users
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            cursor.close()
            if not rows:
                return []
            result = []
            for r in rows:
                u_dict = dict(r)
                if is_protected_superadmin(u_dict):
                    u_dict['role'] = 'super_admin'
                    u_dict['is_active'] = True
                    u_dict['can_view_scrapers'] = True
                    u_dict['can_view_reports'] = True
                    u_dict['can_manage_users'] = True
                result.append(u_dict)
            return result
        except Exception as e:
            logging.error(f"Error fetching all users: {e}")
            return []

    def update_user_permissions(
        self,
        user_id: int,
        role: str,
        can_view_scrapers: bool,
        can_view_reports: bool,
        can_manage_users: bool
    ) -> bool:
        """Update role and permissions for a user."""
        target = self.get_user_by_id(user_id)
        if target and is_protected_superadmin(target):
            role = 'super_admin'
            can_view_scrapers = True
            can_view_reports = True
            can_manage_users = True
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE users
                SET role = %s,
                    can_view_scrapers = %s,
                    can_view_reports = %s,
                    can_manage_users = %s
                WHERE id = %s
            """, (role, can_view_scrapers, can_view_reports, can_manage_users, user_id))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error updating user permissions: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def delete_user(self, user_id: int) -> bool:
        """Delete a user account and completely purge all login records and user details."""
        target = self.get_user_by_id(user_id)
        if target and is_protected_superadmin(target):
            logging.warning(f"Prevented deletion of protected super admin user {user_id} ({target.get('username')})")
            return False
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            target_username = target.get('username') if target else None

            # Purge all foreign key and user activity records
            for tbl in ['user_sessions', 'user_otps', 'login_activity', 'trusted_devices', 'device_logins', 'location_logins', 'password_requests']:
                try:
                    cursor.execute(f"DELETE FROM {tbl} WHERE user_id = %s", (user_id,))
                except Exception as e:
                    logging.warning(f"Cleanup {tbl} by user_id {user_id}: {e}")

            # Also purge login_activity by username if logged without user_id
            if target_username:
                try:
                    cursor.execute("DELETE FROM login_activity WHERE username = %s", (target_username,))
                except Exception:
                    pass
                try:
                    cursor.execute("UPDATE manual_duplicate_links SET created_by = NULL WHERE created_by = %s", (target_username,))
                except Exception:
                    pass

            # Finally delete the user record
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error deleting user {user_id}: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def set_user_active_status(self, user_id: int, is_active: bool) -> bool:
        """Activate or deactivate a user account."""
        if not is_active:
            target = self.get_user_by_id(user_id)
            if target and is_protected_superadmin(target):
                logging.warning(f"Prevented deactivation of protected super admin user {user_id} ({target.get('username')})")
                return False
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("UPDATE users SET is_active = %s WHERE id = %s", (is_active, user_id))
            if not is_active:
                cursor.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error changing user active status: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def get_user_login_history(self, user_id: int, limit: int = 50) -> list:
        """Fetch login activity history for a specific user."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT id, user_id, username, ip_address, country, user_agent, event_type, created_at
                FROM login_activity
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (user_id, limit))
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows] if rows else []
        except Exception as e:
            logging.error(f"Error fetching user login history: {e}")
            return []

    def get_password_requests(self) -> list:
        """Fetch all password reset requests."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT pr.id, pr.user_id, pr.email, pr.status, pr.created_at, pr.resolved_at, pr.temp_password,
                       u.username
                FROM password_requests pr
                LEFT JOIN users u ON u.id = pr.user_id
                ORDER BY pr.created_at DESC
            """)
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows] if rows else []
        except Exception as e:
            logging.error(f"Error fetching password requests: {e}")
            return []

    def create_password_request(self, email: str, user_id = None) -> bool:
        """Create a new password request record."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT INTO password_requests (email, user_id, status)
                VALUES (%s, %s, 'waiting')
            """, (email, user_id))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error creating password request: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def resolve_password_request(self, request_id: int, temp_password = None) -> bool:
        """Mark a password request as done."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE password_requests
                SET status = 'done', resolved_at = CURRENT_TIMESTAMP, temp_password = %s
                WHERE id = %s
            """, (temp_password, request_id))
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error resolving password request: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False

    def get_all_roles(self) -> list:
        """Fetch all roles (system built-in and custom) with active user counts."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT cr.*,
                       COALESCE(u_counts.user_count, 0) AS user_count
                FROM custom_roles cr
                LEFT JOIN (
                    SELECT role, COUNT(*) AS user_count
                    FROM users
                    GROUP BY role
                ) u_counts ON u_counts.role = cr.role_key
                ORDER BY cr.id ASC
            """)
            rows = cursor.fetchall()
            cursor.close()
            system_fallback = [
                {'id': 1, 'name': 'Super admin', 'role_key': 'super_admin', 'description': 'Full permissions across all modules. Cannot be changed or deleted.', 'is_system': True, 'can_view_dashboard': True, 'can_view_reports': True, 'can_export_reports': True, 'can_view_scrapers': True, 'can_run_scrapers': True, 'can_manage_users': True, 'can_manage_settings': True, 'user_count': 0},
                {'id': 2, 'name': 'Sub-Admin', 'role_key': 'sub_admin', 'description': 'Works scraper pipelines & live monitors. Sub-menus (/reports, /login-history) and data exports are restricted to Super Admin.', 'is_system': True, 'can_view_dashboard': True, 'can_view_reports': False, 'can_export_reports': False, 'can_view_scrapers': True, 'can_run_scrapers': True, 'can_manage_users': False, 'can_manage_settings': False, 'user_count': 0},
                {'id': 3, 'name': 'Restricted User', 'role_key': 'restricted_user', 'description': 'Restricted access to: read reports & filters, market intelligence, manual tags (no bulk upload), off-market properties, and duplicate marking. Sub-menus (/reports, /login-history) and exports are excluded.', 'is_system': True, 'can_view_dashboard': True, 'can_view_reports': False, 'can_export_reports': False, 'can_view_scrapers': False, 'can_run_scrapers': False, 'can_manage_users': False, 'can_manage_settings': False, 'user_count': 0}
            ]
            if not rows:
                return system_fallback
            result = [dict(r) for r in rows]
            existing_keys = {r.get('role_key') for r in result}
            for sf in system_fallback:
                if sf['role_key'] not in existing_keys:
                    result.append(sf)
            return result
        except Exception as e:
            logging.error(f"Error fetching roles: {e}")
            return [
                {'id': 1, 'name': 'Super admin', 'role_key': 'super_admin', 'description': 'Full permissions across all modules. Cannot be changed or deleted.', 'is_system': True, 'can_view_dashboard': True, 'can_view_reports': True, 'can_export_reports': True, 'can_view_scrapers': True, 'can_run_scrapers': True, 'can_manage_users': True, 'can_manage_settings': True, 'user_count': 0},
                {'id': 2, 'name': 'Sub-Admin', 'role_key': 'sub_admin', 'description': 'Works scraper pipelines & live monitors. Sub-menus (/reports, /login-history) and data exports are restricted to Super Admin.', 'is_system': True, 'can_view_dashboard': True, 'can_view_reports': False, 'can_export_reports': False, 'can_view_scrapers': True, 'can_run_scrapers': True, 'can_manage_users': False, 'can_manage_settings': False, 'user_count': 0},
                {'id': 3, 'name': 'Restricted User', 'role_key': 'restricted_user', 'description': 'Restricted access to: read reports & filters, market intelligence, manual tags (no bulk upload), off-market properties, and duplicate marking. Sub-menus (/reports, /login-history) and exports are excluded.', 'is_system': True, 'can_view_dashboard': True, 'can_view_reports': False, 'can_export_reports': False, 'can_view_scrapers': False, 'can_run_scrapers': False, 'can_manage_users': False, 'can_manage_settings': False, 'user_count': 0}
            ]

    def create_custom_role(self, name: str, description: str, permissions: dict) -> Optional[dict]:
        """Create a new custom role with specified permissions."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return None
        import re
        role_key = re.sub(r'[^a-z0-9_]+', '_', name.strip().lower()).strip('_')
        if not role_key:
            return None
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                INSERT INTO custom_roles (
                    name, role_key, description, is_system,
                    can_view_dashboard, can_view_reports, can_export_reports,
                    can_view_scrapers, can_run_scrapers, can_manage_users, can_manage_settings
                ) VALUES (%s, %s, %s, FALSE, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *;
            """, (
                name.strip(),
                role_key,
                (description or '').strip(),
                bool(permissions.get('can_view_dashboard', True)),
                bool(permissions.get('can_view_reports', False)),
                bool(permissions.get('can_export_reports', False)),
                bool(permissions.get('can_view_scrapers', False)),
                bool(permissions.get('can_run_scrapers', False)),
                bool(permissions.get('can_manage_users', False)),
                bool(permissions.get('can_manage_settings', False))
            ))
            row = cursor.fetchone()
            self.connection.commit()
            cursor.close()
            return dict(row) if row else None
        except Exception as e:
            logging.error(f"Error creating custom role: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return None

    def delete_custom_role(self, role_id: int) -> tuple:
        """Delete a custom role. Automatically deactivates all users assigned to it."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False, "Database connection failed."
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM custom_roles WHERE id = %s", (role_id,))
            role = cursor.fetchone()
            if not role:
                cursor.close()
                return False, "Role not found."
            if role['is_system']:
                cursor.close()
                return False, "Built-in system roles cannot be deleted."

            role_key = role['role_key']

            # Deactivate all users assigned to this deleted role and clear their permissions
            cursor.execute("""
                UPDATE users
                SET is_active = FALSE,
                    can_view_scrapers = FALSE,
                    can_view_reports = FALSE,
                    can_manage_users = FALSE
                WHERE role = %s
            """, (role_key,))

            # Invalidate all active sessions for those users
            cursor.execute("""
                DELETE FROM user_sessions
                WHERE user_id IN (SELECT id FROM users WHERE role = %s)
            """, (role_key,))

            # Delete the role
            cursor.execute("DELETE FROM custom_roles WHERE id = %s", (role_id,))
            self.connection.commit()
            cursor.close()
            return True, f"Role '{role['name']}' deleted successfully. Assigned users have been deactivated."
        except Exception as e:
            logging.error(f"Error deleting custom role: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return False, str(e)
