"""Serializers for the ads API: request validation (DTOs) and response shapes.

JSON field names follow the ads API contract (camelCase); model fields stay
snake_case and are mapped with ``source=``.
"""
from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ads.validators import validate_ad_image
from core.models import Ad, AdImage, AdStatus, Category

SORT_FIELDS = ['createdAt', 'price', 'title']
SORT_ORDERS = ['ASC', 'DESC']


class _UpperChoiceField(serializers.ChoiceField):
    """Choice field matched case-insensitively."""

    def to_internal_value(self, data):
        if isinstance(data, str):
            data = data.strip().upper()
        return super().to_internal_value(data)


# --- Output -----------------------------------------------------------------

class CategoryBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description']
        read_only_fields = fields


class CreatorSerializer(serializers.Serializer):
    """Public view of the ad's author. Never includes the email address."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class AdminCreatorSerializer(CreatorSerializer):
    email = serializers.EmailField(read_only=True)


class AdImageSerializer(serializers.ModelSerializer):
    imageUrl = serializers.SerializerMethodField()
    displayOrder = serializers.IntegerField(source='display_order', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = AdImage
        fields = ['id', 'imageUrl', 'displayOrder', 'createdAt']
        read_only_fields = fields

    @extend_schema_field(serializers.URLField())
    def get_imageUrl(self, obj):
        url = obj.image.url
        request = self.context.get('request')
        # build_absolute_uri leaves already-absolute URLs (S3, CDN) untouched.
        return request.build_absolute_uri(url) if request else url


class AdSerializer(serializers.ModelSerializer):
    userId = serializers.IntegerField(source='user_id', read_only=True)
    categoryId = serializers.IntegerField(source='category_id', read_only=True)
    category = CategoryBriefSerializer(read_only=True)
    creator = CreatorSerializer(source='user', read_only=True)
    rejectionReason = serializers.CharField(source='rejection_reason', read_only=True)
    images = AdImageSerializer(many=True, read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = Ad
        fields = [
            'id', 'userId', 'title', 'description', 'price', 'status', 'rejectionReason',
            'categoryId', 'category', 'creator', 'images', 'createdAt', 'updatedAt',
        ]
        read_only_fields = fields


class AdminAdSerializer(AdSerializer):
    """Same as AdSerializer, with the creator's contact details for moderators."""

    creator = AdminCreatorSerializer(source='user', read_only=True)


# --- Input: request bodies ----------------------------------------------------

def _image_field(**kwargs):
    return serializers.ListField(
        child=serializers.ImageField(validators=[validate_ad_image]),
        allow_empty=False,
        **kwargs,
    )


class _AdFieldsMixin(serializers.Serializer):
    def validate_title(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError('Title must be at least 3 characters long.')
        return value

    def validate_description(self, value):
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError('Description must be at least 10 characters long.')
        return value


def _category_field(**kwargs):
    return serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        source='category',
        error_messages={'does_not_exist': 'Category {pk_value} does not exist.'},
        help_text='ID of the category the ad belongs to.',
        **kwargs,
    )


class AdCreateSerializer(_AdFieldsMixin):
    """POST /api/ads (multipart/form-data). userId and status are never accepted."""

    title = serializers.CharField(max_length=150)
    description = serializers.CharField(max_length=5000)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    categoryId = _category_field()
    images = _image_field(
        min_length=settings.ADS_MIN_IMAGES,
        max_length=settings.ADS_MAX_IMAGES,
        help_text=(
            f'{settings.ADS_MIN_IMAGES}-{settings.ADS_MAX_IMAGES} product images '
            '(JPEG, PNG or WebP). Repeat the `images` field once per file; '
            'their order becomes the display order.'
        ),
    )


class AdUpdateSerializer(_AdFieldsMixin):
    """PUT/PATCH /api/ads/:id. Every field is optional; omitted fields are unchanged.

    Images: the final set is the existing images minus ``removeImageIds``
    (optionally re-ordered by ``imageOrder``) followed by the new ``images``.
    Sending no image fields keeps the current images untouched.
    """

    title = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(max_length=5000, required=False)
    price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False,
    )
    categoryId = _category_field(required=False)
    status = _UpperChoiceField(
        choices=AdStatus.choices,
        required=False,
        help_text=(
            'Owners may set INACTIVE (deactivate) or PENDING (resubmit an inactive ad). '
            'Admins may set any status.'
        ),
    )
    rejectionReason = serializers.CharField(
        source='rejection_reason', max_length=500, required=False, allow_blank=True,
        help_text='Admins only. Stored when the status is REJECTED.',
    )
    images = _image_field(
        required=False,
        max_length=settings.ADS_MAX_IMAGES,
        help_text='New images to append (JPEG, PNG or WebP). Repeat the field per file.',
    )
    removeImageIds = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        source='remove_image_ids',
        required=False,
        help_text='IDs of existing images of this ad to delete.',
    )
    imageOrder = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        source='image_order',
        required=False,
        help_text=(
            'IDs of the kept existing images in their new display order. '
            'Must list every kept image exactly once. New uploads follow them.'
        ),
    )

    def validate(self, attrs):
        for key in ('remove_image_ids', 'image_order'):
            ids = attrs.get(key)
            if ids is not None and len(ids) != len(set(ids)):
                raise serializers.ValidationError({key: ['Image IDs must not repeat.']})
        if not attrs:
            raise serializers.ValidationError('Provide at least one field to update.')
        return attrs


class AdRejectSerializer(serializers.Serializer):
    rejectionReason = serializers.CharField(
        source='rejection_reason', max_length=500, required=False, allow_blank=True,
        help_text='Optional explanation shown to the ad owner.',
    )


# --- Input: query parameters --------------------------------------------------

class _CaseInsensitiveSortByField(serializers.ChoiceField):
    def to_internal_value(self, data):
        lookup = {c.lower(): c for c in SORT_FIELDS}
        if isinstance(data, str):
            data = lookup.get(data.strip().lower(), data)
        return super().to_internal_value(data)


class MyAdsQuerySerializer(serializers.Serializer):
    """Query parameters of GET /api/ads/my-ads (no userId: always the caller)."""

    page = serializers.IntegerField(min_value=1, default=1)
    limit = serializers.IntegerField(
        min_value=1, max_value=settings.ADS_MAX_PAGE_SIZE, default=settings.ADS_PAGE_SIZE,
    )
    search = serializers.CharField(
        max_length=100, required=False, allow_blank=True,
        help_text='Case-insensitive partial match on title or description.',
    )
    categoryId = serializers.IntegerField(
        min_value=1, required=False,
        help_text='Filter by category (includes its subcategories).',
    )
    minPrice = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False,
    )
    maxPrice = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False,
    )
    status = _UpperChoiceField(choices=AdStatus.choices, required=False)
    sortBy = _CaseInsensitiveSortByField(choices=SORT_FIELDS, default='createdAt')
    sortOrder = _UpperChoiceField(choices=SORT_ORDERS, default='DESC')

    def validate_categoryId(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError(f'Category {value} does not exist.')
        return value

    def validate(self, attrs):
        low, high = attrs.get('minPrice'), attrs.get('maxPrice')
        if low is not None and high is not None and low > high:
            raise serializers.ValidationError(
                {'minPrice': ['minPrice must be less than or equal to maxPrice.']}
            )
        if 'search' in attrs:
            attrs['search'] = attrs['search'].strip()
        return attrs


class AdListQuerySerializer(MyAdsQuerySerializer):
    """Query parameters of GET /api/ads and GET /api/admin/ads."""

    status = _UpperChoiceField(
        choices=AdStatus.choices, required=False,
        help_text=(
            'Admins only on /api/ads (non-admins may only pass ACTIVE). '
            'Use /api/ads/my-ads to see your own non-active ads.'
        ),
    )
    userId = serializers.IntegerField(
        min_value=1, required=False, help_text='Filter by the ad creator.',
    )
