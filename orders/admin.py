from django.contrib import admin
from .models import Order

# Register your models here.
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_id', 'tracking_number', 'shipping_order_id', 'status', 'created']
    search_fields = ['order_id']
    list_filter = ['status']
