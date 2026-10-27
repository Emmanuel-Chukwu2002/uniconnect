import os

from django import forms

from accounts.models import Level
from .models import GroupFile, GroupPost, StudyGroup

MAX_POLL_OPTIONS = 6


class StudyGroupForm(forms.ModelForm):
	class Meta:
		model = StudyGroup
		fields = ['group_type', 'privacy', 'name', 'photo', 'cover', 'course_code', 'level', 'description',
			'mode', 'schedule', 'place', 'meeting_link', 'max_members', 'rules', 'show_posts']
		labels = {'name': 'Group name', 'course_code': 'Course code', 'level': 'Level', 'mode': 'How you meet',
			'schedule': 'When', 'place': 'Where', 'meeting_link': 'Online meeting link', 'max_members': 'Member limit'}
		widgets = {
			'group_type': forms.RadioSelect,
			'privacy': forms.RadioSelect,
			'name': forms.TextInput(attrs={'placeholder': 'e.g. 400 Level, Final-year project team'}),
			'course_code': forms.TextInput(attrs={'placeholder': 'e.g. COS 401'}),
			'photo': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
			'cover': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
			'description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'What the group is for and who should join.'}),
			'schedule': forms.TextInput(attrs={'placeholder': 'e.g. Mondays & Thursdays, 4–6pm'}),
			'place': forms.TextInput(attrs={'placeholder': 'e.g. Faculty library, 2nd floor'}),
			'meeting_link': forms.URLInput(attrs={'placeholder': 'https://meet.google.com/…'}),
			'max_members': forms.NumberInput(attrs={'min': 2, 'max': StudyGroup.MAX_LIMIT, 'placeholder': 'No limit'}),
			'rules': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Be respectful\nKeep it about COS 401\nNo sharing of exam answers'}),
		}

	def __init__(self, *args, student=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['level'].queryset = Level.objects.filter(department=student.department) if student else Level.objects.none()
		self.fields['level'].empty_label = 'Any level'
		self.fields['mode'].choices = [('', "We don't meet up")] + list(StudyGroup.MODE_CHOICES)
		self.fields['course_code'].help_text = 'Academic groups only (optional).'
		self.fields['level'].help_text = 'Optional.'

	def clean_rules(self):
		lines = [' '.join(l.split()) for l in (self.cleaned_data.get('rules') or '').splitlines()]
		lines = [l for l in lines if l]
		if len(lines) > 15:
			raise forms.ValidationError('Up to 15 rules, please.')
		if any(len(l) > 200 for l in lines):
			raise forms.ValidationError('Keep each rule under 200 characters.')
		return '\n'.join(lines)

	def clean_course_code(self):
		return ' '.join(self.cleaned_data.get('course_code', '').upper().split())

	def clean_max_members(self):
		n = self.cleaned_data.get('max_members')
		if n is None:
			return None
		if not 2 <= n <= StudyGroup.MAX_LIMIT:
			raise forms.ValidationError(f'Choose between 2 and {StudyGroup.MAX_LIMIT}, or leave it empty for no limit.')
		if self.instance.pk:
			have = self.instance.members.filter(status='active').count()
			if n < have:
				raise forms.ValidationError(f'The group already has {have} members.')
		return n

	def clean(self):
		data = super().clean()
		if data.get('group_type') != StudyGroup.ACADEMIC:
			data['course_code'] = ''
		if not data.get('mode'):
			data['place'], data['meeting_link'] = '', ''
		elif data['mode'] == StudyGroup.IN_PERSON:
			data['meeting_link'] = ''
		elif data['mode'] == StudyGroup.ONLINE:
			data['place'] = ''
		return data


class GroupPostForm(forms.ModelForm):
	"""A post, an announcement, or a poll (the text is the question; the
	options come in as option_1 ... option_6)."""
	is_poll = forms.BooleanField(required=False)

	class Meta:
		model = GroupPost
		fields = ['title', 'body', 'image', 'is_announcement', 'poll_multiple']

	def __init__(self, *args, can_announce=False, has_files=False, **kwargs):
		super().__init__(*args, **kwargs)
		self.can_announce = can_announce
		self.has_files = has_files
		for i in range(1, MAX_POLL_OPTIONS + 1):
			self.fields[f'option_{i}'] = forms.CharField(max_length=100, required=False)

	def clean(self):
		data = super().clean()
		if not self.can_announce:
			data['is_announcement'] = False
		body = (data.get('body') or '').strip()
		data['body'] = body
		data['title'] = ' '.join((data.get('title') or '').split())
		options = []
		if data.get('is_poll'):
			seen = set()
			for i in range(1, MAX_POLL_OPTIONS + 1):
				text = ' '.join((data.get(f'option_{i}') or '').split())
				if text and text.lower() not in seen:
					seen.add(text.lower())
					options.append(text)
			if not body:
				raise forms.ValidationError('Write the poll question.')
			if len(options) < 2:
				raise forms.ValidationError('A poll needs at least two different options.')
		elif not body and not data.get('title') and not data.get('image') and not self.has_files:
			raise forms.ValidationError('Write something, or attach a photo, video or document.')
		else:
			data['poll_multiple'] = False
		self.options = options
		return data


class GroupFileForm(forms.ModelForm):
	class Meta:
		model = GroupFile
		fields = ['file']

	def save(self, commit=True):
		obj = super().save(commit=False)
		f = self.cleaned_data['file']
		obj.name = os.path.basename(f.name)[:150]
		obj.size = f.size
		if commit:
			obj.save()
		return obj
