"""Delete stored image files whenever an AdImage row is deleted.

This single hook covers every path: removing images on update, deleting an ad,
cascades from deleting a user, and the Django admin. Files are removed only
after the transaction commits, so a rollback never leaves rows pointing at
missing files.
"""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from ads import storage
from core.models import AdImage


@receiver(post_delete, sender=AdImage, dispatch_uid='ads_delete_image_file')
def delete_image_file(sender, instance, **kwargs):
    name = instance.image.name
    if name:
        transaction.on_commit(lambda: storage.delete_files([name]))
