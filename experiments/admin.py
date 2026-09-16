from django.contrib import admin

from .models import Assignment, Event, Experiment


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = ['key', 'name', 'active', 'variants', 'created']
    list_filter = ['active']
    search_fields = ['key', 'name']


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ['experiment', 'variant', 'session_id', 'user', 'created']
    list_filter = ['experiment', 'variant']
    search_fields = ['session_id']
    raw_id_fields = ['user']


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['name', 'assignment', 'created']
    list_filter = ['name']
