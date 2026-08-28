# Generated for Summer Break clearance boxes (compare-at / "was" price)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0011_product_disable_flavour_selection_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="compare_at_price",
            field=models.DecimalField(
                max_digits=10,
                decimal_places=2,
                null=True,
                blank=True,
                help_text="Original price to show struck through (e.g. the pre-discount price).",
            ),
        ),
    ]
