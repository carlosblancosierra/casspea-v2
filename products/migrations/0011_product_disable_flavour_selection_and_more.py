# Generated for Summer Break clearance boxes

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0010_product_custom_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="disable_flavour_selection",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "If True, this box only supports 'Surprise Me' (RANDOM) "
                    "selection; customers cannot pick individual flavours."
                ),
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="block_discount_codes",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "If True, discount codes cannot stack on top of this product "
                    "(its price is already discounted)."
                ),
            ),
        ),
    ]
