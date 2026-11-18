"""Validation for uploaded ad images."""
import os

from django.conf import settings
from rest_framework import serializers

# Pillow format name -> canonical file extension used when storing the file.
ALLOWED_IMAGE_FORMATS = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}


def validate_ad_image(file):
    """Check the extension, the size and the real (decoded) image format.

    DRF's ImageField has already opened the file with Pillow and attached the
    result as ``file.image``, so a renamed non-image is rejected before this
    runs; here we restrict it to the formats ads accept.
    """
    ext = os.path.splitext(file.name or '')[1].lower().lstrip('.')
    allowed = settings.ADS_ALLOWED_IMAGE_EXTENSIONS
    if ext not in allowed:
        raise serializers.ValidationError(
            f'Unsupported file extension ".{ext}". Allowed: {", ".join(allowed)}.'
        )

    max_size = settings.ADS_MAX_IMAGE_SIZE
    if file.size > max_size:
        raise serializers.ValidationError(
            f'Image "{file.name}" is larger than {max_size // (1024 * 1024)} MB.'
        )

    image = getattr(file, 'image', None)
    if image is None or image.format not in ALLOWED_IMAGE_FORMATS:
        raise serializers.ValidationError(
            f'"{file.name}" is not a valid JPEG, PNG or WebP image.'
        )
    return file


def image_extension(file):
    """Extension derived from the decoded format, never from the client's filename."""
    return ALLOWED_IMAGE_FORMATS[file.image.format]
