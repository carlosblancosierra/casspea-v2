from django.db import migrations
from django.db.models import F


def narrow_guaranteed_estimates(apps, schema_editor):
    """
    Put the guaranteed service back to a single day.

    0007 widened every option where `guaranteed=False` and min == max, so the
    tracked services would show the range Royal Mail actually promises. It
    meant to leave Special Delivery alone, and its docstring says so — but
    0006 had added `guaranteed` with default=False and nothing set it until
    0009, three migrations later. So when 0007 ran, Special Delivery was
    `guaranteed=False` like everything else and got widened with the rest:
    min=1, max=2.

    The checkout decides "one day" against "a range" from min == max, because
    that is the carrier's promise expressed as data. With the range widened it
    has been describing the one contractually guaranteed service as a two-day
    estimate — the exact wording the guaranteed flag exists to prevent.

    Matched on `guaranteed=True`, which by now is genuinely set. That is the
    whole lesson of 0007: a data migration cannot guard on a flag that a later
    migration is going to populate.
    """
    ShippingOption = apps.get_model('shipping', 'ShippingOption')
    ShippingOption.objects.filter(
        guaranteed=True,
        estimated_days_max__gt=F('estimated_days_min'),
    ).update(estimated_days_max=F('estimated_days_min'))


def rewiden_guaranteed_estimates(apps, schema_editor):
    """
    Deliberately a no-op.

    Reversing this would restore a range on a service the carrier guarantees
    for a named day, which is the bug rather than a state worth returning to.
    A rollback should leave the data correct.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0009_flag_special_delivery_guaranteed"),
    ]

    operations = [
        migrations.RunPython(narrow_guaranteed_estimates, rewiden_guaranteed_estimates),
    ]
