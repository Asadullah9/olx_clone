"""HTTP views for the user API. Thin by design; logic lives in services.py."""
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.serializers import ErrorResponseSerializer
from user import services
from user.serializers import (
    DeleteAccountSerializer,
    LoginSerializer,
    RegisterSerializer,
    TokenResponseSerializer,
    UserSerializer,
)

ERROR_400 = OpenApiResponse(ErrorResponseSerializer, description='Invalid input.')
ERROR_401 = OpenApiResponse(
    ErrorResponseSerializer, description='Missing, invalid or expired credentials.',
)
ERROR_429 = OpenApiResponse(ErrorResponseSerializer, description='Too many requests.')


@extend_schema(tags=['Authentication'])
class RegisterView(generics.CreateAPIView):
    """Create a new user account."""

    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(
        summary='Register a new user',
        responses={201: UserSerializer, 400: ERROR_400},
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.register_user(**serializer.validated_data)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Authentication'])
class LoginView(APIView):
    """Exchange email and password for an auth token."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def get_authenticate_header(self, request):
        # No authentication classes run here (a stale token header must not block
        # login), so supply the scheme ourselves; DRF needs a WWW-Authenticate
        # header to return 401 rather than downgrading to 403.
        return 'Token'

    @extend_schema(
        summary='Log in and obtain an auth token',
        description=(
            'Returns a token to send on later requests as '
            '`Authorization: Token <token>`.'
        ),
        request=LoginSerializer,
        responses={200: TokenResponseSerializer, 400: ERROR_400, 401: ERROR_401, 429: ERROR_429},
        auth=[],
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.authenticate_user(request=request, **serializer.validated_data)
        token = services.get_or_create_token(user)
        return Response({'token': token.key, 'user': UserSerializer(user).data})


@extend_schema(tags=['Users'])
class ManageUserView(generics.RetrieveDestroyAPIView):
    """Retrieve or delete the authenticated user's own account.

    There is no ID in the URL: the object is always request.user, so a user
    can never read or delete someone else's account.
    """

    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

    @extend_schema(
        summary="Get the current user's profile",
        responses={200: UserSerializer, 401: ERROR_401},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Delete the current user's account",
        description='Permanently deletes the account. The current password is required.',
        request=DeleteAccountSerializer,
        responses={
            204: OpenApiResponse(description='Account deleted.'),
            400: ERROR_400,
            401: ERROR_401,
        },
    )
    def delete(self, request, *args, **kwargs):
        serializer = DeleteAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.delete_user(user=request.user, password=serializer.validated_data['password'])
        return Response(status=status.HTTP_204_NO_CONTENT)
