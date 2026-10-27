from django import template
from django.template.defaultfilters import filesizeformat

from feed.notifications import time_ago

register = template.Library()


@register.filter
def ago(dt):
	"""'just now', '5 minutes ago', '2 days ago'."""
	return time_ago(dt) if dt else ''


@register.filter
def size(n):
	return filesizeformat(n or 0)


@register.filter
def compact(n):
	"""986 → '986', 1234 → '1.2k', 2400 → '2.4k', 1500000 → '1.5M'."""
	try:
		n = int(n)
	except (TypeError, ValueError):
		return n
	for size, suffix in ((1_000_000, 'M'), (1_000, 'k')):
		if n >= size:
			v = f'{n / size:.1f}'.rstrip('0').rstrip('.')
			return f'{v}{suffix}'
	return str(n)
