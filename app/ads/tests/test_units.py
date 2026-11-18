"""Unit tests for the building blocks behind the ads API."""
from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase, TestCase
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied

from ads import selectors, services
from ads.serializers import AdListQuerySerializer, AdUpdateSerializer
from ads.tests.helpers import MediaTestCase, create_ad, create_category, make_image
from ads.validators import validate_ad_image
from core.models import AdStatus
from core.pagination import Page


class PageMetaTests(SimpleTestCase):

    def test_meta(self):
        meta = Page(items=[], total=25, page=2, limit=10).meta
        self.assertEqual(meta, {
            'total': 25, 'page': 2, 'limit': 10, 'totalPages': 3,
            'hasNextPage': True, 'hasPreviousPage': True,
        })

    def test_empty(self):
        meta = Page(items=[], total=0, page=1, limit=10).meta
        self.assertEqual(meta['totalPages'], 0)
        self.assertFalse(meta['hasNextPage'])
        self.assertFalse(meta['hasPreviousPage'])


class ImageValidatorTests(SimpleTestCase):

    def _validated(self, file):
        # Run DRF's ImageField first, as the serializer does, to attach file.image.
        return validate_ad_image(serializers.ImageField().to_internal_value(file))

    def test_accepts_allowed_formats(self):
        for name, fmt in [('a.jpg', 'JPEG'), ('a.jpeg', 'JPEG'), ('a.png', 'PNG'),
                          ('a.webp', 'WEBP')]:
            with self.subTest(name):
                self._validated(make_image(name, fmt))

    def test_rejects_extension_format_mismatch(self):
        # A GIF renamed to .jpg passes the extension check but not the format check.
        with self.assertRaises(serializers.ValidationError):
            self._validated(make_image('sneaky.jpg', 'GIF'))

    def test_rejects_disallowed_extension(self):
        with self.assertRaises(serializers.ValidationError):
            self._validated(make_image('a.gif', 'GIF'))


class QuerySerializerTests(SimpleTestCase):

    def test_defaults(self):
        s = AdListQuerySerializer(data={})
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data, {
            'page': 1, 'limit': 10, 'sortBy': 'createdAt', 'sortOrder': 'DESC',
        })

    def test_case_insensitive_choices(self):
        s = AdListQuerySerializer(data={'status': 'active', 'sortBy': 'PRICE', 'sortOrder': 'asc'})
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data['status'], 'ACTIVE')
        self.assertEqual(s.validated_data['sortBy'], 'price')
        self.assertEqual(s.validated_data['sortOrder'], 'ASC')

    def test_update_rejects_duplicate_image_ids(self):
        s = AdUpdateSerializer(data={'removeImageIds': [1, 1]})
        self.assertFalse(s.is_valid())


class SelectorTests(TestCase):

    def test_category_and_descendant_ids(self):
        root = create_category('Electronics')
        phones = create_category('Phones', parent=root)
        android = create_category('Android', parent=phones)
        create_category('Cars')

        self.assertCountEqual(
            selectors.category_and_descendant_ids(root.id), [root.id, phones.id, android.id],
        )
        self.assertEqual(selectors.category_and_descendant_ids(android.id), [android.id])

    def test_is_admin(self):
        self.assertFalse(selectors.is_admin(AnonymousUser()))
        self.assertFalse(selectors.is_admin(None))


class ServicePermissionTests(MediaTestCase):
    """Rules are enforced in the service layer, independent of the views."""

    def test_update_by_non_owner_denied(self):
        ad = create_ad(self.owner, self.category, images=4)
        with self.assertRaises(PermissionDenied):
            services.update_ad(user=self.other, ad_id=ad.id, data={'title': 'Mine now'})

    def test_hidden_ad_raises_not_found_for_strangers(self):
        ad = create_ad(self.owner, self.category, status=AdStatus.PENDING, images=4)
        with self.assertRaises(NotFound):
            services.delete_ad(user=self.other, ad_id=ad.id)

    def test_moderation_requires_admin(self):
        ad = create_ad(self.owner, self.category, status=AdStatus.PENDING, images=4)
        with self.assertRaises(PermissionDenied):
            services.approve_ad(admin=self.owner, ad_id=ad.id)

    def test_mine_scope_ignores_user_id(self):
        create_ad(self.other, self.category, images=1)
        page = selectors.list_ads(
            viewer=self.owner, scope=selectors.SCOPE_MINE,
            params={'page': 1, 'limit': 10, 'userId': self.other.id,
                    'sortBy': 'createdAt', 'sortOrder': 'DESC'},
        )
        self.assertEqual(page.total, 0)
