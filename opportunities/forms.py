from django import forms

from .models import Opportunity


class OpportunityForm(forms.ModelForm):
	class Meta:
		model = Opportunity
		fields = ['kind', 'title', 'organization', 'location', 'is_remote', 'deadline', 'reward',
			'eligibility', 'description', 'apply_url', 'apply_email']
		labels = {
			'kind': 'Type', 'organization': 'Organisation', 'is_remote': 'Remote / online',
			'reward': 'Pay or award', 'apply_url': 'Application link', 'apply_email': 'Application email',
		}
		widgets = {
			'deadline': forms.DateInput(attrs={'type': 'date'}),
			'description': forms.Textarea(attrs={'rows': 7}),
			'title': forms.TextInput(attrs={'placeholder': 'e.g. Software Engineering Intern'}),
			'organization': forms.TextInput(attrs={'placeholder': 'e.g. Andela'}),
			'apply_url': forms.URLInput(attrs={'placeholder': 'https://'}),
			'is_remote': forms.CheckboxInput(attrs={'class': 'st-switch'}),
		}
