"""The Flask-Login user model and its loader."""

from flask_login import UserMixin

from app.extensions import db_manager, login_manager


class User(UserMixin):
    def __init__(self, id, username, email=None):
        self.id = id
        self.username = username
        self.email = email


@login_manager.user_loader
def load_user(user_id):
    user_data = db_manager.get_user_by_id(int(user_id))
    if user_data:
        return User(id=user_data['id'], username=user_data['username'], email=user_data.get('email'))
    return None
