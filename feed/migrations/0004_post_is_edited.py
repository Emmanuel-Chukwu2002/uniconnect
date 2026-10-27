# Generated manually to match the model change below

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('feed', '0003_post_video_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='is_edited',
            field=models.BooleanField(
                default=False,
                help_text="Set once this post's text or media has been edited; shows an 'Edited' marker on the post.",
            ),
        ),
    ]
