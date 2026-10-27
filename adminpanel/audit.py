"""The audit trail: every dashboard action calls log() (adminpanel.models.AdminLog)."""
from .models import AdminLog

LABELS = {
	'staff.create': 'Created a staff account',
	'staff.invite': 'Sent a staff invitation',
	'report.review': 'Started reviewing a report',
	'report.dismiss': 'Dismissed a report',
	'report.remove': 'Removed reported content',
	'content.remove': 'Removed content',
	'user.warn': 'Warned a user',
	'user.suspend': 'Suspended a user',
	'user.reactivate': 'Reactivated a user',
	'user.verify': 'Verified a student',
	'user.unverify': 'Removed verification',
	'user.clear_profile': 'Cleared a profile photo or bio',
	'university.create': 'Added a university',
	'university.update': 'Updated a university',
	'faculty.create': 'Added a faculty',
	'department.create': 'Added a department',
	'announcement.create': 'Published an announcement',
	'announcement.unpublish': 'Unpublished an announcement',
	'announcement.delete': 'Deleted an announcement',
	'role.assign': 'Assigned an admin role',
	'role.remove': 'Removed an admin role',
	'timetable.upload': 'Uploaded an official timetable',
	'timetable.delete': 'Removed an official class',
	'timetable.cancel': 'Cancelled an official class for one week',
	'timetable.move': 'Moved an official class for one week',
	'timetable.restore': 'Undid a change to an official class',
}


def log(actor, action, target_type='', target_id=None, label='', reason='', university=None):
	return AdminLog.objects.create(actor=actor, action=action, target_type=target_type, target_id=target_id,
		target_label=(label or '')[:200], reason=reason or '', university=university)


def describe(action):
	return LABELS.get(action, action.replace('.', ' ').replace('_', ' ').capitalize())
