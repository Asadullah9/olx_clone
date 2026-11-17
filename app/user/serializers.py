"""Serializers for the user API: input validation and output shapes only."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers


def normalize_email(value):
    """Emails are treated case-insensitively across the whole API."""
    return value.strip().lower()


class UserSerializer(serializers.ModelSerializer):
    """Public representation of a user. Never exposes password or permission flags."""

    class Meta:
        model = get_user_model()
        fields = ['id', 'email', 'name', 'date_joined']
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
        trim_whitespace=False,
    )

    class Meta:
        model = get_user_model()
        fields = ['email', 'name', 'password']
        extra_kwargs = {
            # Uniqueness is checked case-insensitively in validate_email instead.
            'email': {'validators': []},
            'name': {'required': True, 'allow_blank': False},
        }

    def validate_email(self, value):
        email = normalize_email(value)
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return email

    def validate(self, attrs):
        # Run Django's AUTH_PASSWORD_VALIDATORS against an unsaved user so the
        # similarity validator can compare the password with email/name.
        candidate = get_user_model()(email=attrs.get('email'), name=attrs.get('name', ''))
        try:
            validate_password(attrs['password'], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(style={'input_type': 'password'}, trim_whitespace=False)

    def validate_email(self, value):
        return normalize_email(value)


class TokenResponseSerializer(serializers.Serializer):
    """Documents the login response for the OpenAPI schema."""

    token = serializers.CharField()
    user = UserSerializer()


class DeleteAccountSerializer(serializers.Serializer):
    password = serializers.CharField(
        style={'input_type': 'password'},
        trim_whitespace=False,
        help_text='Current password, required to confirm account deletion.',
    )
