from django import forms
from django.contrib import admin

from .models import ClientPage, ClientPageItem


class ClientPageItemInline(admin.TabularInline):
    model = ClientPageItem
    extra = 1
    autocomplete_fields = ['product']
    fields = ['product', 'flavour', 'order']


class ClientPageForm(forms.ModelForm):
    new_access_code = forms.CharField(
        required=False,
        help_text="Type a code to set or change it (it is stored hashed and "
                  "can't be shown again). Changing it locks out everyone who "
                  "used the old one. Leave empty to keep the current code.",
    )

    class Meta:
        model = ClientPage
        fields = '__all__'

    def save(self, commit=True):
        page = super().save(commit=False)
        code = self.cleaned_data.get('new_access_code', '').strip()
        if code:
            page.set_access_code(code)
        if commit:
            page.save()
            self.save_m2m()
        return page


@admin.register(ClientPage)
class ClientPageAdmin(admin.ModelAdmin):
    form = ClientPageForm
    list_display = ['name', 'slug', 'active', 'has_access_code', 'updated']
    list_filter = ['active']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ClientPageItemInline]

    @admin.display(boolean=True, description='Code set')
    def has_access_code(self, obj):
        return obj.has_access_code
