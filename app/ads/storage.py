"""Ad image storage, built on Django's storage API (filesystem, S3, ...).

The database keeps only the storage name (e.g. ``ads/42/<uuid>.jpg``); URLs are
resolved through the configured storage backend when serializing.
"""
import logging
import uuid

from django.core.files.storage import default_storage
from rest_framework import status
from rest_framework.exceptions import APIException

from ads.validators import image_extension

logger = logging.getLogger(__name__)


class ImageStorageError(APIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = 'The images could not be stored. Please try again.'
    default_code = 'image_storage_error'


def save_ad_image(ad_id, file):
    """Persist one validated upload under a random name; return its storage name."""
    name = f'ads/{ad_id}/{uuid.uuid4().hex}.{image_extension(file)}'
    try:
        file.seek(0)
        return default_storage.save(name, file)
    except Exception as exc:
        logger.exception('Failed to store image for ad %s', ad_id)
        raise ImageStorageError() from exc


def delete_files(names):
    """Best-effort removal. A failure is logged, never raised: the DB is the source of truth."""
    for name in names:
        if not name:
            continue
        try:
            default_storage.delete(name)
        except Exception:
            logger.exception('Failed to delete stored image %s', name)
