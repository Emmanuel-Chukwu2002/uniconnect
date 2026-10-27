"""
Serves uploaded files (MEDIA_ROOT) during development, with support for
HTTP Range requests.

Why: to jump to a point in a video (clicking the progress bar, skipping
forward or back), the browser asks for just that part of the file
("Range: bytes=…") and expects "206 Partial Content". Django's built-in
django.views.static.serve ignores Range and always sends the whole file,
so videos can't be seeked — the playhead snaps back. This view answers
Range requests properly and otherwise behaves like Django's.

Only used when DEBUG is on (see uniconnect/urls.py); in production a real
web server or ImageKit serves media, and both handle Range already.
"""
import mimetypes
import os
import re

from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.utils._os import safe_join
from django.views.static import serve as django_serve

RANGE_RE = re.compile(r'^bytes=(\d*)-(\d*)$')
CHUNK = 256 * 1024


def _file_chunks(path, start, length):
	with open(path, 'rb') as f:
		f.seek(start)
		remaining = length
		while remaining > 0:
			data = f.read(min(CHUNK, remaining))
			if not data:
				break
			remaining -= len(data)
			yield data


async def _file_chunks_async(path, start, length):
	# Under Daphne/ASGI, Django wants an async iterator for streaming.
	for data in _file_chunks(path, start, length):
		yield data


def serve_media(request, path, document_root=None):
	try:
		full_path = safe_join(document_root, path)
	except Exception:
		raise Http404('Not found')
	if not os.path.isfile(full_path):
		raise Http404('Not found')

	range_header = request.headers.get('Range', '').strip()
	match = RANGE_RE.match(range_header) if range_header else None
	if not match or request.method not in ('GET', 'HEAD'):
		# Whole file: Django's own view (Last-Modified / 304 handling), plus
		# the header that tells browsers they may ask for parts.
		response = django_serve(request, path, document_root=document_root)
		response['Accept-Ranges'] = 'bytes'
		return response

	size = os.path.getsize(full_path)
	first, last = match.groups()
	if first == '' and last == '':
		start, end = 0, size - 1
	elif first == '':                      # "bytes=-500": the last 500 bytes
		start, end = max(0, size - int(last)), size - 1
	else:
		start = int(first)
		end = min(int(last), size - 1) if last else size - 1
	if size == 0 or start >= size or start > end:
		response = HttpResponse(status=416)
		response['Content-Range'] = f'bytes */{size}'
		response['Accept-Ranges'] = 'bytes'
		return response

	length = end - start + 1
	content_type = mimetypes.guess_type(full_path)[0] or 'application/octet-stream'
	if start == 0 and end == size - 1:
		response = FileResponse(open(full_path, 'rb'), content_type=content_type, status=206)
	else:
		from django.core.handlers.asgi import ASGIRequest
		chunks = _file_chunks_async if isinstance(request, ASGIRequest) else _file_chunks
		response = StreamingHttpResponse(
			chunks(full_path, start, length) if request.method == 'GET' else iter(()),
			content_type=content_type, status=206,
		)
	response['Content-Length'] = str(length)
	response['Content-Range'] = f'bytes {start}-{end}/{size}'
	response['Accept-Ranges'] = 'bytes'
	return response
