from django import forms

from .models import Community, CommunityRule


class CommunityForm(forms.ModelForm):
	"""Create / edit a community. Rules are typed one per line and saved
	as CommunityRule rows (see save_rules)."""
	rules = forms.CharField(
		required=False, widget=forms.Textarea(attrs={'rows': 4}),
		help_text=f'One rule per line (up to {Community.MAX_RULES}).',
	)
	remove_banner = forms.BooleanField(required=False)
	remove_icon = forms.BooleanField(required=False)

	class Meta:
		model = Community
		fields = ['name', 'description', 'topic', 'join_policy', 'banner', 'icon', 'tags']
		widgets = {
			'icon': forms.FileInput(attrs={'accept': 'image/*'}),
			'description': forms.Textarea(attrs={'rows': 3}),
			'topic': forms.RadioSelect,
			'join_policy': forms.RadioSelect,
			'banner': forms.FileInput(attrs={'accept': 'image/*'}),
		}

	def __init__(self, *args, university=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.university = university
		self.fields['name'].widget.attrs.update({'maxlength': 60, 'autocomplete': 'off', 'placeholder': 'e.g. CSC 400 Level, Python Club, Hall 3'})
		self.fields['description'].widget.attrs.update({'maxlength': 500, 'placeholder': 'What is this community about? Who should join?'})
		self.fields['rules'].widget.attrs.update({'placeholder': 'Be kind and respectful\nKeep posts on topic\nNo spam or adverts'})
		if self.instance.pk and not self.is_bound:
			self.initial['rules'] = '\n'.join(r.text for r in self.instance.rules.all())

	def clean_name(self):
		name = ' '.join((self.cleaned_data.get('name') or '').split())
		if len(name) < 3:
			raise forms.ValidationError('Give your community a name of at least 3 characters.')
		# Communities are shared by every university, so names are unique
		# across UniConnect (join the existing "Programming" instead of
		# starting a second one).
		taken = Community.objects.filter(name__iexact=name)
		if self.instance.pk:
			taken = taken.exclude(pk=self.instance.pk)
		if taken.exists():
			raise forms.ValidationError('There is already a community with this name — search for it in Explore and join it.')
		return name

	def clean_description(self):
		text = (self.cleaned_data.get('description') or '').strip()
		if not text:
			raise forms.ValidationError('Tell people what this community is about.')
		return text

	def clean_tags(self):
		"""'python, Django ,web dev' -> 'python, Django, web dev' (no repeats)."""
		tags, seen = [], set()
		for raw in (self.cleaned_data.get('tags') or '').split(','):
			tag = ' '.join(raw.lstrip('#').split())
			if not tag or tag.lower() in seen:
				continue
			if len(tag) > Community.TAG_LENGTH:
				raise forms.ValidationError(f'Keep each tag under {Community.TAG_LENGTH} characters ("{tag[:24]}…").')
			seen.add(tag.lower())
			tags.append(tag)
		if len(tags) > Community.MAX_TAGS:
			raise forms.ValidationError(f'Up to {Community.MAX_TAGS} tags, please.')
		return ', '.join(tags)

	def clean_rules(self):
		lines = [' '.join(line.split()) for line in (self.cleaned_data.get('rules') or '').splitlines()]
		lines = [line for line in lines if line]
		if len(lines) > Community.MAX_RULES:
			raise forms.ValidationError(f'Up to {Community.MAX_RULES} rules, please.')
		for line in lines:
			if len(line) > 200:
				raise forms.ValidationError('Keep each rule under 200 characters.')
		return lines

	def save_rules(self, community):
		community.rules.all().delete()
		CommunityRule.objects.bulk_create(
			[CommunityRule(community=community, text=text, order=i) for i, text in enumerate(self.cleaned_data['rules'])]
		)
