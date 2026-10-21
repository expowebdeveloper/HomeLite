from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any

@dataclass
class User:
    """Updated User model for the new authentication system."""
    id: int
    username: str
    password_hash: str
    created_at: datetime
    email: Optional[str] = None
    two_factor_enabled: bool = False
    mfa_enabled: bool = False
    google_auth_secret: Optional[str] = None
    backup_codes: Optional[List[str]] = field(default_factory=list)
    last_login: Optional[datetime] = None
    last_login_ip: Optional[str] = None
    last_login_device: Optional[str] = None
    role: str = 'user'
    can_view_scrapers: bool = True
    can_view_reports: bool = True
    can_manage_users: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role in ('super_admin', 'admin') or self.can_manage_users

    @property
    def can_access_scrapers(self) -> bool:
        return self.is_admin or self.can_view_scrapers

    @property
    def can_access_reports(self) -> bool:
        return self.is_admin or self.can_view_reports
    
    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> 'User':
        return cls(
            id=row.get('id'),
            username=row.get('username'),
            password_hash=row.get('password_hash'),
            created_at=row.get('created_at'),
            email=row.get('email'),
            two_factor_enabled=row.get('two_factor_enabled', False),
            mfa_enabled=row.get('mfa_enabled', False),
            google_auth_secret=row.get('google_auth_secret'),
            backup_codes=row.get('backup_codes', []),
            last_login=row.get('last_login'),
            last_login_ip=row.get('last_login_ip'),
            last_login_device=row.get('last_login_device'),
            role=row.get('role', 'user'),
            can_view_scrapers=row.get('can_view_scrapers', True),
            can_view_reports=row.get('can_view_reports', True),
            can_manage_users=row.get('can_manage_users', False)
        )

@dataclass
class LoginActivity:
    """Model for tracking user login activity."""
    id: int
    user_id: int
    username: str
    ip_address: str
    country: str
    user_agent: str
    event_type: str
    created_at: datetime

@dataclass
class UserSession:
    """Model for managing user sessions securely."""
    id: int
    user_id: int
    session_token: str
    expires_at: datetime
    ip_address: str
    user_agent: str
    created_at: datetime
    last_active: datetime

@dataclass
class TrustedDevice:
    """Model for managing trusted devices (e.g. for "remember me" functionality)."""
    id: int
    user_id: int
    device_id: str
    device_name: str
    ip_address: str
    user_agent: str
    expires_at: datetime
    created_at: datetime
    last_used: datetime

@dataclass
class UserOTP:
    """Model for tracking OTPs securely in the database."""
    id: int
    user_id: int
    otp_hash: str
    expires_at: datetime
    attempts: int
    created_at: datetime
