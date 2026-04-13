import uuid
from django.db import migrations, models


def assign_unique_tokens(apps, schema_editor):
    EmailSent = apps.get_model("mails", "EmailSent")
    for row in EmailSent.objects.filter(token__isnull=True):
        row.token = uuid.uuid4()
        row.save(update_fields=["token"])


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
        # Add nullable first so existing rows don't all get the same default
        migrations.AddField(
            model_name="emailsent",
            name="token",
            field=models.UUIDField(null=True, unique=False),
        ),
        # Assign a unique UUID to every existing row
        migrations.RunPython(assign_unique_tokens, migrations.RunPython.noop),
        # Now safe to enforce uniqueness and drop null
        migrations.AlterField(
            model_name="emailsent",
            name="token",
            field=models.UUIDField(default=uuid.uuid4, unique=True, db_index=True),
        ),
    ]
