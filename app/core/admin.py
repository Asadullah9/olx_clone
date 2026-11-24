"""Django admin customisation."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from core.models import Ad, AdImage, Category, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ['id']
    list_display = ['email', 'name', 'is_staff', 'is_active']
    search_fields = ['email', 'name']
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {'fields': ('name',)}),
        (
            _('Permissions'),
            {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')},
        ),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    readonly_fields = ['last_login', 'date_joined']
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'name', 'password1', 'password2', 'is_staff', 'is_superuser'),
        }),
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'parent', 'created_at']
    list_filter = ['parent']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    autocomplete_fields = ['parent']


class AdImageInline(admin.TabularInline):
    model = AdImage
    extra = 0
    fields = ['image', 'display_order', 'created_at']
    readonly_fields = ['created_at']


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'category', 'price', 'status', 'created_at']
    list_filter = ['status', 'category']
    search_fields = ['title', 'description', 'user__email']
    list_select_related = ['user', 'category']
    autocomplete_fields = ['user', 'category']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [AdImageInline]
