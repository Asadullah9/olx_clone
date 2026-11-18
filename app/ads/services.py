"""Write-side business logic for ads, independent of the HTTP layer.

Authorization is enforced here (not only in views) so every caller gets the
same rules:

* only the owner or an admin may update or delete an ad;
* owners may deactivate (-> INACTIVE) or resubmit an inactive ad (-> PENDING),
  but never set ACTIVE or REJECTED; only admins moderate;
* an owner who edits the content of an ACTIVE or REJECTED ad sends it back to
  PENDING, so approved content cannot be swapped after moderation.

File handling: new files are written before the DB transaction commits and
deleted again if it fails; removed files are deleted only after commit (see
ads.signals). Either way the database never references a missing file.
"""
from django.conf import settings
from django.db import transaction
from rest_framework import status as http_status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from ads import storage
from ads.selectors import ads_with_relations, get_visible_ad, is_admin
from core.models import Ad, AdImage, AdStatus

CONTENT_FIELDS = ('title', 'description', 'price', 'category')


class InvalidStatusTransition(APIException):
    status_code = http_status.HTTP_400_BAD_REQUEST
    default_detail = 'This status change is not allowed.'
    default_code = 'invalid_status_transition'


def ensure_can_modify(user, ad):
    if not (is_admin(user) or ad.user_id == user.id):
        raise PermissionDenied('You can only modify your own advertisements.')


def _reload(ad_id):
    return ads_with_relations().get(pk=ad_id)


def _store_images(ad_id, files, stored):
    """Save files to storage, appending each name to ``stored`` for cleanup on failure."""
    for file in files:
        stored.append(storage.save_ad_image(ad_id, file))


def create_ad(*, user, title, description, price, category, images):
    """Create a PENDING ad owned by ``user`` with its images in upload order."""
    stored = []
    try:
        with transaction.atomic():
            ad = Ad.objects.create(
                user=user, title=title, description=description, price=price,
                category=category, status=AdStatus.PENDING,
            )
            _store_images(ad.id, images, stored)
            AdImage.objects.bulk_create(
                AdImage(ad=ad, image=name, display_order=i) for i, name in enumerate(stored)
            )
    except Exception:
        storage.delete_files(stored)
        raise
    return _reload(ad.id)


def _apply_status(*, user, ad, data):
    """Validate and apply a requested status change (and rejection reason) to ``ad``."""
    admin = is_admin(user)
    if 'rejection_reason' in data and not admin:
        raise PermissionDenied('Only administrators can set a rejection reason.')

    new_status = data.get('status')
    if new_status is None:
        if admin and 'rejection_reason' in data and ad.status == AdStatus.REJECTED:
            ad.rejection_reason = data['rejection_reason']
        return

    if not admin and new_status != ad.status:
        allowed = new_status == AdStatus.INACTIVE or (
            new_status == AdStatus.PENDING and ad.status == AdStatus.INACTIVE
        )
        if not allowed:
            raise PermissionDenied(
                'You can only deactivate your advertisement (INACTIVE) or resubmit '
                'an inactive one for review (PENDING). Approval and rejection are '
                'done by administrators.'
            )

    ad.status = new_status
    if new_status == AdStatus.REJECTED:
        ad.rejection_reason = data.get('rejection_reason', ad.rejection_reason)
    else:
        ad.rejection_reason = ''


def _plan_images(*, ad, data):
    """Work out the final image list. Returns (kept_images_in_order, removed, new_files).

    Returns None when the request asks for no image change.
    """
    remove_ids = data.get('remove_image_ids') or []
    order = data.get('image_order')
    new_files = data.get('images') or []
    if not remove_ids and order is None and not new_files:
        return None

    existing = list(ad.images.order_by('display_order', 'id'))
    by_id = {img.id: img for img in existing}

    unknown = sorted(set(remove_ids) - by_id.keys())
    if unknown:
        raise ValidationError(
            {'removeImageIds': [f'Images {unknown} do not belong to this advertisement.']}
        )
    removed = [by_id[i] for i in remove_ids]
    kept = [img for img in existing if img.id not in set(remove_ids)]

    if order is not None:
        if sorted(order) != sorted(img.id for img in kept):
            raise ValidationError({'imageOrder': [
                'imageOrder must list every remaining image ID of this advertisement '
                'exactly once.'
            ]})
        kept = [by_id[i] for i in order]

    total = len(kept) + len(new_files)
    low, high = settings.ADS_MIN_IMAGES, settings.ADS_MAX_IMAGES
    if not low <= total <= high:
        raise ValidationError({'images': [
            f'An advertisement must have between {low} and {high} images; '
            f'this update would leave {total}.'
        ]})
    return kept, removed, new_files


def update_ad(*, user, ad_id, data):
    """Partially update an ad. ``data`` is AdUpdateSerializer.validated_data."""
    stored = []
    try:
        with transaction.atomic():
            # Row lock: concurrent image edits cannot push the ad past 5 images.
            ad = get_visible_ad(viewer=user, ad_id=ad_id, for_update=True)
            ensure_can_modify(user, ad)

            content_changed = False
            for field in CONTENT_FIELDS:
                if field in data and getattr(ad, field) != data[field]:
                    setattr(ad, field, data[field])
                    content_changed = True

            _apply_status(user=user, ad=ad, data=data)

            plan = _plan_images(ad=ad, data=data)
            if plan is not None:
                kept, removed, new_files = plan
                content_changed = True
                _store_images(ad.id, new_files, stored)
                # Deleting rows fires ads.signals, which removes files after commit.
                for img in removed:
                    img.delete()
                for position, img in enumerate(kept):
                    img.display_order = position
                AdImage.objects.bulk_update(kept, ['display_order'])
                AdImage.objects.bulk_create(
                    AdImage(ad=ad, image=name, display_order=len(kept) + i)
                    for i, name in enumerate(stored)
                )

            # Judged on the final status, so a no-op "status=ACTIVE" cannot bypass it.
            if (content_changed and not is_admin(user)
                    and ad.status in (AdStatus.ACTIVE, AdStatus.REJECTED)):
                ad.status = AdStatus.PENDING
                ad.rejection_reason = ''

            ad.save()  # always bumps updated_at
    except Exception:
        storage.delete_files(stored)
        raise
    return _reload(ad.id)


@transaction.atomic
def delete_ad(*, user, ad_id):
    """Delete an ad and its image rows; files are removed once the transaction commits."""
    ad = get_visible_ad(viewer=user, ad_id=ad_id, for_update=True)
    ensure_can_modify(user, ad)
    ad.delete()


def _moderate(*, admin, ad_id, new_status, reason=''):
    if not is_admin(admin):
        raise PermissionDenied('Only administrators can moderate advertisements.')
    with transaction.atomic():
        ad = get_visible_ad(viewer=admin, ad_id=ad_id, for_update=True)
        if ad.status != AdStatus.PENDING:
            raise InvalidStatusTransition(
                f'Only PENDING advertisements can be moderated; this one is {ad.status}.'
            )
        ad.status = new_status
        ad.rejection_reason = reason
        ad.save(update_fields=['status', 'rejection_reason', 'updated_at'])
    return _reload(ad.id)


def approve_ad(*, admin, ad_id):
    return _moderate(admin=admin, ad_id=ad_id, new_status=AdStatus.ACTIVE)


def reject_ad(*, admin, ad_id, rejection_reason=''):
    return _moderate(
        admin=admin, ad_id=ad_id, new_status=AdStatus.REJECTED, reason=rejection_reason,
    )
