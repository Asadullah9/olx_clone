"""Tests for the custom user model."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from core.models import Category


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


class CategoryModelTests(TestCase):

    def test_str(self):
        self.assertEqual(str(Category.objects.create(name='Electronics', slug='e')), 'Electronics')

    def test_same_name_allowed_under_different_parents(self):
        phones = Category.objects.create(name='Phones', slug='phones')
        cars = Category.objects.create(name='Cars', slug='cars')
        Category.objects.create(name='Accessories', slug='acc-1', parent=phones)
        Category.objects.create(name='Accessories', slug='acc-2', parent=cars)
        self.assertEqual(Category.objects.filter(name='Accessories').count(), 2)

    def test_duplicate_top_level_name_blocked_by_db(self):
        Category.objects.create(name='Electronics', slug='e1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(name='Electronics', slug='e2')

    def test_duplicate_name_under_same_parent_blocked_by_db(self):
        parent = Category.objects.create(name='Electronics', slug='e')
        Category.objects.create(name='Laptops', slug='l1', parent=parent)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(name='Laptops', slug='l2', parent=parent)

    def test_clean_rejects_cycle(self):
        a = Category.objects.create(name='A', slug='a')
        b = Category.objects.create(name='B', slug='b', parent=a)
        a.parent = b
        with self.assertRaises(ValidationError):
            a.clean()

    def test_clean_rejects_self_parent(self):
        a = Category.objects.create(name='A', slug='a')
        a.parent = a
        with self.assertRaises(ValidationError):
            a.clean()

    def test_deleting_parent_with_children_is_protected(self):
        parent = Category.objects.create(name='Electronics', slug='e')
        Category.objects.create(name='Laptops', slug='l', parent=parent)
        with self.assertRaises(ProtectedError):
            parent.delete()
