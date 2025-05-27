from django.contrib import admin
from django.contrib.admin import register
from checkout.models import CheckoutSession


# Register your models here.
@register(CheckoutSession)
class CheckoutSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'cart', 'email', 'created')
    search_fields = ('cart__id', 'email')
    list_filter = ('created',)
    autocomplete_fields = ['cart']
