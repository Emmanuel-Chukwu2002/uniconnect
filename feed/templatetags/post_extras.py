"""Template helpers for posts (load with {% load post_extras %})."""
import re
from types import SimpleNamespace

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils import timezone

register = template.Library()

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


@register.filter
def short_ago(value):
	"""X-style compact age for a post header: "now", "5m", "7h", "3d",
	then the date ("13 Oct", or "13 Oct 25" for an earlier year)."""
	if not value:
		return ''
	now = timezone.now()
	seconds = (now - value).total_seconds()
	if seconds < 60:
		return 'now'
	if seconds < 3600:
		return f'{int(seconds // 60)}m'
	if seconds < 86400:
		return f'{int(seconds // 3600)}h'
	if seconds < 7 * 86400:
		return f'{int(seconds // 86400)}d'
	local = timezone.localtime(value)
	if local.year == timezone.localtime(now).year:
		return f'{local.day} {MONTHS[local.month - 1]}'
	return f'{local.day} {MONTHS[local.month - 1]} {local:%y}'


@register.filter
def compact_count(value):
	"""Short counts for the video feed's buttons: 950, 1.2K, 17K, 2.3M."""
	try:
		n = int(value or 0)
	except (TypeError, ValueError):
		return value
	if n < 1000:
		return str(n)
	for size, unit in ((1_000_000, 'M'), (1_000, 'K')):
		if n >= size:
			v = n / size
			text = f'{v:.1f}' if v < 10 else f'{int(v)}'
			return text.rstrip('0').rstrip('.') + unit
	return str(n)


_HASHTAG = re.compile(r'(?<![\w&])#(\w{1,60})')


@register.filter
def with_hashtags(text):
	"""Escapes a caption, keeps its line breaks, and makes #tags stand out."""
	html = escape(text or '')
	html = _HASHTAG.sub(r'<span class="reel-tag">#\1</span>', html)
	return mark_safe(html.replace('\r\n', '\n').replace('\n', '<br>'))


@register.filter
def first_video(post):
	"""The post's video for the full-screen feed: its first video item, or
	the older single `video` file. Has .video_url, .stream_url, .poster_url."""
	for m in post.media_items.all():
		if m.is_video:
			return m
	if getattr(post, 'video', None):
		return SimpleNamespace(video_url=post.video.url, stream_url='', poster_url='')
	return None


@register.simple_tag(takes_context=True)
def post_poll(context, post):
	"""{% post_poll post as pp %} — the post's poll state for the card, or None."""
	try:
		poll = post.poll
	except Exception:   # no poll on this post
		return None
	if poll is None:
		return None
	from feed.polls import poll_state
	request = context.get('request')
	return poll_state(poll, getattr(request, 'user', None))


_POST_TOKEN = re.compile(r'(?P<url>https?://[^\s<>"\']+)|(?<![\w#&/])#(?P<tag>\w{2,50})|(?<![\w@])@(?P<user>[\w.\-]+)')
_TRAILING_TAGS = re.compile(r'(?:\s*(?<![\w#&/])#\w{2,50})+\s*$')


def _short_url(url):
	"""tutorialspoint.com/django… — a link as it's shown in a post."""
	text = re.sub(r'^https?://(www\.)?', '', url).rstrip('/')
	return text if len(text) <= 32 else text[:31] + '…'


@register.simple_tag
def body_and_tags(text):
	"""{% body_and_tags post.content as bt %}: the text without the #tags at its
	very end (bt.body) and those tags (bt.tags), for posts that show their tags
	as chips (community posts). Text that is only tags is left as it is."""
	text = text or ''
	m = _TRAILING_TAGS.search(text)
	if not m or not text[:m.start()].strip():
		return SimpleNamespace(body=text, tags=[])
	tags, seen = [], set()
	for t in re.findall(r'#(\w{2,50})', m.group(0)):
		if t.lower() not in seen:
			seen.add(t.lower())
			tags.append(t)
	return SimpleNamespace(body=text[:m.start()].rstrip(), tags=tags)


@register.filter
def post_text(text):
	"""A post's text for its card: escaped, line breaks kept, #tags linked
	to their hashtag page and @mentions of real accounts linked to the
	profile (one query, only when the post mentions someone)."""
	from django.contrib.auth import get_user_model
	from django.urls import reverse
	text = text or ''
	names = {}
	wanted = {m.group('user').rstrip('.').lower() for m in _POST_TOKEN.finditer(text) if m.group('user')}
	if wanted:
		for u in get_user_model().objects.filter(username__iregex=r'^(' + '|'.join(re.escape(w) for w in wanted) + r')$').values_list('username', flat=True):
			names[u.lower()] = u
	out, last = [], 0
	for m in _POST_TOKEN.finditer(text):
		if m.group('url'):
			url = m.group('url').rstrip('.,;:!?)]}\'"')
			start, end = m.start(), m.start() + len(url)
			link = f'<a href="{escape(url)}" class="post-link" target="_blank" rel="noopener noreferrer nofollow ugc">{escape(_short_url(url))}</a>'
		elif m.group('tag'):
			tag = m.group('tag')
			link = f'<a href="{reverse("hashtag", args=[tag.lower()])}" class="post-tag">#{escape(tag)}</a>'
			start, end = m.start(), m.end()
		else:
			raw = m.group('user')
			name = raw.rstrip('.')
			real = names.get(name.lower())
			if not real:
				continue
			link = f'<a href="{reverse("user_profile", args=[real])}" class="post-mention">@{escape(name)}</a>'
			start, end = m.start(), m.start() + 1 + len(name)
		out.append(escape(text[last:start]))
		out.append(link)
		last = end
	out.append(escape(text[last:]))
	html = ''.join(out).replace('\r\n', '\n').replace('\n', '<br>')
	return mark_safe(html)


@register.simple_tag(takes_context=True)
def with_page(context, number):
	"""This page's address with ?page= changed (pagination on the card pages)."""
	q = context['request'].GET.copy()
	q['page'] = number
	return '?' + q.urlencode()
