"""Tests for the custom user model."""
from django.contrib.auth import get_user_model
from django.test import TestCase


class UserModelTests(TestCase):

    def test_create_user_with_email(self):
        user = get_user_model().objects.create_user(
            email='test@example.com', password='testpass123',
        )
        self.assertEqual(user.email, 'test@example.com')
        self.assertTrue(user.check_password('testpass123'))
        self.assertFalse(user.is_staff)

    def test_new_user_email_normalized(self):
        samples = [
            ('test1@EXAMPLE.com', 'test1@example.com'),
            ('Test2@Example.com', 'Test2@example.com'),
            ('TEST3@EXAMPLE.COM', 'TEST3@example.com'),
        ]
        for email, expected in samples:
            user = get_user_model().objects.create_user(email, 'sample123')
            self.assertEqual(user.email, expected)

    def test_new_user_without_email_raises_error(self):
        with self.assertRaises(ValueError):
            get_user_model().objects.create_user('', 'test123')

    def test_create_superuser(self):
        user = get_user_model().objects.create_superuser('admin@example.com', 'test123')
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
