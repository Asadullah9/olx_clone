"""Serializers shared across apps."""
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers


class ErrorDetailSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField()


class ErrorResponseSerializer(serializers.Serializer):
    """Documents the uniform error envelope produced by core.exceptions."""

    success = serializers.BooleanField(default=False)
    message = serializers.CharField()
    data = serializers.JSONField(allow_null=True, default=None)
    error = ErrorDetailSerializer()


class PaginationSerializer(serializers.Serializer):
    """Documents the pagination block produced by core.pagination."""

    total = serializers.IntegerField()
    page = serializers.IntegerField()
    limit = serializers.IntegerField()
    totalPages = serializers.IntegerField()
    hasNextPage = serializers.BooleanField()
    hasPreviousPage = serializers.BooleanField()


def envelope(name, data_serializer=None, *, many=False, paginated=False):
    """OpenAPI schema for a success envelope wrapping ``data_serializer``."""
    fields = {
        'success': serializers.BooleanField(default=True),
        'message': serializers.CharField(),
        'data': (
            data_serializer(many=many) if data_serializer
            else serializers.JSONField(allow_null=True, default=None)
        ),
    }
    if paginated:
        fields['pagination'] = PaginationSerializer()
    return inline_serializer(name=name, fields=fields)
