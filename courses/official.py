"""The department's official timetable (OfficialClass).

A University Admin uploads it in the dashboard (/staff/timetable/,
adminpanel/views.py timetable) as a CSV file or an Excel (.xlsx) sheet with one
class per row:

    course_code, course_title, type, day, start, end, venue
    COS 401,     Data Structures, Lecture, Monday, 08:00, 10:00, LT 2

Only course_code, day, start and end are needed. A course that doesn't exist
yet at the university is created (it needs course_title then).

Every student taking a course (CourseEnrollment) gets a copy of its official
classes on their own timetable (ClassSlot.official), so Home, reminders and the
calendar export work for them with nothing to type:

  - on upload: copies are added, updated or removed to match
  - when a student adds the course later: they get its classes (signal below)
  - when they drop the course: its official classes leave their timetable
  - a student who removes one copy (they don't attend that class) keeps it
    removed (OfficialClassSkip)

The department can also cancel or move one week's official class
(change_official): every student's copy gets that change and a notification.
"""
import csv
import io
import re
import zipfile
from datetime import time
from xml.etree import ElementTree as ET

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import (ClassChange, ClassSlot, Course, CourseEnrollment, OfficialClass, OfficialClassSkip,
	normalise_code)

COLUMNS = ['course_code', 'course_title', 'type', 'day', 'start', 'end', 'venue']
TEMPLATE_ROWS = [
	['COS 401', 'Data Structures', 'Lecture', 'Monday', '08:00', '10:00', 'LT 2'],
	['COS 401', 'Data Structures', 'Practical', 'Wednesday', '14:00', '16:00', 'Computer Lab 1'],
	['MTH 401', 'Numerical Analysis', 'Lecture', 'Tuesday', '10:00', '12:00', 'Faculty Hall'],
]
MAX_ROWS = 2000

_DAYS = {d.lower(): i for i, d in enumerate(ClassSlot.DAYS)}
_DAYS.update({d[:3].lower(): i for i, d in enumerate(ClassSlot.DAYS)})
_DAYS.update({'tues': 1, 'wed': 2, 'thur': 3, 'thurs': 3})
_KINDS = {'lecture': ClassSlot.LECTURE, 'lec': ClassSlot.LECTURE, 'tutorial': ClassSlot.TUTORIAL,
	'tut': ClassSlot.TUTORIAL, 'practical': ClassSlot.PRACTICAL, 'lab': ClassSlot.PRACTICAL,
	'practical / lab': ClassSlot.PRACTICAL, 'other': ClassSlot.OTHER, '': ClassSlot.LECTURE}
_HEADERS = {'code': 'course_code', 'course': 'course_code', 'course code': 'course_code', 'course_code': 'course_code',
	'title': 'course_title', 'course title': 'course_title', 'course_title': 'course_title', 'type': 'type',
	'kind': 'type', 'day': 'day', 'start': 'start', 'starts': 'start', 'start time': 'start', 'end': 'end',
	'ends': 'end', 'end time': 'end', 'venue': 'venue', 'room': 'venue', 'location': 'venue'}


class UploadError(Exception):
	pass


def template_csv():
	out = io.StringIO()
	w = csv.writer(out)
	w.writerow(COLUMNS)
	w.writerows(TEMPLATE_ROWS)
	return out.getvalue()


# ---------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------

def _xlsx_rows(data):
	"""Rows of the first sheet of an .xlsx file, as lists of strings. Times typed
	in Excel are stored as fractions of a day; they come back as 'HH:MM'."""
	ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
	try:
		z = zipfile.ZipFile(io.BytesIO(data))
		shared = []
		if 'xl/sharedStrings.xml' in z.namelist():
			for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', ns):
				shared.append(''.join(t.text or '' for t in si.iter('{%s}t' % ns['m'])))
		sheets = sorted(n for n in z.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', n))
		root = ET.fromstring(z.read(sheets[0]))
	except (zipfile.BadZipFile, KeyError, IndexError, ET.ParseError):
		raise UploadError('That Excel file could not be read. Save it as .xlsx or CSV and try again.')
	rows = []
	for row in root.iter('{%s}row' % ns['m']):
		cells = {}
		for c in row.findall('m:c', ns):
			ref = re.match(r'([A-Z]+)', c.get('r', 'A'))
			col = 0
			for ch in ref.group(1):
				col = col * 26 + ord(ch) - 64
			t, v = c.get('t'), c.find('m:v', ns)
			if t == 's' and v is not None:
				val = shared[int(v.text)]
			elif t == 'inlineStr':
				val = ''.join(x.text or '' for x in c.iter('{%s}t' % ns['m']))
			elif v is not None:
				val = v.text or ''
				try:
					f = float(val)
					if 0 <= f < 1:                       # a time of day
						mins = round(f * 24 * 60)
						val = f'{mins // 60:02d}:{mins % 60:02d}'
					elif f == int(f):
						val = str(int(f))
				except ValueError:
					pass
			else:
				val = ''
			cells[col - 1] = val
		if cells:
			rows.append([cells.get(i, '') for i in range(max(cells) + 1)])
	return rows


def read_rows(upload):
	"""The uploaded file as a list of dicts with the COLUMNS keys."""
	name = (upload.name or '').lower()
	data = upload.read()
	if name.endswith('.xlsx'):
		rows = _xlsx_rows(data)
	elif name.endswith('.csv') or name.endswith('.txt'):
		try:
			text = data.decode('utf-8-sig')
		except UnicodeDecodeError:
			text = data.decode('latin-1')
		rows = list(csv.reader(io.StringIO(text)))
	else:
		raise UploadError('Upload a CSV file or an Excel (.xlsx) file.')
	rows = [r for r in rows if any((c or '').strip() for c in r)]
	if not rows:
		raise UploadError('The file is empty.')
	head = [_HEADERS.get(' '.join((h or '').strip().lower().replace('_', ' ').split()),
		_HEADERS.get((h or '').strip().lower())) for h in rows[0]]
	if 'course_code' not in head or 'day' not in head or 'start' not in head or 'end' not in head:
		raise UploadError('The first row must name the columns: course_code, course_title, type, day, start, end, venue. '
			'Download the template to see the layout.')
	out = []
	for r in rows[1:MAX_ROWS + 1]:
		out.append({k: (r[i].strip() if i < len(r) and r[i] else '') for i, k in enumerate(head) if k})
	if len(rows) - 1 > MAX_ROWS:
		raise UploadError(f'The file has more than {MAX_ROWS} classes. Split it into smaller files.')
	return out


def _parse_time(text):
	text = (text or '').strip().lower().replace('.', ':')
	m = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*(am|pm)?', text)
	if not m:
		return None
	h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
	if ap == 'pm' and h < 12:
		h += 12
	if ap == 'am' and h == 12:
		h = 0
	return time(h, mi) if h < 24 and mi < 60 else None


def check_rows(rows):
	"""(good rows, errors). Good rows have course_code, title, kind, day, start, end, venue."""
	good, errors = [], []
	for n, r in enumerate(rows, start=2):
		code = normalise_code(r.get('course_code', ''))
		day = _DAYS.get((r.get('day') or '').strip().lower())
		kind = _KINDS.get((r.get('type') or '').strip().lower())
		start, end = _parse_time(r.get('start')), _parse_time(r.get('end'))
		problem = None
		if not code:
			problem = 'no course code'
		elif day is None:
			problem = f'"{r.get("day")}" is not a day of the week'
		elif kind is None:
			problem = f'type "{r.get("type")}" should be Lecture, Tutorial, Practical or Other'
		elif not (start and end):
			problem = 'start and end must be times like 08:00 or 2:00 PM'
		elif end <= start:
			problem = 'the class ends before it starts'
		if problem:
			errors.append(f'Row {n}: {problem}.')
			continue
		good.append({'code': code, 'title': ' '.join((r.get('course_title') or '').split())[:120], 'kind': kind,
			'day': day, 'start': start, 'end': end, 'venue': ' '.join((r.get('venue') or '').split())[:80], 'row': n})
	return good, errors


# ---------------------------------------------------------------------
# Saving it and keeping students' copies in step
# ---------------------------------------------------------------------

def _copy_fields(o):
	return {'course_id': o.course_id, 'kind': o.kind, 'day': o.day, 'start': o.start, 'end': o.end, 'venue': o.venue}


def sync_copies(official):
	"""Make every enrolled student's copy of `official` match it. Returns copies added."""
	have = {s.user_id: s for s in ClassSlot.objects.filter(official=official)}
	skip = set(OfficialClassSkip.objects.filter(official=official).values_list('user_id', flat=True))
	users = CourseEnrollment.objects.filter(course_id=official.course_id).values_list('user_id', flat=True)
	fields = _copy_fields(official)
	new = [ClassSlot(user_id=u, official=official, title='', **fields) for u in users if u not in have and u not in skip]
	ClassSlot.objects.bulk_create(new)
	stale = [s.pk for s in have.values() if any(getattr(s, k) != v for k, v in fields.items())]
	if stale:
		ClassSlot.objects.filter(pk__in=stale).update(**fields)
	return len(new)


@transaction.atomic
def import_rows(university, rows, admin_user, department=None, replace=True):
	"""Save checked rows as the official timetable of their courses.
	replace=True: a course's official classes that aren't in the file are removed.
	Returns a summary dict."""
	from django.db.models import Q
	courses, created_courses, errors = {}, [], []
	for r in rows:
		if r['code'] in courses:
			continue
		course = Course.objects.filter(university=university, code__iexact=r['code']).first()
		if course is None:
			if not r['title']:
				errors.append(f'Row {r["row"]}: {r["code"]} is not a course at {university.short_name} yet. '
					'Add its course_title so it can be created.')
				courses[r['code']] = None
				continue
			course = Course.objects.create(university=university, code=r['code'], title=r['title'],
				department=department, created_by=admin_user)
			created_courses.append(course.code)
		courses[r['code']] = course
	added = updated = removed = 0
	kept = {}
	for r in rows:
		course = courses.get(r['code'])
		if course is None:
			continue
		o, made = OfficialClass.objects.get_or_create(course=course, kind=r['kind'], day=r['day'], start=r['start'],
			defaults={'end': r['end'], 'venue': r['venue'], 'uploaded_by': admin_user})
		if made:
			added += 1
		elif o.end != r['end'] or o.venue != r['venue']:
			o.end, o.venue, o.uploaded_by = r['end'], r['venue'], admin_user
			o.save()
			updated += 1
		kept.setdefault(course.pk, set()).add(o.pk)
	if replace and kept:
		q = Q()
		for course_id, ids in kept.items():
			q |= Q(course_id=course_id) & ~Q(pk__in=ids)
		gone = OfficialClass.objects.filter(q)
		removed = gone.count()
		gone.delete()               # students' copies go with them (CASCADE)
	copies = 0
	for o in OfficialClass.objects.filter(course_id__in=list(kept)):
		copies += sync_copies(o)
	students = CourseEnrollment.objects.filter(course_id__in=list(kept)).values('user_id').distinct().count()
	return {'added': added, 'updated': updated, 'removed': removed, 'courses': len(kept),
		'new_courses': created_courses, 'students': students, 'copies': copies, 'errors': errors}


def change_official(official, day, admin_user, cancel=True, new_date=None, new_start=None, new_end=None,
		new_venue='', note=''):
	"""Cancel or move one week's official class for every student taking it, and tell them."""
	from feed.models import Notification as N
	from feed.notifications import is_muted
	copies = list(ClassSlot.objects.filter(official=official).select_related('user'))
	n = 0
	for s in copies:
		values = {'status': ClassChange.CANCELLED, 'new_date': None, 'new_start': None, 'new_end': None, 'new_venue': ''} \
			if cancel else {'status': ClassChange.MOVED, 'new_date': new_date or day, 'new_start': new_start,
			'new_end': new_end, 'new_venue': new_venue}
		ClassChange.objects.update_or_create(slot=s, date=day, defaults={**values, 'note': note, 'set_by': admin_user})
		key = f'classchg:{s.pk}:{day.isoformat()}'
		N.objects.filter(recipient=s.user, type=N.CLASS_CHANGED, group_key=key).delete()
		if not is_muted(s.user, N.CLASS_CHANGED):
			N.objects.create(recipient=s.user, actor=admin_user, type=N.CLASS_CHANGED, class_slot=s, group_key=key)
		n += 1
	return n


def undo_official_change(official, day):
	from feed.models import Notification as N
	ids = list(ClassSlot.objects.filter(official=official).values_list('pk', flat=True))
	ClassChange.objects.filter(slot_id__in=ids, date=day).delete()
	N.objects.filter(type=N.CLASS_CHANGED, class_slot_id__in=ids, group_key__endswith=f':{day.isoformat()}').delete()


# Students who add or drop a course later.

@receiver(post_save, sender=CourseEnrollment)
def _enrolled(sender, instance, created, **kwargs):
	if not created:
		return
	skip = set(OfficialClassSkip.objects.filter(user_id=instance.user_id).values_list('official_id', flat=True))
	have = set(ClassSlot.objects.filter(user_id=instance.user_id, official__course_id=instance.course_id)
		.values_list('official_id', flat=True))
	ClassSlot.objects.bulk_create([ClassSlot(user_id=instance.user_id, official=o, title='', **_copy_fields(o))
		for o in OfficialClass.objects.filter(course_id=instance.course_id) if o.pk not in skip and o.pk not in have])


@receiver(post_delete, sender=CourseEnrollment)
def _dropped(sender, instance, **kwargs):
	ClassSlot.objects.filter(user_id=instance.user_id, official__course_id=instance.course_id).delete()
