"""Tests for the user authentication and management API."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

REGISTER_URL = reverse('user:register')
TOKEN_URL = reverse('user:token')
ME_URL = reverse('user:me')

PASSWORD = 'Str0ng-pass-phrase!'


def create_user(email='user@example.com', password=PASSWORD, name='Test User', **extra):
    return get_user_model().objects.create_user(
        email=email, password=password, name=name, **extra,
    )


class BaseAPITestCase(TestCase):
    def setUp(self):
        cache.clear()  # reset throttle counters between tests
        self.client = APIClient()

    def assertErrorShape(self, res, code=None):
        self.assertIn('error', res.data)
        self.assertEqual(set(res.data['error']), {'code', 'message', 'details'})
        if code:
            self.assertEqual(res.data['error']['code'], code)


class RegisterApiTests(BaseAPITestCase):

    def test_register_success(self):
        payload = {'email': 'New@Example.com', 'password': PASSWORD, 'name': 'New User'}
        res = self.client.post(REGISTER_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['email'], 'new@example.com')
        self.assertNotIn('password', res.data)
        user = get_user_model().objects.get(email='new@example.com')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotEqual(user.password, PASSWORD)

    def test_register_duplicate_email_case_insensitive(self):
        create_user(email='taken@example.com')
        payload = {'email': 'TAKEN@example.com', 'password': PASSWORD, 'name': 'X'}
        res = self.client.post(REGISTER_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertErrorShape(res, 'validation_error')
        self.assertIn('email', res.data['error']['details'])
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_register_weak_password_rejected(self):
        payload = {'email': 'weak@example.com', 'password': '123', 'name': 'Weak'}
        res = self.client.post(REGISTER_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', res.data['error']['details'])
        self.assertFalse(get_user_model().objects.filter(email='weak@example.com').exists())

    def test_register_missing_fields(self):
        res = self.client.post(REGISTER_URL, {})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            set(res.data['error']['details']), {'email', 'password', 'name'},
        )

    def test_register_cannot_set_staff_flags(self):
        payload = {
            'email': 'sneaky@example.com', 'password': PASSWORD, 'name': 'S',
            'is_staff': True, 'is_superuser': True,
        }
        res = self.client.post(REGISTER_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        user = get_user_model().objects.get(email='sneaky@example.com')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)


class TokenApiTests(BaseAPITestCase):

    def test_login_returns_token_and_user(self):
        user = create_user()
        res = self.client.post(TOKEN_URL, {'email': 'USER@example.com', 'password': PASSWORD})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['token'], Token.objects.get(user=user).key)
        self.assertEqual(res.data['user']['email'], user.email)
        self.assertNotIn('password', res.data['user'])

    def test_login_reuses_existing_token(self):
        create_user()
        first = self.client.post(TOKEN_URL, {'email': 'user@example.com', 'password': PASSWORD})
        second = self.client.post(TOKEN_URL, {'email': 'user@example.com', 'password': PASSWORD})
        self.assertEqual(first.data['token'], second.data['token'])

    def test_login_wrong_password(self):
        create_user()
        res = self.client.post(TOKEN_URL, {'email': 'user@example.com', 'password': 'wrong'})

        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertErrorShape(res, 'authentication_failed')
        self.assertNotIn('token', res.data)

    def test_login_unknown_email_same_message(self):
        create_user()
        wrong_pw = self.client.post(TOKEN_URL, {'email': 'user@example.com', 'password': 'x'})
        unknown = self.client.post(TOKEN_URL, {'email': 'nobody@example.com', 'password': 'x'})

        self.assertEqual(unknown.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(unknown.data['error']['message'], wrong_pw.data['error']['message'])

    def test_login_inactive_user_rejected(self):
        create_user(is_active=False)
        res = self.client.post(TOKEN_URL, {'email': 'user@example.com', 'password': PASSWORD})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_blank_fields(self):
        res = self.client.post(TOKEN_URL, {'email': '', 'password': ''})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertErrorShape(res, 'validation_error')

    def test_login_is_throttled(self):
        payload = {'email': 'user@example.com', 'password': 'wrong'}
        for _ in range(5):
            self.client.post(TOKEN_URL, payload)
        res = self.client.post(TOKEN_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertErrorShape(res, 'throttled')


class PublicManageUserApiTests(BaseAPITestCase):

    def test_get_me_requires_auth(self):
        res = self.client.get(ME_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertErrorShape(res, 'not_authenticated')

    def test_delete_me_requires_auth(self):
        res = self.client.delete(ME_URL, {'password': PASSWORD})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_token_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token not-a-real-token')
        res = self.client.get(ME_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class PrivateManageUserApiTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.user = create_user()
        self.other = create_user(email='other@example.com', name='Other')
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    def test_get_me_returns_own_profile(self):
        res = self.client.get(ME_URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, {
            'id': self.user.id,
            'email': self.user.email,
            'name': self.user.name,
            'date_joined': res.data['date_joined'],
        })

    def test_delete_me_wrong_password(self):
        res = self.client.delete(ME_URL, {'password': 'wrong'})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', res.data['error']['details'])
        self.assertTrue(get_user_model().objects.filter(id=self.user.id).exists())

    def test_delete_me_missing_password(self):
        res = self.client.delete(ME_URL)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(get_user_model().objects.filter(id=self.user.id).exists())

    def test_delete_me_success(self):
        res = self.client.delete(ME_URL, {'password': PASSWORD})

        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(get_user_model().objects.filter(id=self.user.id).exists())
        self.assertFalse(Token.objects.filter(key=self.token.key).exists())
        self.assertTrue(get_user_model().objects.filter(id=self.other.id).exists())

        # The old token no longer works.
        self.assertEqual(self.client.get(ME_URL).status_code, status.HTTP_401_UNAUTHORIZED)


class ApiDocsTests(BaseAPITestCase):

    def test_schema_documents_endpoints_and_token_auth(self):
        res = self.client.get(reverse('api-schema'), {'format': 'json'})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        schema = res.json()
        for path in ('/api/user/register/', '/api/user/token/', '/api/user/me/'):
            self.assertIn(path, schema['paths'])
        self.assertIn('tokenAuth', schema['components']['securitySchemes'])

    def test_swagger_ui_available(self):
        res = self.client.get(reverse('api-docs'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
