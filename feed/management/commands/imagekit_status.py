"""
How much of the ImageKit free plan UniConnect is using, which videos (and
how many photos) are on ImageKit, and clean-up of leftover uploads.

Usage:
    python manage.py imagekit_status
        This month's bandwidth / storage / video processing units against
        the free plan, every UniConnect video stored on ImageKit, and any
        leftover uploads (files on ImageKit that no post uses — e.g. a video
        uploaded and then the composer closed before posting).

    python manage.py imagekit_status --delete-leftovers
        Same, then deletes those leftover files from ImageKit.

Files uploaded in the last hour are never counted as leftovers, so a post
that's being written right now is safe. To remove a video that IS on a
post, delete the post in UniConnect: its files are deleted from ImageKit
automatically.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from feed import imagekit
from feed.models import PostMedia, Story

# ImageKit free plan (https://imagekit.io/plans)
FREE_BANDWIDTH_GB = 20
FREE_STORAGE_GB = 3
FREE_VIDEO_UNITS = 500
GB = 1024 ** 3
SAFE_AGE = timedelta(hours=1)


def _mb(n):
	return f'{(n or 0) / 1024 ** 2:,.1f} MB'


def _size(n):
	n = n or 0
	return f'{n / GB:.2f} GB' if n >= GB else _mb(n)


def _bar(used, limit, width=24):
	share = min(1.0, (used or 0) / limit) if limit else 0
	filled = round(share * width)
	return '[' + '#' * filled + '.' * (width - filled) + f'] {share * 100:5.1f}%'


class Command(BaseCommand):
	help = "Show ImageKit usage vs the free plan, list UniConnect's videos on ImageKit, and clean up leftover uploads."

	def add_arguments(self, parser):
		parser.add_argument('--delete-leftovers', action='store_true',
			help='Delete files on ImageKit that no UniConnect post uses (older than 1 hour).')

	def handle(self, *args, **opts):
		if not imagekit.enabled():
			raise CommandError('ImageKit is not configured (IMAGEKIT_PUBLIC_KEY / IMAGEKIT_PRIVATE_KEY in .env).')
		try:
			self.show_usage()
			files = self.show_videos()
			self.leftovers(files, opts['delete_leftovers'])
		except imagekit.ImageKitError as e:
			raise CommandError(f'ImageKit: {e}')

	# ------------------------------------------------------------------
	def show_usage(self):
		today = date.today()
		start = today.replace(day=1)
		end = today + timedelta(days=1)            # the end date itself is excluded
		u = imagekit.usage(start.isoformat(), end.isoformat())
		bw, storage, units = u.get('bandwidthBytes', 0), u.get('mediaLibraryStorageBytes', 0), u.get('videoProcessingUnitsCount', 0)
		self.stdout.write(self.style.MIGRATE_HEADING(f'ImageKit usage this month ({start:%d %b} – {today:%d %b %Y})'))
		self.stdout.write(f'  Bandwidth          {_size(bw):>10} of {FREE_BANDWIDTH_GB} GB     {_bar(bw, FREE_BANDWIDTH_GB * GB)}')
		self.stdout.write(f'  Storage            {_size(storage):>10} of {FREE_STORAGE_GB} GB      {_bar(storage, FREE_STORAGE_GB * GB)}')
		self.stdout.write(f'  Video processing   {units:>10,} of {FREE_VIDEO_UNITS} units {_bar(units, FREE_VIDEO_UNITS)}')
		streaming = 'ON (uses video processing units)' if imagekit.streaming_enabled() else 'off (no video processing units used)'
		self.stdout.write(f'  Adaptive streaming: {streaming}')
		for label, used, limit in (('Bandwidth', bw, FREE_BANDWIDTH_GB * GB), ('Storage', storage, FREE_STORAGE_GB * GB),
								   ('Video processing', units, FREE_VIDEO_UNITS)):
			if limit and used / limit >= 0.8:
				self.stdout.write(self.style.WARNING(f'  ! {label} is at {used / limit * 100:.0f}% of the free plan.'))
		self.stdout.write('')

	def show_videos(self):
		files = {f['fileId']: f for path in (imagekit.VIDEO_FOLDER, imagekit.THUMBNAIL_FOLDER, imagekit.PHOTO_FOLDER, imagekit.STORY_FOLDER)
				 for f in imagekit.list_files(path)}
		photos = [f for f in files.values() if (f.get('filePath') or '').startswith((imagekit.PHOTO_FOLDER + '/', imagekit.STORY_FOLDER + '/'))]
		self.stdout.write(self.style.MIGRATE_HEADING(f'Photos on ImageKit (posts and stories): {len(photos)} — {_mb(sum(f.get("size", 0) for f in photos))}'))
		self.stdout.write('')
		media = (PostMedia.objects.exclude(ik_url='').select_related('post', 'post__author')
				 .annotate(views=Count('post__video_views')).order_by('post__created_at'))
		self.stdout.write(self.style.MIGRATE_HEADING(f'Videos on ImageKit used by posts: {len(media)}'))
		for m in media:
			p = m.post
			size = (files.get(m.ik_file_id) or {}).get('size', 0) + (files.get(m.ik_thumbnail_file_id) or {}).get('size', 0)
			text = (p.content or '').strip().replace('\n', ' ')[:48] or '(no text)'
			self.stdout.write(f'  post {p.pk:<5} {p.created_at:%d %b %Y}  {_mb(size):>9}  {m.views:>3} views  @{p.author.username}  "{text}"')
		if not media:
			self.stdout.write('  (none yet)')
		self.stdout.write('  To remove one: delete the post in UniConnect — its files are deleted from ImageKit too.\n')
		return files

	def leftovers(self, files, delete):
		used = set(PostMedia.objects.exclude(ik_file_id='').values_list('ik_file_id', flat=True))
		used |= set(PostMedia.objects.exclude(ik_thumbnail_file_id='').values_list('ik_thumbnail_file_id', flat=True))
		used |= set(PostMedia.objects.exclude(ik_image_file_id='').values_list('ik_image_file_id', flat=True))
		used |= set(Story.objects.exclude(ik_image_file_id='').values_list('ik_image_file_id', flat=True))
		now = datetime.now(dt_timezone.utc)
		left = []
		for fid, f in files.items():
			if fid in used:
				continue
			created = f.get('createdAt')
			try:
				created = datetime.fromisoformat(created.replace('Z', '+00:00')) if created else None
			except ValueError:
				created = None
			if created and now - created < SAFE_AGE:
				continue                       # might be a post being written right now
			left.append(f)
		total = sum(f.get('size', 0) for f in left)
		self.stdout.write(self.style.MIGRATE_HEADING(f'Leftover uploads (on ImageKit, not on any post): {len(left)} — {_mb(total)}'))
		for f in left:
			self.stdout.write(f"  {f.get('filePath')}  {_mb(f.get('size'))}  uploaded {str(f.get('createdAt', ''))[:10]}")
		if not left:
			self.stdout.write('  Nothing to clean up.')
			return
		if not delete:
			self.stdout.write('  Run again with --delete-leftovers to delete them.')
			return
		for f in left:
			imagekit.delete_file(f['fileId'])
		self.stdout.write(self.style.SUCCESS(f'  Deleted {len(left)} leftover file(s), freeing {_mb(total)}.'))
