"""Fills the Opportunities board with sample posts so you can see how it looks.

    python manage.py seed_opportunities           add the samples (safe to run again)
    python manage.py seed_opportunities --reset   remove the samples first, then add them

For every university that has students, it adds 16 sample opportunities
(every type: internships, jobs, scholarships, fellowships, competitions,
volunteering), shared by that university's students, with a mix of
deadlines: closing in a day or two, later this term, no deadline, and a
couple already closed. The organisations are made up, the application
links go to example.com, and every description says it is a sample, so
nobody mistakes them for real openings. --reset removes only these samples.
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import StudentProfile, University
from opportunities.models import Opportunity as O
from opportunities.models import OpportunitySave

MARK = 'Sample listing added by seed_opportunities.'

# (kind, title, organisation, location, remote, days to deadline or None, reward, who can apply, description)
SAMPLES = [
	(O.INTERNSHIP, 'Software Engineering Intern', 'Lagos Fintech Labs', 'Yaba, Lagos', False, 21, '₦150,000 a month',
	 '300–500 level Computer Science or Engineering students',
	 'Spend 3 months building payment features with our backend team (Python and Django). '
	 'You will pair with a mentor, ship real code and present a project at the end.'),
	(O.INTERNSHIP, 'Data Analytics Intern', 'Eastern Agro Data', 'Enugu', True, 5, '₦100,000 a month',
	 'Students who know Excel; Python or SQL is a plus',
	 'Help farmers make better decisions: clean crop data, build simple dashboards and write short reports for the field team.'),
	(O.INTERNSHIP, 'UI/UX Design Intern', 'Pixel Harbour Studio', 'Abuja', True, 30, '₦80,000 a month',
	 'Any department — send a portfolio (even class projects count)',
	 'Design screens for mobile apps used across West Africa. Figma experience helps; curiosity matters more.'),
	(O.INTERNSHIP, 'Electrical Engineering SIWES Placement', 'Northgrid Power Services', 'Kaduna', False, 12, 'SIWES allowance + transport',
	 '300–400 level Electrical/Electronic Engineering students',
	 'Six-month industrial training placement on substation maintenance and solar mini-grid installation.'),
	(O.JOB, 'Junior Frontend Developer (Part-time)', 'CampusCart', 'Remote', True, None, '₦120,000 a month',
	 'Final-year students and recent graduates',
	 'Work 20 hours a week on our student marketplace using HTML, CSS and JavaScript. Flexible hours around your lectures.'),
	(O.JOB, 'Campus Brand Ambassador', 'Chop Fast Foods', 'On campus', False, 9, 'Commission + monthly airtime',
	 'Outgoing students in any department',
	 'Represent the brand on campus: run small events, manage the class WhatsApp promos and gather feedback from students.'),
	(O.JOB, 'Research Assistant — Public Health Survey', 'Faculty of Medical Sciences', 'Teaching Hospital', False, 2, '₦60,000 for the project',
	 'Students who can speak Igbo or Hausa',
	 'Help collect and enter survey data for a four-week community health study. Training is provided before field work.'),
	(O.SCHOLARSHIP, 'Women in STEM Scholarship', 'Bright Futures Foundation', 'Nationwide', True, 4, '₦250,000 a year',
	 'Female students in Science, Technology, Engineering or Maths with CGPA 3.5+',
	 'Covers tuition support and a laptop. Apply with your transcript and a 500-word essay on a problem you want to solve.'),
	(O.SCHOLARSHIP, 'Undergraduate Merit Award 2026/27', 'Delta Heritage Trust', 'Nationwide', True, 45, '₦300,000 one-off',
	 '200–400 level students in any course with CGPA 4.0+',
	 'Awarded to 50 students each year based on grades and community service. Shortlisted students are interviewed online.'),
	(O.SCHOLARSHIP, 'Need-based Bursary', 'Alumni Association', 'On campus', False, None, 'Tuition support',
	 'Students who are struggling to pay fees',
	 'A confidential bursary run by alumni. Apply through the Students Affairs office or the link below at any time.'),
	(O.FELLOWSHIP, 'Africa Tech Leaders Fellowship', 'Savanna Tech Institute', 'Remote', True, 60, 'Stipend + mentorship',
	 'Final-year students and graduates under 25',
	 'A 6-month online fellowship: weekly classes on product, leadership and AI, a mentor from industry and a final team project.'),
	(O.FELLOWSHIP, 'Climate Action Fellowship', 'GreenRoots Nigeria', 'Port Harcourt', False, 18, '₦50,000 monthly stipend',
	 'Students in Environmental Science, Geography, Agriculture or Engineering',
	 'Lead a climate project in your community for one semester with funding, training and a network of other fellows.'),
	(O.COMPETITION, 'Inter-University Hackathon 2026', 'Computer Science Society', 'Main Auditorium', False, 3, '₦500,000 prize pool',
	 'Teams of 2–4 students from any department',
	 '48 hours to build something that helps students. Food, Wi-Fi and mentors provided. Register your team before the deadline.'),
	(O.COMPETITION, 'National Essay Competition: The Nigeria We Want', 'Young Voices Initiative', 'Online', True, 25, '₦200,000 + publication',
	 'All undergraduates',
	 'Write 1,500 words on one change that would improve life for young Nigerians. The best essays are published in a national magazine.'),
	(O.VOLUNTEER, 'Teach Kids to Code (Saturdays)', 'Code4Kids', 'Community schools near campus', False, None, 'Certificate + lunch',
	 'Students comfortable with basic programming',
	 'Spend Saturday mornings teaching Scratch and simple websites to secondary school students. No teaching experience needed.'),
	(O.VOLUNTEER, 'Blood Donation Drive Volunteers', 'Red Cross Campus Chapter', 'Health Centre', False, -3, '',
	 'Any healthy student',
	 'Help register donors and run the drive for one day. (This one has already closed — shown so you can see how closed ones look.)'),
]


class Command(BaseCommand):
	help = 'Adds sample opportunities for every university that has students (python manage.py seed_opportunities [--reset]).'

	def add_arguments(self, parser):
		parser.add_argument('--reset', action='store_true', help='Remove earlier samples first.')

	def handle(self, *args, **opts):
		samples = O.objects.filter(description__contains=MARK)
		if opts['reset']:
			n = samples.count()
			samples.delete()
			self.stdout.write(f'Removed {n} sample opportunities.')
		today = timezone.localdate()
		rng = random.Random(2026)
		added = 0
		for uni in University.objects.all():
			students = list(StudentProfile.objects.filter(university=uni, user__is_active=True).select_related('user'))
			if not students:
				continue
			for i, (kind, title, org, location, remote, days, reward, who, about) in enumerate(SAMPLES):
				if O.objects.filter(university=uni, title=title, description__contains=MARK).exists():
					continue
				opp = O.objects.create(
					university=uni, posted_by=rng.choice(students).user, kind=kind, title=title, organization=org,
					location=location, is_remote=remote, reward=reward, eligibility=who,
					description=f'{about}\n\n{MARK} The organisation is made up and the link goes to example.com.',
					deadline=(today + timedelta(days=days)) if days is not None else None,
					apply_url='https://example.com/apply', apply_email='' if i % 3 else 'opportunities@example.com',
				)
				# Spread "posted" times over the last few weeks so Newest has an order.
				O.objects.filter(pk=opp.pk).update(created_at=timezone.now() - timedelta(hours=rng.randint(1, 24 * 21)))
				# A few saves so the counts aren't all zero.
				for s in rng.sample(students, k=min(len(students), rng.randint(0, 4))):
					OpportunitySave.objects.get_or_create(user=s.user, opportunity=opp)
				added += 1
		self.stdout.write(self.style.SUCCESS(f'Added {added} sample opportunities. Open /opportunities/ to see them.'))
