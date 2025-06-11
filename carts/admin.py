from django.contrib import admin
from .models import Cart, CartItem, CartItemBoxCustomization, CartItemBoxFlavorSelection, CartItemPackCustomization


class BoxFlavorSelectionInline(admin.TabularInline):
    model = CartItemBoxFlavorSelection
    fk_name = 'box_customization'
    extra = 0
    readonly_fields = ['created', 'updated']
    classes = ['collapse']


class PackFlavorSelectionInline(admin.TabularInline):
    model = CartItemBoxFlavorSelection
    fk_name = 'pack_customization'
    extra = 0
    readonly_fields = ['created', 'updated']
    classes = ['collapse']


class CartItemBoxCustomizationInline(admin.TabularInline):
    model = CartItemBoxCustomization
    extra = 0
    readonly_fields = ['created', 'updated']
    inlines = [BoxFlavorSelectionInline]
    show_change_link = True
    classes = ['collapse']


class CartItemInline(admin.StackedInline):
    model = CartItem
    extra = 0
    readonly_fields = ['created', 'updated']
    show_change_link = True
    inlines = [CartItemBoxCustomizationInline]
    classes = ['collapse']

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        return formset


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['id', 'session_id', 'user', 'discount', 'created', 'updated', 'get_total', 'get_items_count']
    list_filter = ['created', 'updated']
    search_fields = ['session_id', 'user__email']
    readonly_fields = ['created', 'updated', 'get_total', 'get_items_count']
    inlines = [CartItemInline]

    def get_total(self, obj):
        return f"£{sum(item.quantity * item.product.base_price for item in obj.items.all())}"
    get_total.short_description = 'Cart Total'

    def get_items_count(self, obj):
        return obj.items.count()
    get_items_count.short_description = 'Number of Items'

    fieldsets = (
        ('Cart Information', {
            'fields': ('user', 'session_id', 'discount', 'active')
        }),
        ('Additional Information', {
            'fields': ('gift_message', 'shipping_date')
        }),
        ('Metrics', {
            'fields': ('get_total', 'get_items_count')
        }),
        ('Timestamps', {
            'fields': ('created', 'updated'),
            'classes': ('collapse',)
        }),
    )


class CartItemBoxCustomizationAdmin(admin.ModelAdmin):
    list_display = ['id', 'cart_item', 'selection_type', 'created', 'updated']
    list_filter = ['selection_type', 'created', 'updated']
    search_fields = ['cart_item__cart__session_id']
    readonly_fields = ['created', 'updated']
    inlines = [BoxFlavorSelectionInline]


class CartItemPackCustomizationAdmin(admin.ModelAdmin):
    list_display = ['id', 'cart_item', 'selection_type', 'created', 'updated']
    list_filter = ['selection_type', 'created', 'updated']
    search_fields = ['cart_item__cart__session_id']
    readonly_fields = ['created', 'updated']
    inlines = [PackFlavorSelectionInline]
    autocomplete_fields = ['cart_item']


class CartItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'cart', 'product', 'quantity', 'created', 'updated']
    list_filter = ['created', 'updated']
    search_fields = ['cart__session_id', 'product__name', 'id']
    readonly_fields = ['created', 'updated']
    inlines = [CartItemBoxCustomizationInline]

    fieldsets = (
        ('Cart Item Information', {
            'fields': ('cart', 'product', 'quantity')
        }),
        ('Timestamps', {
            'fields': ('created', 'updated'),
            'classes': ('collapse',)
        }),
    )


admin.site.register(CartItemBoxCustomization, CartItemBoxCustomizationAdmin)
admin.site.register(CartItem, CartItemAdmin)
admin.site.register(CartItemPackCustomization, CartItemPackCustomizationAdmin)
