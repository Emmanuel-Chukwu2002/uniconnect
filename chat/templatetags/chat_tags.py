from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def wa_time(value):
	"""Chat-list style time. The browser re-formats it in the viewer's
	own time zone (see data-ts in the templates); this is the fallback."""
	if not value:
		return ''
	local = timezone.localtime(value)
	today = timezone.localdate()
	if local.date() == today:
		return local.strftime('%I:%M %p').lstrip('0').lower()
	if (today - local.date()).days == 1:
		return 'Yesterday'
	return local.strftime('%d/%m/%Y')


@register.filter
def duration(seconds):
	seconds = int(seconds or 0)
	m, s = divmod(seconds, 60)
	h, m = divmod(m, 60)
	return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'
