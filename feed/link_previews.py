"""Link preview cards: when a post has a web link in it, the card under the
post shows the page's title, summary and picture (like X and WhatsApp).

attach(post) is called when a post is made or edited (feed/views.py). It
finds the first http(s) link in the text and reads that page once — the
result is kept in LinkPreview, so the same link is never fetched twice.

Reading other websites from the server needs care, so fetch() only:
  * opens http and https addresses on the public internet — never this
    computer, the local network or other private addresses (checked again
    on every redirect), so a post can't make the server look at itself;
  * waits at most a few seconds and reads at most 512 KB;
  * reads HTML pages, and keeps only the text of a few tags (no scripts run).
The picture itself is not downloaded: the card shows it from its own site.

If anything goes wrong the post is made as usual, just without a card.
"""
import ipaddress
import re
import socket
import urllib.request
from html import unescape
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit

from django.conf import settings

from .models import LinkPreview

URL_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)
TIMEOUT = 4
MAX_BYTES = 512 * 1024
USER_AGENT = 'UniConnectBot/1.0 (link previews)'


def first_link(text):
	m = URL_RE.search(text or '')
	if not m:
		return ''
	return m.group(0).rstrip('.,;:!?)]}\'"')


def _public_host(host):
	"""True if every address `host` resolves to is on the public internet."""
	if getattr(settings, 'LINK_PREVIEW_ALLOW_PRIVATE', False):
		return True
	try:
		infos = socket.getaddrinfo(host, None)
	except (socket.gaierror, UnicodeError):
		return False
	for info in infos:
		ip = ipaddress.ip_address(info[4][0].split('%')[0])
		if not ip.is_global or ip.is_multicast:
			return False
	return bool(infos)


def _allowed(url):
	parts = urlsplit(url)
	return parts.scheme in ('http', 'https') and parts.hostname and _public_host(parts.hostname)


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
	def redirect_request(self, req, fp, code, msg, headers, newurl):
		if not _allowed(newurl):
			raise URLError('redirect to a non-public address')
		return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Meta(HTMLParser):
	def __init__(self):
		super().__init__(convert_charrefs=True)
		self.meta, self.title, self._in_title = {}, '', False

	def handle_starttag(self, tag, attrs):
		a = {k.lower(): (v or '') for k, v in attrs}
		if tag == 'meta':
			key = (a.get('property') or a.get('name') or '').lower()
			if key and 'content' in a and key not in self.meta:
				self.meta[key] = a['content']
		elif tag == 'title':
			self._in_title = True

	def handle_endtag(self, tag):
		if tag == 'title':
			self._in_title = False
		if tag == 'head':
			raise StopIteration      # everything we need is in <head>

	def handle_data(self, data):
		if self._in_title and len(self.title) < 300:
			self.title += data


def _clean(text, limit):
	text = ' '.join(unescape(text or '').split())
	return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def fetch(url):
	"""{'title', 'description', 'image_url', 'site_name'} for a page, or None."""
	if not _allowed(url):
		return None
	opener = urllib.request.build_opener(_CheckedRedirects)
	req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html'})
	try:
		with opener.open(req, timeout=TIMEOUT) as resp:
			if 'html' not in (resp.headers.get('Content-Type') or '').lower():
				return None
			final = resp.geturl()
			charset = resp.headers.get_content_charset() or 'utf-8'
			html = resp.read(MAX_BYTES).decode(charset, errors='replace')
	except (URLError, OSError, ValueError):
		return None
	parser = _Meta()
	try:
		parser.feed(html)
	except StopIteration:
		pass
	except Exception:          # badly broken HTML: use what was read
		pass
	m = parser.meta
	title = m.get('og:title') or m.get('twitter:title') or parser.title
	desc = m.get('og:description') or m.get('twitter:description') or m.get('description')
	image = m.get('og:image') or m.get('og:image:url') or m.get('twitter:image') or ''
	image = urljoin(final, image.strip()) if image else ''
	if urlsplit(image).scheme not in ('http', 'https'):
		image = ''
	if not title:
		return None
	return {
		'title': _clean(title, 200), 'description': _clean(desc, 300),
		'image_url': image[:500], 'site_name': _clean(m.get('og:site_name'), 80),
	}


def preview_for(url):
	"""The saved LinkPreview for `url`, reading the page the first time."""
	if not url or len(url) > 500:
		return None
	found = LinkPreview.objects.filter(url=url).first()
	if found is None:
		data = fetch(url)
		found, _ = LinkPreview.objects.update_or_create(url=url, defaults=dict(data or {}, ok=bool(data)))
	return found if found.ok else None


def attach(post):
	"""Sets post.link_preview from the first link in its text (or clears it)."""
	from .models import Post
	url = first_link(post.content)
	preview = preview_for(url) if url else None
	if (preview.pk if preview else None) != post.link_preview_id:
		Post.all_objects.filter(pk=post.pk).update(link_preview=preview)
		post.link_preview = preview
	return preview
