"""Reusable DRF permission classes."""
from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """Anyone may read; only staff users may write."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)
