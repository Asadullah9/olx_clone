"""Serializers shared across apps."""
from rest_framework import serializers


class ErrorDetailSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField()


class ErrorResponseSerializer(serializers.Serializer):
    """Documents the uniform error envelope produced by core.exceptions."""

    error = ErrorDetailSerializer()
