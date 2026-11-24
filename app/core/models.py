"""Database models shared across the project."""
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Upper


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
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        # Never cascade: removing a parent must not silently wipe its subtree.
        on_delete=models.PROTECT,
        related_name='children',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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


class AdStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'        # approved by an admin and publicly visible
    PENDING = 'PENDING', 'Pending'     # awaiting admin review (default)
    INACTIVE = 'INACTIVE', 'Inactive'  # disabled by its owner or an admin
    REJECTED = 'REJECTED', 'Rejected'  # refused by an admin


class Ad(models.Model):
    """A product advertisement posted by a user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ads',
    )
    category = models.ForeignKey(
        Category,
        # A category that still has ads cannot be deleted.
        on_delete=models.PROTECT,
        related_name='ads',
    )
    title = models.CharField(max_length=150)
    description = models.TextField(max_length=5000)
    price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0)],
    )
    status = models.CharField(
        max_length=10, choices=AdStatus.choices, default=AdStatus.PENDING,
    )
    rejection_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            # user_id and category_id are indexed automatically as foreign keys.
            models.Index(fields=['status'], name='ad_status_idx'),
            models.Index(fields=['created_at'], name='ad_created_at_idx'),
            models.Index(fields=['price'], name='ad_price_idx'),
            # The default public listing: ACTIVE ads, newest first.
            models.Index(fields=['status', '-created_at'], name='ad_status_created_idx'),
            # "My ads" filtered by status.
            models.Index(fields=['user', 'status'], name='ad_user_status_idx'),
            # Trigram indexes serve case-insensitive partial matching. Django
            # compiles `icontains` on Postgres to UPPER(col) LIKE UPPER(%s), so
            # the indexed expression is UPPER(col) for the planner to use it.
            GinIndex(
                OpClass(Upper('title'), name='gin_trgm_ops'), name='ad_title_trgm_idx',
            ),
            GinIndex(
                OpClass(Upper('description'), name='gin_trgm_ops'),
                name='ad_description_trgm_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gte=0), name='ad_price_non_negative'),
        ]

    def __str__(self):
        return self.title


class AdImage(models.Model):
    """One product photo of an ad. ``image`` holds the storage reference."""

    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(max_length=255)
    display_order = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'id']
        constraints = [
            # Deferred so positions can be renumbered inside one transaction.
            models.UniqueConstraint(
                fields=['ad', 'display_order'],
                name='unique_ad_image_order',
                deferrable=models.Deferrable.DEFERRED,
            ),
        ]

    def __str__(self):
        return f'{self.ad_id}#{self.display_order}'
