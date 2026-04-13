import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mails", "0008_alter_emailtype_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailsent",
            name="opened",
            field=models.DateTimeField(blank=True, null=True),
        ),
        # Add token without unique constraint first so existing rows get defaults
        migrations.AddField(
            model_name="emailsent",
            name="token",
            field=models.UUIDField(default=uuid.uuid4, unique=False),
        ),
        # Then apply the unique constraint
        migrations.AlterField(
            model_name="emailsent",
            name="token",
            field=models.UUIDField(default=uuid.uuid4, unique=True, db_index=True),
        ),
    ]
