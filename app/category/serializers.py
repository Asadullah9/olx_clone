"""Serializers for the category API."""
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.models import Category


class CategorySerializer(serializers.ModelSerializer):
    """Flat representation, used to create a category and in its 201 response."""

    slug = serializers.SlugField(
        max_length=120,
        required=False,
        help_text='Optional. Generated from the name when omitted.',
    )
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        required=False,
        allow_null=True,
        help_text='ID of the parent category. Omit or null for a top-level category.',
    )

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'parent']
        read_only_fields = ['id']
        # Uniqueness is validated explicitly below. DRF's auto validator skips
        # rows whose parent is NULL, so it would miss top-level duplicates.
        validators = []

    def validate_slug(self, value):
        if Category.objects.filter(slug=value).exists():
            raise serializers.ValidationError('A category with this slug already exists.')
        return value

    def validate(self, attrs):
        name = attrs['name'].strip()
        parent = attrs.get('parent')
        if Category.objects.filter(parent=parent, name__iexact=name).exists():
            where = f'under "{parent}"' if parent else 'at the top level'
            raise serializers.ValidationError(
                {'name': [f'A category named "{name}" already exists {where}.']}
            )
        attrs['name'] = name
        return attrs

    def create(self, validated_data):
        if not validated_data.get('slug'):
            validated_data['slug'] = self._unique_slug(validated_data['name'])
        try:
            with transaction.atomic():
                return super().create(validated_data)
        except IntegrityError:
            # A concurrent request won the race for the same slug or name.
            raise serializers.ValidationError(
                {'non_field_errors': ['This category already exists.']}
            )

    @staticmethod
    def _unique_slug(name):
        base = slugify(name)[:110] or 'category'
        slug, n = base, 2
        while Category.objects.filter(slug=slug).exists():
            slug, n = f'{base}-{n}', n + 1
        return slug


class CategoryTreeSerializer(serializers.ModelSerializer):
    """A category with its subcategories nested recursively.

    Children come from ``context['children_map']`` ({parent_id: [Category, ...]})
    that the view builds from a single query, so any depth costs one query.
    """

    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'children']
        read_only_fields = fields

    def get_children(self, obj):
        children = self.context.get('children_map', {}).get(obj.id, [])
        return CategoryTreeSerializer(children, many=True, context=self.context).data


# Annotated after the class exists so the OpenAPI schema can describe the recursion.
extend_schema_field(CategoryTreeSerializer(many=True))(CategoryTreeSerializer.get_children)
