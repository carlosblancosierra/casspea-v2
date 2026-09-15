from django.contrib import admin
from django.contrib import messages
from .models import Flavour, FlavourCategory, FlavourSelection, FlavourBox

@admin.register(FlavourCategory)
class FlavourCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'active']
    list_filter = ['active']
    search_fields = ['name']

@admin.register(Flavour)
class FlavourAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'active', 'created', 'updated']
    list_filter = ['category', 'active', 'allergens']
    search_fields = ['name', 'description', 'mini_description', 'story']
    filter_horizontal = ['allergens']
    actions = ['make_active', 'make_inactive']

    def make_active(self, request, queryset):
        updated = queryset.update(active=True)
        self.message_user(
            request,
            f'{updated} flavours have been marked as active.',
            messages.SUCCESS
        )
    make_active.short_description = "Mark selected flavours as active"

    def make_inactive(self, request, queryset):
        updated = queryset.update(active=False)
        self.message_user(
            request,
            f'{updated} flavours have been marked as inactive.',
            messages.SUCCESS
        )
    make_inactive.short_description = "Mark selected flavours as inactive"

@admin.register(FlavourSelection)
class FlavourSelectionAdmin(admin.ModelAdmin):
    list_display = ['flavour', 'quantity']
    list_filter = ['flavour']
    search_fields = ['flavour__name']

@admin.register(FlavourBox)
class FlavourBoxAdmin(admin.ModelAdmin):
    list_display = ['id', 'created', 'updated']
    list_filter = ['created']
    filter_horizontal = ['selections']
