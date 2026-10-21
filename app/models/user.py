"""The Flask-Login user model and its loader."""

from flask_login import UserMixin

from app.extensions import db_manager, login_manager


class User(UserMixin):
    def __init__(
        self,
        id,
        username,
        email=None,
        role="sub_admin",
        can_view_scrapers=True,
        can_view_reports=True,
        can_manage_users=False,
        is_active=True,
    ):
        self.id = id
        self.username = username
        self.email = email
        self.role = role or "sub_admin"
        self.can_view_scrapers = bool(can_view_scrapers)
        self.can_view_reports = bool(can_view_reports)
        self.can_manage_users = bool(can_manage_users)
        self._is_active = bool(is_active)

    @property
    def is_active(self) -> bool:
        """Flask-Login check: inactive users cannot log in."""
        return self._is_active

    @property
    def is_admin(self) -> bool:
        """Check if user has super_admin/admin role or user management permissions."""
        return self.role in ("super_admin", "admin") or self.can_manage_users

    @property
    def can_access_scrapers(self) -> bool:
        """Admins have universal access; otherwise check specific scraper permission."""
        return self.is_admin or self.can_view_scrapers

    @property
    def can_access_reports(self) -> bool:
        """Admins have universal access; otherwise check specific reports permission."""
        return self.is_admin or self.can_view_reports

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "is_admin": self.is_admin,
            "can_view_scrapers": self.can_view_scrapers,
            "can_view_reports": self.can_view_reports,
            "can_manage_users": self.can_manage_users,
        }


@login_manager.user_loader
def load_user(user_id):
    user_data = db_manager.get_user_by_id(int(user_id))
    if user_data:
        return User(
            id=user_data["id"],
            username=user_data["username"],
            email=user_data.get("email"),
            role=user_data.get("role", "sub_admin"),
            can_view_scrapers=user_data.get("can_view_scrapers", True),
            can_view_reports=user_data.get("can_view_reports", True),
            can_manage_users=user_data.get("can_manage_users", False),
            is_active=user_data.get("is_active", True),
        )
    return None
