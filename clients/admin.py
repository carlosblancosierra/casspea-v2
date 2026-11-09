from django.contrib import admin

from .models import ClientPage, ClientPageItem


class ClientPageItemInline(admin.TabularInline):
    model = ClientPageItem
    extra = 1
    autocomplete_fields = ['product']
    fields = ['product', 'flavour', 'order']


@admin.register(ClientPage)
class ClientPageAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'active', 'updated']
    list_filter = ['active']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ClientPageItemInline]
