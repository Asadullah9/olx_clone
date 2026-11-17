"""Database models shared across the project."""
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.core.exceptions import ValidationError
from django.db import models


class UserManager(BaseUserManager):
    """Manager for users who log in with an email address."""

    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address.')
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """User account identified by email instead of username."""

    email = models.EmailField(max_length=255, unique=True)
    name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'

    def __str__(self):
        return self.email


class Category(models.Model):
    """Listing category. Categories nest through `parent` (Electronics -> Mobile Phones)."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        # Never cascade: removing a parent must not silently wipe its subtree.
        on_delete=models.PROTECT,
        related_name='children',
    )

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'categories'
        constraints = [
            # nulls_distinct=False makes two top-level categories with the same
            # name collide too (Postgres treats NULLs as distinct by default).
            models.UniqueConstraint(
                fields=['parent', 'name'],
                nulls_distinct=False,
                name='unique_category_name_per_parent',
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """Reject a parent chain that would loop back to this category."""
        ancestor = self.parent
        while ancestor is not None:
            if self.pk is not None and ancestor.pk == self.pk:
                raise ValidationError({'parent': 'A category cannot be its own ancestor.'})
            ancestor = ancestor.parent
