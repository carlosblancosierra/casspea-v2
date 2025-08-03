from django.contrib import admin
from .models import Order, UnitsSold, SoldSource

# Register your models here.


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_id', 'tracking_number', 'shipping_order_id', 'status', 'created']
    search_fields = ['order_id']
    list_filter = ['status']


@admin.register(UnitsSold)
class UnitsSoldAdmin(admin.ModelAdmin):
    list_display = ['source_fk', 'date', 'units_sold']
    list_filter = ['source_fk', 'date']
    search_fields = ['source_fk', 'date']


@admin.register(SoldSource)
class SoldSourceAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']
