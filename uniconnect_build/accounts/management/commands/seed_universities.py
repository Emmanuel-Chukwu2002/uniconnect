from django.core.management.base import BaseCommand

from accounts.models import University, Faculty, Department, Level

# A starter list of well-known Nigerian universities. Email domains are
# the generally known official ones — double-check any that matter for
# your specific demo via Django admin, since these occasionally change
# and it's easy to correct a single field there.
UNIVERSITIES = [
	("University of Nigeria, Nsukka", "UNN", "unn.edu.ng"),
	("University of Lagos", "UNILAG", "unilag.edu.ng"),
	("Obafemi Awolowo University", "OAU", "oauife.edu.ng"),
	("University of Ibadan", "UI", "ui.edu.ng"),
	("Ahmadu Bello University", "ABU", "abu.edu.ng"),
	("University of Port Harcourt", "UNIPORT", "uniport.edu.ng"),
	("University of Benin", "UNIBEN", "uniben.edu"),
	("Nnamdi Azikiwe University", "UNIZIK", "unizik.edu.ng"),
	("Lagos State University", "LASU", "lasu.edu.ng"),
	("Bayero University Kano", "BUK", "buk.edu.ng"),
	("University of Ilorin", "UNILORIN", "unilorin.edu.ng"),
	("Federal University of Technology, Akure", "FUTA", "futa.edu.ng"),
	("Federal University of Technology, Minna", "FUTMINNA", "futminna.edu.ng"),
	("Covenant University", "CU", "covenantuniversity.edu.ng"),
	("Delta State University", "DELSU", "delsu.edu.ng"),
	("Imo State University", "IMSU", "imsu.edu.ng"),
	("Ladoke Akintola University of Technology", "LAUTECH", "lautech.edu.ng"),
	("Federal University of Agriculture, Abeokuta", "FUNAAB", "funaab.edu.ng"),
	("University of Uyo", "UNIUYO", "uniuyo.edu.ng"),
	("Ekiti State University", "EKSU", "eksu.edu.ng"),
]

# Every seeded university gets this same faculty/department/level
# structure, so registration works end-to-end no matter which one a
# tester picks. Feel free to customize per-university later via admin.
FACULTY_STRUCTURE = {
	"Faculty of Science": ["Computer Science", "Mathematics", "Physics"],
	"Faculty of Engineering": ["Electrical Engineering", "Mechanical Engineering", "Civil Engineering"],
	"Faculty of Arts": ["English", "History"],
	"Faculty of Social Sciences": ["Economics", "Political Science"],
	"Faculty of Law": ["Law"],
}

LEVELS = [(100, "100 Level"), (200, "200 Level"), (300, "300 Level"), (400, "400 Level"), (500, "500 Level")]


class Command(BaseCommand):
	help = "Seeds a starter list of Nigerian universities, each with a full faculty/department/level structure."

	def handle(self, *args, **options):
		uni_count = 0
		for name, short_name, domain in UNIVERSITIES:
			uni, created = University.objects.get_or_create(
				name=name,
				defaults={
					"short_name": short_name,
					"email_domain": domain,
					"matric_format_hint": "CSC/2021/045",
				},
			)
			if created:
				uni_count += 1

			for faculty_name, department_names in FACULTY_STRUCTURE.items():
				faculty, _ = Faculty.objects.get_or_create(university=uni, name=faculty_name)
				for dept_name in department_names:
					dept, _ = Department.objects.get_or_create(faculty=faculty, name=dept_name)
					for order, level_name in LEVELS:
						Level.objects.get_or_create(department=dept, name=level_name, defaults={"order": order})

		self.stdout.write(self.style.SUCCESS(
			f"Done. {uni_count} new universities created "
			f"({University.objects.count()} total now in the database)."
		))
