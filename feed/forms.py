from django import forms

from accounts.models import StudentProfile
from . import imagekit
from .models import Event, Listing, Post, PostMedia, Story, Venue, validate_image_size


class MultipleFileInput(forms.ClearableFileInput):
	"""A FileInput that keeps the browser's native `multiple` attribute
	— Django's ClearableFileInput drops it by default, since a plain
	FileField normally expects one file."""
	allow_multiple_selected = True


class MultipleFileField(forms.FileField):
	"""A FileField that validates a *list* of uploaded files instead of
	just one. Each file still runs through FileField's own validators
	(extension, size) individually."""
	def __init__(self, *args, **kwargs):
		kwargs.setdefault('widget', MultipleFileInput())
		super().__init__(*args, **kwargs)

	def clean(self, data, initial=None):
		single_file_clean = super().clean
		if not data:
			return []
		if isinstance(data, (list, tuple)):
			return [single_file_clean(f, initial) for f in data]
		return [single_file_clean(data, initial)]


class PostForm(forms.ModelForm):
	"""A post is text plus, optionally, up to 4 photos OR a single video
	(never a mix, and never more than one video) — enforced in clean()
	below. The uploaded files aren't Post fields any more (see
	PostMedia); compose_post()/edit_post() turn
	cleaned_data['media'] into PostMedia rows after the post itself is
	saved."""
	media = MultipleFileField(required=False)
	# A video the browser already uploaded straight to ImageKit (and its
	# optional thumbnail): only the ImageKit file IDs come back here;
	# clean() asks ImageKit for the real details (feed/imagekit.py).
	ik_video_file_id = forms.CharField(required=False, max_length=64, widget=forms.HiddenInput())
	ik_thumbnail_file_id = forms.CharField(required=False, max_length=64, widget=forms.HiddenInput())
	# The thumbnail for a video stored on this server (no ImageKit).
	video_thumbnail = forms.ImageField(required=False, validators=[validate_image_size])
	# A poll (the composer's poll button): the post's text is the question,
	# 2-4 options of up to 25 characters, open for 1, 3 or 7 days.
	poll = forms.BooleanField(required=False)
	poll_option_1 = forms.CharField(required=False, max_length=25)
	poll_option_2 = forms.CharField(required=False, max_length=25)
	poll_option_3 = forms.CharField(required=False, max_length=25)
	poll_option_4 = forms.CharField(required=False, max_length=25)
	poll_days = forms.TypedChoiceField(required=False, coerce=int, empty_value=1, choices=[(1, '1 day'), (3, '3 days'), (7, '1 week')])
	# Composer extras (feed/scheduling.py): where you are, and posting later.
	location = forms.CharField(required=False, max_length=80)
	schedule_at = forms.DateTimeField(required=False, input_formats=['%Y-%m-%dT%H:%M'])

	def clean_location(self):
		return ' '.join((self.cleaned_data.get('location') or '').split())[:80]

	def clean_schedule_at(self):
		from .scheduling import check_time
		return check_time(self.cleaned_data.get('schedule_at'))

	class Meta:
		model = Post
		fields = ['content']

	def _check_imagekit_upload(self, cleaned, field, kind):
		file_id = (cleaned.get(field) or '').strip()
		if not file_id:
			return None
		if not imagekit.enabled():
			raise forms.ValidationError("Video uploads to ImageKit aren't set up on this server.")
		if PostMedia.objects.filter(**{'ik_file_id' if kind == 'video' else 'ik_thumbnail_file_id': file_id}).exists():
			raise forms.ValidationError('That upload is already attached to a post.')
		try:
			return imagekit.check_upload(file_id, kind)
		except imagekit.ImageKitError as e:
			raise forms.ValidationError(f"Couldn't attach your {kind}: {e}")

	# Overridden by PostEditForm so the same validation below works for
	# both "a brand new post" (nothing existing yet) and "editing a post
	# that already has media" without duplicating the rules.
	def existing_media(self):
		return PostMedia.objects.none()

	def removed_media_ids(self, cleaned):
		return set()

	def clean(self):
		cleaned = super().clean()
		content = (cleaned.get('content') or '').strip()
		new_files = cleaned.get('media') or []
		cleaned['ik_video'] = self._check_imagekit_upload(cleaned, 'ik_video_file_id', 'video')
		cleaned['ik_thumbnail'] = self._check_imagekit_upload(cleaned, 'ik_thumbnail_file_id', 'thumbnail')
		ik_video_count = 1 if cleaned['ik_video'] else 0

		removed_ids = self.removed_media_ids(cleaned)
		kept_existing = [m for m in self.existing_media() if m.id not in removed_ids]

		total_count = len(kept_existing) + len(new_files) + ik_video_count
		if not content and total_count == 0:
			raise forms.ValidationError("Say something, or attach a photo or video, before posting.")

		if total_count > 4:
			raise forms.ValidationError("A post can have up to 4 photos, or a single video — remove some and try again.")

		def is_video_file(f):
			return (f.content_type or '').startswith('video/')

		new_video_count = sum(1 for f in new_files if is_video_file(f)) + ik_video_count
		new_has_image = any(not is_video_file(f) for f in new_files)
		existing_has_video = any(m.is_video for m in kept_existing)
		existing_has_image = any(not m.is_video for m in kept_existing)

		has_video = new_video_count > 0 or existing_has_video
		has_image = new_has_image or existing_has_image

		if has_video and has_image:
			raise forms.ValidationError("A post can have photos or a video, not both — remove one and try again.")

		if new_video_count + (1 if existing_has_video else 0) > 1:
			raise forms.ValidationError("Only one video can be attached per post.")

		if (cleaned.get('ik_thumbnail') or cleaned.get('video_thumbnail')) and not new_video_count:
			raise forms.ValidationError("A thumbnail can only be added together with a new video.")

		cleaned['poll_options'] = []
		if cleaned.get('poll') and not self.instance.pk:
			options, seen = [], set()
			for i in range(1, 5):
				text = ' '.join((cleaned.get(f'poll_option_{i}') or '').split())
				if text and text.lower() not in seen:
					seen.add(text.lower())
					options.append(text)
			if not content:
				raise forms.ValidationError("Write your poll question in the post.")
			if len(options) < 2:
				raise forms.ValidationError("A poll needs at least 2 different choices.")
			if total_count:
				raise forms.ValidationError("A poll can't have photos or a video — remove them or the poll.")
			cleaned['poll_options'] = options
		return cleaned


class PostEditForm(PostForm):
	"""Same validation as PostForm, but also aware of the post's
	existing PostMedia rows — which ones stay counts toward the
	4-attachment / no-mixing rules above, and which ones get deleted is
	driven by remove_media_ids, a hidden input the frontend fills in as
	the user removes existing thumbnails from the edit page."""
	remove_media_ids = forms.CharField(required=False, widget=forms.HiddenInput())

	def existing_media(self):
		if not self.instance.pk:
			return PostMedia.objects.none()
		return self.instance.media_items.all()

	def removed_media_ids(self, cleaned):
		raw = cleaned.get('remove_media_ids') or ''
		ids = set()
		for part in raw.split(','):
			part = part.strip()
			if part.isdigit():
				ids.add(int(part))
		return ids


class ProfileEditForm(forms.ModelForm):
	# Not a StudentProfile field — it edits the related User's name,
	# split into first/last on save. Kept as a single input to match
	# how the name is shown everywhere else on the profile.
	name = forms.CharField(max_length=150, required=True)

	class Meta:
		model = StudentProfile
		fields = [
			'profile_photo', 'cover_photo', 'bio', 'location', 'website',
			'date_of_birth', 'show_date_of_birth',
		]
		widgets = {
			'bio': forms.Textarea(attrs={'rows': 2, 'maxlength': 160}),
			'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
			# Plain FileInput instead of ImageField's default
			# ClearableFileInput — the latter renders a "Currently: <link>
			# Clear" block we don't want, since the current photo is
			# already shown as the cover/avatar background image right
			# behind this input.
			'profile_photo': forms.FileInput(),
			'cover_photo': forms.FileInput(),
		}

	def __init__(self, *args, user=None, **kwargs):
		self.user = user
		super().__init__(*args, **kwargs)
		if self.user is not None and not self.is_bound:
			self.fields['name'].initial = self.user.get_full_name() or self.user.username
		self.order_fields([
			'name', 'profile_photo', 'cover_photo', 'bio', 'location',
			'website', 'date_of_birth', 'show_date_of_birth',
		])

		text_input_fields = ['name', 'bio', 'location', 'website']
		for field_name in text_input_fields:
			self.fields[field_name].required = field_name == 'name'
			self.fields[field_name].widget.attrs.update({'class': 'editprofile-input'})
		self.fields['date_of_birth'].widget.attrs.update({'class': 'editprofile-input'})
		self.fields['show_date_of_birth'].widget.attrs.update({'class': 'editprofile-toggle-input'})
		for photo_field in ('profile_photo', 'cover_photo'):
			self.fields[photo_field].widget.attrs.update({'class': 'editprofile-photo-input', 'accept': 'image/*'})

	def save(self, commit=True):
		profile = super().save(commit=False)
		if self.user is not None:
			full_name = self.cleaned_data.get('name', '').strip()
			first_name, _, last_name = full_name.partition(' ')
			self.user.first_name = first_name
			self.user.last_name = last_name
		if commit:
			if self.user is not None:
				self.user.save()
			profile.save()
		return profile


class EventForm(forms.ModelForm):
	"""The "Add Event" form on the Events page. organizer isn't a form
	field — the view sets it to request.user, same as Post.author."""
	class Meta:
		model = Event
		fields = ['title', 'category', 'date', 'time', 'location', 'capacity', 'price', 'image', 'description']
		widgets = {
			'title': forms.TextInput(attrs={'placeholder': 'e.g. Tech Conference 2026'}),
			'location': forms.TextInput(attrs={'placeholder': 'e.g. Main Auditorium'}),
			'date': forms.DateInput(attrs={'type': 'date'}),
			'time': forms.TimeInput(attrs={'type': 'time'}),
			'capacity': forms.NumberInput(attrs={'placeholder': 'Max attendees (optional)'}),
			'price': forms.NumberInput(attrs={'step': '0.01', 'placeholder': '0'}),
			'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'What is this event about?'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for name, field in self.fields.items():
			css = 'events-select' if name == 'category' else 'events-textarea' if name == 'description' else 'events-input'
			field.widget.attrs.update({'class': css})
			field.required = name not in ('time', 'capacity', 'price', 'image', 'description')


class ListingForm(forms.ModelForm):
	"""The "Sell an item" form on the Marketplace page. seller isn't a
	form field — the view sets it to request.user, same as
	Event.organizer. images (plural, optional multi-photo upload) isn't
	a Listing field either — it's turned into ListingImage rows by
	_create_listing_images() after the listing itself is saved, the
	same pattern PostForm.media uses for PostMedia."""
	images = MultipleFileField(required=False)

	class Meta:
		model = Listing
		fields = ['title', 'category', 'condition', 'price', 'quantity_available', 'location', 'description']
		widgets = {
			'title': forms.TextInput(attrs={'placeholder': 'e.g. Calculus textbook, 3rd edition'}),
			'price': forms.NumberInput(attrs={'step': '0.01', 'placeholder': '0'}),
			'quantity_available': forms.NumberInput(attrs={'placeholder': '1'}),
			'location': forms.TextInput(attrs={'placeholder': 'e.g. Hostel Block C, Room 12'}),
			'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe the item, its condition, why you\'re selling...'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for name, field in self.fields.items():
			css = 'events-select' if name in ('category', 'condition') else 'events-textarea' if name == 'description' else 'events-input'
			field.widget.attrs.update({'class': css})
			field.required = name not in ('location', 'description', 'images')


class VenueForm(forms.ModelForm):
	class Meta:
		model = Venue
		fields = ['name', 'address', 'venue_type', 'capacity']
		widgets = {
			'name': forms.TextInput(attrs={'placeholder': 'e.g. Main Auditorium'}),
			'address': forms.TextInput(attrs={'placeholder': 'Full address'}),
			'capacity': forms.NumberInput(attrs={'placeholder': 'Capacity (optional)'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for name, field in self.fields.items():
			css = 'events-select' if name == 'venue_type' else 'events-input'
			field.widget.attrs.update({'class': css})
			field.required = name != 'capacity'


class StoryForm(forms.ModelForm):
	"""A story is just a photo plus an optional caption. The image
	itself doesn't need a separate "is this really an image" check —
	Django's ImageField (both here and on the model) already rejects
	anything Pillow can't open as one, and Pillow is already a
	dependency of this project for every other photo upload
	(profile/cover photos, post photos, comment photos)."""
	class Meta:
		model = Story
		fields = ['image', 'caption']
		widgets = {
			'caption': forms.TextInput(attrs={
				'placeholder': 'Add a caption (optional)', 'maxlength': 200,
				'class': 'story-upload-caption-input',
			}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['image'].required = True
		self.fields['image'].widget.attrs.update({
			'accept': 'image/*', 'class': 'js-story-upload-input', 'hidden': True,
		})
