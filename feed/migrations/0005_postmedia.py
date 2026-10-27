# Generated manually to match the model change below

import django.core.validators
import django.db.models.deletion
import feed.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('feed', '0004_post_is_edited'),
    ]

    operations = [
        migrations.CreateModel(
            name='PostMedia',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(
                    blank=True, null=True, upload_to='post_images',
                    validators=[
                        django.core.validators.FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif', 'webp']),
                        feed.models.validate_image_size,
                    ],
                )),
                ('video', models.FileField(
                    blank=True, null=True, upload_to='post_videos',
                    validators=[
                        django.core.validators.FileExtensionValidator(allowed_extensions=['mp4', 'mov', 'webm']),
                        feed.models.validate_video_size,
                    ],
                )),
                ('order', models.PositiveSmallIntegerField(default=0)),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='media_items', to='feed.post')),
            ],
            options={
                'ordering': ['order', 'id'],
            },
        ),
    ]
