from django.db import migrations
from django.db.models import F


def widen_estimate_ranges(apps, schema_editor):
    """
    Give the non-guaranteed services the range Royal Mail actually promises.

    Every option was stored with estimated_days_min == estimated_days_max, so
    the checkout showed a single delivery day for services the carrier only
    ever describes as a range — Tracked 24 "aims to deliver the next working
    day", Tracked 48 "two to three working days". Stating one date for those
    is a promise neither we nor Royal Mail have made.

    Only the max moves, and only where it currently equals the min, so a
    range someone has already widened by hand is left alone. Special Delivery
    keeps min == max: it genuinely is one guaranteed day, which is the whole
    point of the guaranteed flag.
    """
    ShippingOption = apps.get_model('shipping', 'ShippingOption')
    ShippingOption.objects.filter(
        guaranteed=False,
        estimated_days_min=F('estimated_days_max'),
    ).update(estimated_days_max=F('estimated_days_max') + 1)


def narrow_estimate_ranges(apps, schema_editor):
    ShippingOption = apps.get_model('shipping', 'ShippingOption')
    ShippingOption.objects.filter(
        guaranteed=False,
        estimated_days_max=F('estimated_days_min') + 1,
    ).update(estimated_days_max=F('estimated_days_min'))


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0006_shippingoption_guaranteed"),
    ]

    operations = [
        migrations.RunPython(widen_estimate_ranges, narrow_estimate_ranges),
    ]
