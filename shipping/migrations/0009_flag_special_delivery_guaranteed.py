from django.db import migrations


def flag_guaranteed_services(apps, schema_editor):
    """
    Turn the guaranteed flag on for Royal Mail's next-day service.

    0006 added the field with default=False, which left every live row saying
    "estimate" — including the one service the carrier genuinely commits to
    and compensates for. So the checkout has been describing Special Delivery
    exactly the way the guaranteed flag exists to stop it describing it.

    Fixing that was a manual tick in Django admin in the deploy notes, which
    is the kind of step that gets missed. It belongs in the migration.

    Matched on delivery_speed rather than name: the name is editable in admin
    and someone renaming the service should not silently turn the guarantee
    back into an estimate.
    """
    ShippingOption = apps.get_model('shipping', 'ShippingOption')
    ShippingOption.objects.filter(delivery_speed='NEXT_DAY').update(guaranteed=True)


def unflag_guaranteed_services(apps, schema_editor):
    ShippingOption = apps.get_model('shipping', 'ShippingOption')
    ShippingOption.objects.filter(delivery_speed='NEXT_DAY').update(guaranteed=False)


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0008_retire_priority_24"),
    ]

    operations = [
        migrations.RunPython(flag_guaranteed_services, unflag_guaranteed_services),
    ]
