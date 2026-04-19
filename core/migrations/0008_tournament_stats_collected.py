from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_remove_matchrecord_final_status_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='stats_collected',
            field=models.BooleanField(default=False, help_text='선수 전적 수집 완료 여부'),
        ),
    ]
