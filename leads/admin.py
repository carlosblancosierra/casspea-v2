from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import EmailOptOut, Lead

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ['email', 'lead_type', 'unsubscribed', 'created', 
                    'first_name', 'last_name', 'instagram_username', 
                    'form_code']
    list_filter = ['lead_type', 'unsubscribed', 'created','form_code']
    search_fields = ['email']


@admin.register(EmailOptOut)
class EmailOptOutAdmin(admin.ModelAdmin):
    """Addresses that unsubscribed. Delete one to send them marketing again,
    only if they asked to be added back."""
    list_display = ['email', 'created']
    search_fields = ['email']
