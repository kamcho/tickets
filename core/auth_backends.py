"""Authenticate with phone (primary) or email + password."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from core.auth_utils import get_user_by_login_identifier

User = get_user_model()


class EmailOrPhoneBackend(ModelBackend):
    """
    Django authenticate(username=...) accepts phone or email.

    Phone is tried first when the value is not email-shaped.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD) or kwargs.get('phone')
        if not username or password is None:
            return None

        user = get_user_by_login_identifier(username)
        if user is None:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
