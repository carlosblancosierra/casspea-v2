from django.db import migrations


def retire_priority_24(apps, schema_editor):
    """
    Three delivery options was one decision too many.

    Two is the choice that actually means something: a tracked service with a
    range, or Special Delivery for a date the carrier guarantees. Priority 24
    sat between them — dearer than the tracked one, without the guarantee — so
    it added a third column of near-identical text to compare and no real
    third answer.

    Deactivated rather than deleted. CheckoutSession.shipping_option points at
    it on every order ever placed with it, and that FK is SET_NULL, so a delete
    would quietly erase what those customers were charged for.
    """
    ShippingOption = apps.get_model('shipping', 'ShippingOption')
    ShippingOption.objects.filter(name='Priority 24').update(active=False)


def restore_priority_24(apps, schema_editor):
    ShippingOption = apps.get_model('shipping', 'ShippingOption')
    ShippingOption.objects.filter(name='Priority 24').update(active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0007_widen_estimate_ranges"),
    ]

    operations = [
        migrations.RunPython(retire_priority_24, restore_priority_24),
    ]
