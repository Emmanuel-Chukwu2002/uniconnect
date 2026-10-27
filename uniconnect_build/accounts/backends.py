from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .models import StudentProfile

User = get_user_model()


class MatricNumberBackend(ModelBackend):
	"""Authenticates a student using (university, matric_number, password)
	instead of Django's default global username. This is necessary because
	matric numbers are only unique *within* a university — the same string
	could legitimately belong to two different students at two different
	schools, so the university has to be part of the lookup."""

	def authenticate(self, request, university=None, matric_number=None, password=None, **kwargs):
		if not university or not matric_number or not password:
			return None

		try:
			profile = StudentProfile.objects.select_related('user').get(
				university=university,
				matric_number__iexact=matric_number,
			)
		except StudentProfile.DoesNotExist:
			return None

		user = profile.user
		if user.check_password(password) and self.user_can_authenticate(user):
			return user
		return None

	def get_user(self, user_id):
		try:
			return User.objects.get(pk=user_id)
		except User.DoesNotExist:
			return None
