"""Le job d'impression pointe vers les réglages.
/ The print job points at the settings."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("impression", "0001_initial"),
        ("bornes", "0003_reglages"),
    ]

    operations = [
        migrations.RenameField(
            model_name="jobimpression", old_name="borne", new_name="reglages"
        ),
    ]
