"""Shared fixtures for the ads tests."""
import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from core.models import Ad, AdImage, AdStatus, Category

_CONTENT_TYPES = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp',
                  'GIF': 'image/gif'}


def make_image(name='photo.jpg', fmt='JPEG', size=(8, 8)):
    buf = io.BytesIO()
    Image.new('RGB', size, 'red').save(buf, fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=_CONTENT_TYPES[fmt])


def make_images(count, fmt='JPEG', ext='jpg'):
    return [make_image(f'photo{i}.{ext}', fmt) for i in range(count)]


def create_user(email='owner@example.com', **extra):
    extra.setdefault('name', email.split('@')[0])
    return get_user_model().objects.create_user(email=email, password='Str0ng-pass!', **extra)


def create_category(name='Mobile Phones', parent=None):
    return Category.objects.create(name=name, slug=name.lower().replace(' ', '-'), parent=parent)


def create_ad(user, category, *, images=4, status=AdStatus.ACTIVE, **fields):
    """Insert an ad directly (bypassing the API) with ``images`` stored files."""
    fields.setdefault('title', 'iPhone 15 Pro')
    fields.setdefault('description', 'Great condition, barely used phone.')
    fields.setdefault('price', '950.00')
    ad = Ad.objects.create(user=user, category=category, status=status, **fields)
    for i in range(images):
        name = default_storage.save(f'ads/{ad.id}/seed{i}.jpg', make_image())
        AdImage.objects.create(ad=ad, image=name, display_order=i)
    return ad


class MediaTestCase(TestCase):
    """Writes uploaded files to a throwaway MEDIA_ROOT."""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='ads-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        cache.clear()  # reset throttle counters
        self.client = APIClient()
        self.category = create_category()
        self.owner = create_user('owner@example.com')
        self.other = create_user('other@example.com')
        self.admin = create_user('admin@example.com', is_staff=True)

    def auth(self, user):
        self.client.force_authenticate(user)

    def assertError(self, res, status_code, code=None):
        self.assertEqual(res.status_code, status_code, res.data)
        self.assertFalse(res.data['success'])
        self.assertIsNone(res.data['data'])
        if code:
            self.assertEqual(res.data['error']['code'], code)
