from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0008_backfill_has_completed_reveal"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_demo",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
