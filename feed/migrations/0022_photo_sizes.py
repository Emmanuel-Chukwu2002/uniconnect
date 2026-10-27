# Photos' real sizes (PostMedia.width / height), so small photos can be shown
# at their true size instead of stretched. Existing photos get theirs filled
# in: read from the file on this computer, or asked from ImageKit (best
# effort — a photo whose size can't be found simply keeps None).
from django.db import migrations, models


def fill_sizes(apps, schema_editor):
	PostMedia = apps.get_model('feed', 'PostMedia')
	from django.core.files.images import get_image_dimensions
	from feed import imagekit
	for m in PostMedia.objects.filter(width__isnull=True).exclude(image='', ik_image_url=''):
		w = h = None
		try:
			if m.image:
				with m.image.open('rb') as f:
					w, h = get_image_dimensions(f)
			elif m.ik_image_file_id and imagekit.enabled():
				d = imagekit.file_details(m.ik_image_file_id)
				w, h = d.get('width'), d.get('height')
		except Exception:
			continue
		if w and h:
			PostMedia.objects.filter(pk=m.pk).update(width=w, height=h)


class Migration(migrations.Migration):

	dependencies = [
		('feed', '0021_imagekit_photos'),
	]

	operations = [
		migrations.AddField(
			model_name='postmedia',
			name='height',
			field=models.PositiveIntegerField(blank=True, null=True),
		),
		migrations.AddField(
			model_name='postmedia',
			name='width',
			field=models.PositiveIntegerField(blank=True, null=True),
		),
		migrations.RunPython(fill_sizes, migrations.RunPython.noop),
	]
