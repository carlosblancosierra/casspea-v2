from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Lead

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ['email', 'lead_type', 'unsubscribed', 'created', 
                    'first_name', 'last_name', 'instagram_username', 
                    'form_code']
    list_filter = ['lead_type', 'unsubscribed', 'created','form_code']
    search_fields = ['email']
