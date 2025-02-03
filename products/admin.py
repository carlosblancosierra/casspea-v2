from django.contrib import admin
from django.utils.html import format_html
from .models import Product, ProductCategory, ProductGalleryImage


class ProductGalleryImageInline(admin.TabularInline):
    model = ProductGalleryImage
    extra = 1
    readonly_fields = ['image_preview', 'thumbnail_preview']
    fields = ['image', 'image_preview', 'thumbnail', 'thumbnail_preview', 'order', 'alt_text']

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 150px;"/>', obj.image.url)
        return "No image"
    image_preview.short_description = 'Image Preview'

    def thumbnail_preview(self, obj):
        if obj.thumbnail:
            return format_html('<img src="{}" style="max-height: 100px;"/>', obj.thumbnail.url)
        return "No thumbnail"
    thumbnail_preview.short_description = 'Thumbnail Preview'


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'base_price', 'active', 'sold_out', 'image_preview']
    list_filter = ['category', 'active', 'sold_out']
    search_fields = ['name', 'description']
    inlines = [ProductGalleryImageInline]

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 50px;"/>', obj.image.url)
        return "No image"
    image_preview.short_description = 'Image Preview'

@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'active']
    list_filter = ['active']
    search_fields = ['name', 'description']

@admin.register(ProductGalleryImage)
class ProductGalleryImageAdmin(admin.ModelAdmin):
    list_display = ['product', 'order', 'image_preview', 'thumbnail_preview']
    list_filter = ['product']
    ordering = ['product', 'order']

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 100px;"/>', obj.image.url)
        return "No image"
    image_preview.short_description = 'Image Preview'

    def thumbnail_preview(self, obj):
        if obj.thumbnail:
            return format_html('<img src="{}" style="max-height: 50px;"/>', obj.thumbnail.url)
        return "No thumbnail"
    thumbnail_preview.short_description = 'Thumbnail Preview'
