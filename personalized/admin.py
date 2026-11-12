from django.contrib import admin
from .models import (
    LayerColor,
    LayerType,
    ChocolateTemplate,
    TemplateLayerSlot,
    ChocolateLayer,
    PersonalisedRequest,
)

@admin.register(LayerColor)
class LayerColorAdmin(admin.ModelAdmin):
    list_display = ('name', 'hex_code')
    search_fields = ('name',)


@admin.register(LayerType)
class LayerTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(ChocolateLayer)
class ChocolateLayerAdmin(admin.ModelAdmin):
    list_display = ('layer_type', 'color', 'top_image', 'side_image')
    list_filter = ('layer_type', 'color')
    search_fields = ('layer_type__name', 'color__name')
    autocomplete_fields = ('layer_type', 'color')  # Enable autocomplete for foreign keys


class TemplateLayerSlotInline(admin.TabularInline):
    model = TemplateLayerSlot
    extra = 1
    autocomplete_fields = ('layer_type',)


@admin.register(ChocolateTemplate)
class ChocolateTemplateAdmin(admin.ModelAdmin):
    list_display = ('title',)
    search_fields = ('title',)
    inlines = [TemplateLayerSlotInline]  # Include inline editing for related TemplateLayerSlot


@admin.register(TemplateLayerSlot)
class TemplateLayerSlotAdmin(admin.ModelAdmin):
    list_display = ('template', 'layer_type', 'name', 'order')
    list_filter = ('template', 'layer_type')
    search_fields = ('template__title', 'layer_type__name')
    ordering = ('template', 'order')  # Ensure slots are displayed in order
    autocomplete_fields = ('template', 'layer_type')  # Enable autocomplete


@admin.register(PersonalisedRequest)
class PersonalisedRequestAdmin(admin.ModelAdmin):
    list_display = ('created', 'email', 'template', 'quantity', 'handled')
    list_filter = ('handled', 'template')
    list_editable = ('handled',)
    search_fields = ('email', 'comments')
    readonly_fields = ('created',)
