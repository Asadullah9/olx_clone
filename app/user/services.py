"""Business logic for user accounts, kept independent of the HTTP layer."""
from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from rest_framework import exceptions
from rest_framework.authtoken.models import Token


def register_user(*, email, password, **extra_fields):
    """Create a user. The manager hashes the password via set_password()."""
    return get_user_model().objects.create_user(email=email, password=password, **extra_fields)


def authenticate_user(*, request, email, password):
    """Return the active user for these credentials, or raise AuthenticationFailed.

    The same generic message is used for unknown emails, wrong passwords and
    inactive accounts so the endpoint cannot be used to discover accounts.
    """
    user = authenticate(request=request, email=email, password=password)
    if user is None or not user.is_active:
        raise exceptions.AuthenticationFailed('Invalid email or password.')
    return user


def get_or_create_token(user):
    token, _ = Token.objects.get_or_create(user=user)
    return token


@transaction.atomic
def delete_user(*, user, password):
    """Permanently delete the user after re-checking their password.

    Their auth token is removed by the FK cascade.
    """
    if not user.check_password(password):
        raise exceptions.ValidationError({'password': ['Incorrect password.']})
    user.delete()
