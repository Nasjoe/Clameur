"""La capsule pointe vers les réglages, plus vers une borne.

Un `RenameField` conserve la colonne et ses données ; le régénérer aurait
détaché toutes les capsules de leur lieu.
/ RenameField keeps the column and its data.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("capsules", "0002_capsule_position_x_capsule_position_y"),
        ("bornes", "0003_reglages"),
    ]

    operations = [
        migrations.RenameField(model_name="capsule", old_name="borne", new_name="reglages"),
    ]
