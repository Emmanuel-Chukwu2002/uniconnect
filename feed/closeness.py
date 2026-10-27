"""Shared bits for the card pages that group things closest-first, like
Who to follow (feed/people.py): Groups (studygroups/discover.py),
Opportunities (opportunities/discover.py) and Course Companion
(courses/discover.py).

Each of those builds sections, closest to you first — your class, your
department, your faculty, your university — shows 3 cards a section with
"See all", and puts faces of people you follow on each card.
Templates: feed/_pc_sections.html; styles: restyle.css ("Who to follow cards").
"""
from django.contrib.auth import get_user_model

from .models import Follow

PREVIEW = 3          # cards a section shows before "See all"
SECTION_PAGE = 24    # cards a page on a section's "See all"


def friend_ids(user):
	"""People you follow (accepted)."""
	return set(Follow.objects.filter(follower=user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True))


def attach_faces(items, people_of, friends, limit=2):
	"""For each item sets .known (how many people you follow are in it) and
	.faces (up to `limit` of them, as users with student_profile).
	`people_of` maps item pk -> list of user ids."""
	wanted = set()
	for item in items:
		ids = [u for u in people_of.get(item.pk, []) if u in friends]
		item.known = len(ids)
		item._face_ids = ids[:limit]
		wanted.update(item._face_ids)
	users = get_user_model().objects.select_related('student_profile').in_bulk(wanted)
	for item in items:
		item.faces = [users[u] for u in item._face_ids if u in users]
	return items


def hue(n):
	"""A steady colour for an item without a photo."""
	return (int(n) * 47) % 360


def split(items, rules):
	"""Puts each item in the first section whose test it passes.
	rules: [(key, title, subtitle, test)]; returns [(key, title, subtitle, [items])] with empty ones dropped."""
	buckets = {key: [] for key, *_ in rules}
	for item in items:
		for key, _, _, test in rules:
			if test(item):
				buckets[key].append(item)
				break
	return [(key, title, sub, buckets[key]) for key, title, sub, _ in rules if buckets[key]]


def overview(sections, prepare=lambda items: items):
	"""The page's groups: each with its first PREVIEW items and a total."""
	return [{'key': key, 'title': title, 'sub': sub, 'total': len(items), 'items': prepare(items[:PREVIEW])}
		for key, title, sub, items in sections]
