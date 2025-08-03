from django.contrib import admin
from .models import Order, UnitsSold

# Register your models here.


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_id', 'tracking_number', 'shipping_order_id', 'status', 'created']
    search_fields = ['order_id']
    list_filter = ['status']


@admin.register(UnitsSold)
class UnitsSoldAdmin(admin.ModelAdmin):
    list_display = ['source', 'date', 'units_sold']
    list_filter = ['source', 'date']
    search_fields = ['source', 'date']
