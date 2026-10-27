import re

from django import forms

from accounts.models import Department
from .models import Book


class BookForm(forms.ModelForm):
	class Meta:
		model = Book
		fields = ['cover', 'title', 'author', 'category', 'condition', 'price', 'course_code', 'department',
				  'edition', 'description', 'meetup_spot', 'contact_phone']
		widgets = {
			'title': forms.TextInput(attrs={'placeholder': 'e.g. Introduction to Algorithms', 'autofocus': True}),
			'author': forms.TextInput(attrs={'placeholder': 'e.g. Thomas H. Cormen'}),
			'price': forms.NumberInput(attrs={'placeholder': '0', 'min': 0, 'step': 50, 'inputmode': 'numeric'}),
			'course_code': forms.TextInput(attrs={'placeholder': 'e.g. CSC 411'}),
			'edition': forms.TextInput(attrs={'placeholder': 'e.g. 3rd edition'}),
			'description': forms.Textarea(attrs={'rows': 4, 'placeholder': "What's inside, any highlights or missing pages, why you're selling…"}),
			'meetup_spot': forms.TextInput(attrs={'placeholder': 'e.g. Faculty of Science gate'}),
			'contact_phone': forms.TextInput(attrs={'placeholder': 'e.g. 0803 123 4567', 'inputmode': 'tel'}),
			'cover': forms.FileInput(attrs={'accept': 'image/*'}),
		}
		labels = {
			'cover': 'Cover photo', 'price': 'Price (₦)', 'course_code': 'Course code',
			'meetup_spot': 'Meet-up spot', 'contact_phone': 'Phone / WhatsApp',
		}

	def __init__(self, *args, user=None, **kwargs):
		super().__init__(*args, **kwargs)
		student = getattr(user, 'student_profile', None)
		depts = Department.objects.all()
		if student:
			depts = depts.filter(faculty__university=student.university)
			if not self.instance.pk:
				self.fields['department'].initial = student.department_id
		self.fields['department'].queryset = depts.order_by('name')
		self.fields['department'].empty_label = 'Any department'
		for name, field in self.fields.items():
			css = 'bs-input'
			if isinstance(field.widget, forms.Select):
				css = 'bs-input bs-select'
			field.widget.attrs['class'] = (field.widget.attrs.get('class', '') + ' ' + css).strip()

	def clean_contact_phone(self):
		phone = (self.cleaned_data.get('contact_phone') or '').strip()
		if phone and not re.fullmatch(r'\+?[\d\s\-()]{7,20}', phone):
			raise forms.ValidationError('Enter a phone number using digits only, e.g. 0803 123 4567.')
		return phone

	def clean_course_code(self):
		return re.sub(r'\s+', ' ', (self.cleaned_data.get('course_code') or '').strip().upper())
