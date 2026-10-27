"""
ImageKit.io — where post videos (and their thumbnails) are stored and
streamed from, when it's configured.

How an upload works (no big file ever passes through Django):
  1. The composer asks Django for a one-time signature
     (views.imagekit_auth -> auth_params() below). It's made with the
     PRIVATE key, which never leaves the server.
  2. The browser uploads the video straight to ImageKit with that
     signature and the PUBLIC key, showing a progress bar.
  3. The browser sends Django only the ImageKit fileId. Django asks
     ImageKit for that file's details (file_details()) and trusts only
     what ImageKit says (its URL, type and size) — never a URL typed in
     by the browser.

Playback: by default the original file is played as uploaded
(original_url(), no processing, so no video processing units are used);
the composer makes a thumbnail in the browser if the student doesn't
pick one. With IMAGEKIT_ADAPTIVE_STREAMING=1, ImageKit also serves
adaptive streams (stream_url(): HLS switching between 240p and 1080p)
and generates thumbnails (auto_thumbnail_url()) — both use processing
units.

Keys come from the environment (see .env and settings.py):
  IMAGEKIT_PUBLIC_KEY, IMAGEKIT_PRIVATE_KEY
Without them, videos are saved to MEDIA_ROOT exactly as before.
"""
import base64
import hashlib
import hmac
import json
import re
import time
import uuid
import urllib.error
import urllib.request

from django.conf import settings

VIDEO_FOLDER = '/uniconnect/videos'
THUMBNAIL_FOLDER = '/uniconnect/thumbnails'
PHOTO_FOLDER = '/uniconnect/photos'      # photos in posts
STORY_FOLDER = '/uniconnect/stories'     # story photos
SIGNATURE_LIFETIME = 30 * 60          # seconds; ImageKit allows up to 1 hour
# 50 MB keeps the free plan's 3 GB storage / 20 GB monthly bandwidth
# going much further (and matches the limit for videos stored locally).
MAX_VIDEO_MB = 50
MAX_THUMBNAIL_MB = 8
STREAM_SIZES = 'sr-240_360_480_720_1080'

_FILE_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


class ImageKitError(Exception):
	"""ImageKit couldn't be reached, or said no."""


def enabled():
	return bool(getattr(settings, 'IMAGEKIT_PUBLIC_KEY', '') and getattr(settings, 'IMAGEKIT_PRIVATE_KEY', ''))


def upload_url():
	return getattr(settings, 'IMAGEKIT_UPLOAD_URL', '') or 'https://upload.imagekit.io/api/v1/files/upload'


def _api_url():
	return (getattr(settings, 'IMAGEKIT_API_URL', '') or 'https://api.imagekit.io/v1').rstrip('/')


def auth_params():
	"""The one-time signature a browser needs to upload one file
	directly to ImageKit (client-side upload authentication)."""
	token = uuid.uuid4().hex
	expire = int(time.time()) + SIGNATURE_LIFETIME
	signature = hmac.new(
		settings.IMAGEKIT_PRIVATE_KEY.encode(), f'{token}{expire}'.encode(), hashlib.sha1
	).hexdigest()
	return {
		'token': token, 'expire': expire, 'signature': signature,
		'publicKey': settings.IMAGEKIT_PUBLIC_KEY, 'uploadUrl': upload_url(),
		'videoFolder': VIDEO_FOLDER, 'thumbnailFolder': THUMBNAIL_FOLDER,
		'maxVideoMb': MAX_VIDEO_MB, 'maxThumbnailMb': MAX_THUMBNAIL_MB,
	}


def _request(method, path):
	if not enabled():
		raise ImageKitError('ImageKit is not configured.')
	auth = base64.b64encode(f'{settings.IMAGEKIT_PRIVATE_KEY}:'.encode()).decode()
	req = urllib.request.Request(_api_url() + path, method=method, headers={
		'Authorization': f'Basic {auth}', 'Accept': 'application/json',
	})
	try:
		with urllib.request.urlopen(req, timeout=15) as resp:
			body = resp.read()
			return json.loads(body) if body else {}
	except urllib.error.HTTPError as e:
		raise ImageKitError(f'ImageKit answered {e.code}.') from e
	except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
		raise ImageKitError("Couldn't reach ImageKit.") from e


def list_files(path, limit=1000):
	"""Every file ImageKit holds under `path` (e.g. VIDEO_FOLDER)."""
	from urllib.parse import urlencode
	files, skip = [], 0
	while True:
		page = _request('GET', '/files?' + urlencode({'path': path, 'fileType': 'all', 'limit': limit, 'skip': skip}))
		files += [f for f in page if f.get('type', 'file') == 'file']
		if len(page) < limit:
			return files
		skip += limit


def usage(start_date, end_date):
	"""Account usage between two dates (YYYY-MM-DD; end date excluded,
	under 90 days apart): bandwidthBytes, mediaLibraryStorageBytes,
	videoProcessingUnitsCount, extensionUnitsCount, originalCacheStorageBytes."""
	from urllib.parse import urlencode
	return _request('GET', '/accounts/usage?' + urlencode({'startDate': start_date, 'endDate': end_date}))


def file_details(file_id):
	"""ImageKit's own record of an uploaded file: url, fileType, mime, size, filePath..."""
	if not _FILE_ID.match(file_id or ''):
		raise ImageKitError('That upload ID is not valid.')
	try:
		return _request('GET', f'/files/{file_id}/details')
	except ImageKitError as e:
		if '404' in str(e):
			raise ImageKitError('ImageKit has no file with that ID — please upload it again.') from e
		raise


def delete_file(file_id):
	"""Removes a file from ImageKit. Already gone counts as done."""
	if not file_id or not _FILE_ID.match(file_id):
		return
	try:
		_request('DELETE', f'/files/{file_id}')
	except ImageKitError as e:
		if '404' not in str(e):
			raise


def check_upload(file_id, kind):
	"""Fetches an upload's details from ImageKit and makes sure it is what
	it should be: kind='video' or 'thumbnail', in our folder, not too big.
	Returns the details dict, or raises ImageKitError with a message
	that can be shown to the student."""
	details = file_details(file_id)
	mime = (details.get('mime') or '').lower()
	folder = VIDEO_FOLDER if kind == 'video' else THUMBNAIL_FOLDER
	limit_mb = MAX_VIDEO_MB if kind == 'video' else MAX_THUMBNAIL_MB
	if not (details.get('filePath') or '').startswith(folder + '/'):
		raise ImageKitError('That upload was not made from UniConnect.')
	if kind == 'video' and not mime.startswith('video/'):
		raise ImageKitError('The uploaded file is not a video.')
	if kind == 'thumbnail' and details.get('fileType') != 'image':
		raise ImageKitError('The thumbnail must be an image.')
	if (details.get('size') or 0) > limit_mb * 1024 * 1024:
		raise ImageKitError(f"{'Video' if kind == 'video' else 'Thumbnail'} must be smaller than {limit_mb}MB.")
	if not (details.get('url') or '').startswith('https://') and not getattr(settings, 'IMAGEKIT_ALLOW_HTTP', False):
		raise ImageKitError('ImageKit returned an unexpected address.')
	return details


def streaming_enabled():
	"""Adaptive streaming and ImageKit-made thumbnails use ImageKit's
	video processing units (500 a month on the free plan, and 5 stream
	sizes per video use them up fast). Off unless .env says
	IMAGEKIT_ADAPTIVE_STREAMING=1 — e.g. switch it on for a demo."""
	return bool(getattr(settings, 'IMAGEKIT_ADAPTIVE_STREAMING', False))


def original_url(video_url):
	"""The uploaded file exactly as it is: ImageKit does no processing,
	so it never uses video processing units. Seeking works (Range)."""
	if not video_url:
		return ''
	return f"{video_url}{'&' if '?' in video_url else '?'}tr=orig-true"


def stream_url(video_url):
	"""Adaptive bitrate (HLS) stream of an ImageKit video — only when switched on."""
	if not video_url or not streaming_enabled():
		return ''
	return f'{video_url}/ik-master.m3u8?tr={STREAM_SIZES}'


def auto_thumbnail_url(video_url):
	"""A thumbnail ImageKit generates from the video itself — only when
	streaming is switched on (it uses processing units too). Otherwise
	the browser makes the thumbnail at upload time (video-upload.js)."""
	if not video_url or not streaming_enabled():
		return ''
	return f'{video_url}/ik-thumbnail.jpg?tr=w-1920,c-at_max,q-{PHOTO_QUALITY}'


# ---------------------------------------------------------------------
# Photos: sharp, right-sized copies made by ImageKit
#
# A photo is stored on ImageKit once, at full size. Each screen then asks
# for the size it needs (srcset): a phone gets ~1080px, a big screen up
# to 2048px, the photo viewer the largest — never bigger than the
# original (c-at_max), at high quality, and in WebP/AVIF when the browser
# supports it (ImageKit's automatic format, on by default).
# ---------------------------------------------------------------------
PHOTO_WIDTHS = (480, 720, 1080, 1440, 2048)
PHOTO_QUALITY = 90
FULL_WIDTH = 2560


def sized_image_url(image_url, width=1280, quality=PHOTO_QUALITY):
	"""An ImageKit image at `width` px wide (never upscaled), high quality,
	served as WebP/AVIF where the browser supports it."""
	if not image_url:
		return ''
	return f"{image_url}{'&' if '?' in image_url else '?'}tr=w-{width},c-at_max,q-{quality}"


def srcset(image_url, widths=PHOTO_WIDTHS):
	"""The srcset attribute for an ImageKit photo: one URL per width, so
	the browser picks the sharpest one the screen needs (retina included)."""
	if not image_url:
		return ''
	return ', '.join(f'{sized_image_url(image_url, w)} {w}w' for w in widths)


def _multipart(fields, file_field, filename, content, content_type):
	boundary = uuid.uuid4().hex
	lines = []
	for name, value in fields.items():
		lines += [f'--{boundary}', f'Content-Disposition: form-data; name="{name}"', '', str(value)]
	head = '\r\n'.join(lines + [
		f'--{boundary}',
		f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"',
		f'Content-Type: {content_type}', '', '',
	]).encode()
	return boundary, head + content + f'\r\n--{boundary}--\r\n'.encode()


def upload_image(uploaded_file, folder=PHOTO_FOLDER):
	"""Sends a photo the student uploaded to Django on to ImageKit (server
	side, with the private key). Returns ImageKit's details: fileId, url,
	width, height, size... Raises ImageKitError if ImageKit can't take it
	— the caller then keeps the photo on this server instead."""
	if not enabled():
		raise ImageKitError('ImageKit is not configured.')
	uploaded_file.seek(0)
	content = uploaded_file.read()
	uploaded_file.seek(0)
	name = re.sub(r'[^A-Za-z0-9._-]+', '_', getattr(uploaded_file, 'name', '') or 'photo.jpg')[-80:] or 'photo.jpg'
	boundary, body = _multipart(
		{'fileName': name, 'folder': folder, 'useUniqueFileName': 'true'},
		'file', name, content, getattr(uploaded_file, 'content_type', '') or 'application/octet-stream',
	)
	auth = base64.b64encode(f'{settings.IMAGEKIT_PRIVATE_KEY}:'.encode()).decode()
	req = urllib.request.Request(upload_url(), data=body, method='POST', headers={
		'Authorization': f'Basic {auth}', 'Accept': 'application/json',
		'Content-Type': f'multipart/form-data; boundary={boundary}',
	})
	try:
		with urllib.request.urlopen(req, timeout=60) as resp:
			details = json.loads(resp.read() or b'{}')
	except urllib.error.HTTPError as e:
		raise ImageKitError(f'ImageKit answered {e.code}.') from e
	except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
		raise ImageKitError("Couldn't reach ImageKit.") from e
	if not _FILE_ID.match(details.get('fileId') or ''):
		raise ImageKitError('ImageKit returned an unexpected answer.')
	if not (details.get('url') or '').startswith('https://') and not getattr(settings, 'IMAGEKIT_ALLOW_HTTP', False):
		raise ImageKitError('ImageKit returned an unexpected address.')
	return details


def upload_images(files, folder=PHOTO_FOLDER):
	"""upload_image() for several photos at once (in parallel, so four
	photos take about as long as one). Returns a list with ImageKit's
	details for each photo, or None for any that couldn't be uploaded."""
	from concurrent.futures import ThreadPoolExecutor
	import logging

	def one(f):
		try:
			return upload_image(f, folder)
		except ImageKitError as e:
			logging.getLogger(__name__).warning('Photo kept on this server (ImageKit: %s)', e)
			return None
	files = list(files)
	if not files:
		return []
	if len(files) == 1:
		return [one(files[0])]
	with ThreadPoolExecutor(max_workers=min(4, len(files))) as pool:
		return list(pool.map(one, files))
