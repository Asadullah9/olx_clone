"""Tests for the category API."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Category

CATEGORIES_URL = reverse('category:category-list')


def create_category(name, parent=None, slug=None):
    return Category.objects.create(name=name, parent=parent, slug=slug or name.lower())


class PublicCategoryApiTests(TestCase):

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_list_is_public_and_nested(self):
        electronics = create_category('Electronics')
        phones = create_category('Mobile Phones', electronics, 'mobile-phones')
        create_category('Android', phones)
        create_category('Laptops', electronics)
        create_category('Cars')

        with self.assertNumQueries(1):
            res = self.client.get(CATEGORIES_URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Only top-level categories at the root, sorted by name.
        self.assertEqual([c['name'] for c in res.data], ['Cars', 'Electronics'])
        self.assertEqual(res.data[0]['children'], [])
        elec = res.data[1]
        self.assertEqual(set(elec), {'id', 'name', 'slug', 'children'})
        self.assertEqual([c['name'] for c in elec['children']], ['Laptops', 'Mobile Phones'])
        android = elec['children'][1]['children']
        self.assertEqual([c['name'] for c in android], ['Android'])
        self.assertEqual(android[0]['children'], [])

    def test_list_empty(self):
        res = self.client.get(CATEGORIES_URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, [])

    def test_create_requires_authentication(self):
        res = self.client.post(CATEGORIES_URL, {'name': 'Electronics'})

        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(res.data['error']['code'], 'not_authenticated')
        self.assertFalse(Category.objects.exists())


class NonStaffCategoryApiTests(TestCase):

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        user = get_user_model().objects.create_user('user@example.com', 'pass12345')
        self.client.force_authenticate(user)

    def test_create_forbidden_for_non_staff(self):
        res = self.client.post(CATEGORIES_URL, {'name': 'Electronics'})

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data['error']['code'], 'permission_denied')
        self.assertFalse(Category.objects.exists())

    def test_list_allowed_for_non_staff(self):
        res = self.client.get(CATEGORIES_URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)


class StaffCategoryApiTests(TestCase):

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        staff = get_user_model().objects.create_user(
            'staff@example.com', 'pass12345', is_staff=True,
        )
        self.client.force_authenticate(staff)

    def test_create_top_level_category(self):
        res = self.client.post(CATEGORIES_URL, {'name': 'Electronics', 'slug': 'electronics'})

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['name'], 'Electronics')
        self.assertEqual(res.data['slug'], 'electronics')
        self.assertIsNone(res.data['parent'])
        self.assertTrue(Category.objects.filter(slug='electronics', parent=None).exists())

    def test_create_subcategory(self):
        parent = create_category('Electronics')
        res = self.client.post(CATEGORIES_URL, {'name': 'Mobile Phones', 'parent': parent.id})

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['parent'], parent.id)
        self.assertEqual(Category.objects.get(id=res.data['id']).parent, parent)

    def test_slug_generated_and_made_unique(self):
        phones = create_category('Phones')
        create_category('Accessories', slug='accessories')

        res = self.client.post(CATEGORIES_URL, {'name': 'Accessories', 'parent': phones.id})

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['slug'], 'accessories-2')

    def test_duplicate_slug_rejected(self):
        create_category('Electronics', slug='electronics')
        res = self.client.post(CATEGORIES_URL, {'name': 'Other', 'slug': 'electronics'})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('slug', res.data['error']['details'])

    def test_duplicate_top_level_name_rejected(self):
        create_category('Electronics')
        res = self.client.post(CATEGORIES_URL, {'name': 'electronics'})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', res.data['error']['details'])
        self.assertEqual(Category.objects.count(), 1)

    def test_duplicate_name_under_same_parent_rejected(self):
        parent = create_category('Electronics')
        create_category('Laptops', parent)
        res = self.client.post(CATEGORIES_URL, {'name': 'Laptops', 'parent': parent.id})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_parent_rejected(self):
        res = self.client.post(CATEGORIES_URL, {'name': 'Orphan', 'parent': 9999})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent', res.data['error']['details'])

    def test_missing_name_rejected(self):
        res = self.client.post(CATEGORIES_URL, {})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', res.data['error']['details'])
