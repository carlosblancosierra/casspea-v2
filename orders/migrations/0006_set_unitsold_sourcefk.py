from django.db import migrations


def set_source_fk_to_1(apps, schema_editor):
    UnitsSold = apps.get_model('orders', 'UnitsSold')
    UnitsSold.objects.filter(source_fk__isnull=True).update(source_fk_id=1)


class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0005_soldsource_unitssold_source_fk'),
    ]

    operations = [
        migrations.RunPython(set_source_fk_to_1, reverse_code=migrations.RunPython.noop),
    ]
