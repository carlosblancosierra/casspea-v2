import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mails", "0008_alter_emailtype_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailsent",
            name="token",
            field=models.UUIDField(default=uuid.uuid4, unique=True, db_index=True),
        ),
        migrations.AddField(
            model_name="emailsent",
            name="opened",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
