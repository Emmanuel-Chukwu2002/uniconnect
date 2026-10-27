"""Fills Home's Today strip with samples so you can see how it works.

    python manage.py seed_today            add the samples (safe to run again)
    python manage.py seed_today --reset    remove the samples first, then add them

Adds, for every course:
  * a bank of "Question of the day" questions for its subject (from the course
    code: MTH, STA, COS/CSC, PHY, CHM, ECO, BIO, GST, MEE; general study questions otherwise)
  * two deadlines — an exam or test and an assignment — a few days to two weeks away,
    so the countdown rings show (one of them within 2 days, so it shows red)
  * a few classmates' answers to today's question, so the results have numbers
Samples are marked (deadline title ends with "· sample", questions explain "Sample question") so
--reset removes only those.
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from courses.models import Course, CourseEnrollment, DailyAnswer, DailyQuestion, Deadline

MARK = 'Sample question.'
DMARK = ' · sample'

# (question, a, b, c, d, correct, why)
BANKS = {
	'MTH': [
		('What is the derivative of x³?', '3x²', 'x²', '3x', 'x⁴/4', 'a', 'Power rule: d/dx xⁿ = n·xⁿ⁻¹.'),
		('If A is a 3×3 matrix with det(A) = 4, what is det(2A)?', '8', '12', '32', '64', 'c', 'det(kA) = kⁿ·det(A) = 2³ × 4 = 32.'),
		('Solve x² − 5x + 6 = 0.', 'x = 1, 6', 'x = 2, 3', 'x = −2, −3', 'x = 3, 5', 'b', '(x − 2)(x − 3) = 0.'),
		('∫ 1/x dx = ?', 'x⁻²', 'ln|x| + C', 'eˣ + C', '1/x² + C', 'b', 'The antiderivative of 1/x is ln|x|.'),
		('The eigenvalues of [[2,0],[0,5]] are…', '2 and 5', '0 and 7', '10 only', '2 and 0', 'a', 'A diagonal matrix has its diagonal entries as eigenvalues.'),
	],
	'STA': [
		('The mean of 2, 4, 6, 8 is…', '4', '5', '6', '20', 'b', '(2+4+6+8)/4 = 5.'),
		('A p-value of 0.03 at α = 0.05 means you…', 'Accept H₀', 'Reject H₀', 'Need a bigger α', 'Have a type II error', 'b', 'p < α, so the result is significant: reject H₀.'),
		('Which measure is least affected by outliers?', 'Mean', 'Range', 'Median', 'Variance', 'c', 'The median depends only on the middle value(s).'),
		('In a BIBD, λ(v − 1) equals…', 'r(k − 1)', 'b(k − 1)', 'v(r − 1)', 'bk', 'a', 'Each treatment meets the other v − 1 treatments λ times in its r blocks of k − 1 others.'),
		('Var(aX + b) = ?', 'aVar(X) + b', 'a²Var(X)', 'a²Var(X) + b', 'Var(X)', 'b', 'Adding a constant does not change the spread; scaling by a multiplies variance by a².'),
	],
	'COS': [
		('Which data structure works first-in, first-out?', 'Stack', 'Queue', 'Tree', 'Hash map', 'b', 'A queue removes items in the order they were added.'),
		('Binary search on a sorted list of n items takes…', 'O(n)', 'O(n log n)', 'O(log n)', 'O(1)', 'c', 'It halves the search space every step.'),
		('In SQL, which clause filters groups after GROUP BY?', 'WHERE', 'HAVING', 'ORDER BY', 'LIMIT', 'b', 'WHERE filters rows before grouping; HAVING filters the groups.'),
		('Which HTTP method should be safe and not change data?', 'POST', 'DELETE', 'GET', 'PUT', 'c', 'GET is a safe method — it only reads.'),
		('A balanced AVL tree with n nodes has height…', 'O(n)', 'O(log n)', 'O(1)', 'O(n²)', 'b', 'Rotations keep the tree balanced, so height stays logarithmic.'),
	],
	'PHY': [
		('The SI unit of force is the…', 'Joule', 'Watt', 'Newton', 'Pascal', 'c', '1 N = 1 kg·m/s².'),
		('An object in free fall near Earth accelerates at about…', '9.8 m/s²', '3.0 × 10⁸ m/s', '1 m/s²', '0 m/s²', 'a', 'g ≈ 9.8 m/s².'),
		('Ohm’s law states that V = …', 'I/R', 'IR', 'I²R', 'R/I', 'b', 'Voltage = current × resistance.'),
		('Which quantity is a vector?', 'Speed', 'Mass', 'Velocity', 'Energy', 'c', 'Velocity has both size and direction.'),
	],
	'CHM': [
		('The pH of pure water at 25 °C is…', '0', '7', '14', '1', 'b', 'Neutral water has [H⁺] = 10⁻⁷ mol/dm³.'),
		('How many moles are in 18 g of water (H₂O)?', '0.5', '1', '2', '18', 'b', 'Molar mass of H₂O ≈ 18 g/mol.'),
		('Which bond shares electrons between atoms?', 'Ionic', 'Covalent', 'Metallic', 'Hydrogen', 'b', 'Covalent bonds share electron pairs.'),
	],
	'ECO': [
		('When price rises and demand falls a lot, demand is…', 'Inelastic', 'Elastic', 'Unit elastic', 'Perfectly inelastic', 'b', 'A large response to price means elastic demand.'),
		('GDP measures…', 'A country’s total output', 'Government debt', 'Inflation', 'Exports only', 'a', 'Gross Domestic Product is the value of goods and services produced.'),
		('Opportunity cost is…', 'The money price', 'The next best alternative given up', 'A sunk cost', 'A tax', 'b', 'What you give up to choose something.'),
	],
	'BIO': [
		('The powerhouse of the cell is the…', 'Nucleus', 'Ribosome', 'Mitochondrion', 'Golgi body', 'c', 'Mitochondria make most of the cell’s ATP.'),
		('DNA bases pair as…', 'A–G, C–T', 'A–T, C–G', 'A–C, G–T', 'A–U, C–G', 'b', 'Adenine with thymine, cytosine with guanine.'),
	],
	'GST': [
		('A good thesis statement should be…', 'A question', 'Clear and arguable', 'A quotation', 'Very long', 'b', 'It states the main claim the essay will support.'),
		('Plagiarism means…', 'Citing sources', 'Using others’ work without credit', 'Paraphrasing with a citation', 'Writing a summary', 'b', 'Always credit the original author.'),
	],
	'MEE': [
		('A free-body diagram shows…', 'Only the weight', 'All external forces on a body', 'Internal stresses', 'The velocity', 'b', 'Every external force acting on the isolated body.'),
		('Torque is force times…', 'Mass', 'Perpendicular distance', 'Time', 'Velocity', 'b', 'τ = F × d (perpendicular distance from the pivot).'),
	],
	'': [
		('Which study method helps you remember longest?', 'Re-reading notes', 'Spaced practice testing', 'Highlighting', 'Cramming the night before', 'b', 'Testing yourself over spaced days beats re-reading.'),
		('Before an exam, the best first step is to…', 'Read everything again', 'Do past questions', 'Make new notes', 'Skip sleep', 'b', 'Past questions show the style and what is examined.'),
	],
}
ALIASES = {'CSC': 'COS', 'CIT': 'COS', 'MAT': 'MTH', 'STAT': 'STA', 'CHE': 'CHM', 'EEE': 'MEE', 'CVE': 'MEE', 'BCH': 'BIO', 'MCB': 'BIO'}


def bank_for(code):
	prefix = ''.join(ch for ch in code.upper() if ch.isalpha())
	prefix = ALIASES.get(prefix, prefix)
	return BANKS.get(prefix) or BANKS['']


class Command(BaseCommand):
	help = 'Adds sample deadlines and questions of the day (python manage.py seed_today [--reset]).'

	def add_arguments(self, parser):
		parser.add_argument('--reset', action='store_true', help='Remove earlier samples first.')

	def handle(self, *args, **opts):
		if opts['reset']:
			n = DailyQuestion.objects.filter(explanation__startswith=MARK).delete()[0]
			m = Deadline.objects.filter(title__endswith=DMARK).delete()[0]
			self.stdout.write(f'Removed {n} sample questions and {m} sample deadlines.')
		rng = random.Random(2026)
		now = timezone.localtime()
		q_added = d_added = 0
		for course in Course.objects.all():
			if not DailyQuestion.objects.filter(course=course, explanation__startswith=MARK).exists():
				for text, a, b, c, d, right, why in bank_for(course.code):
					DailyQuestion.objects.create(course=course, text=text, option_a=a, option_b=b, option_c=c, option_d=d,
						correct=right, explanation=f'{MARK} {why}')
					q_added += 1
			if not Deadline.objects.filter(course=course, title__endswith=DMARK).exists():
				soon = rng.choice([1, 2, 3, 5])
				later = rng.choice([7, 9, 11, 13])
				first = now.replace(hour=rng.choice([9, 10, 14]), minute=0, second=0, microsecond=0) + timedelta(days=soon)
				second = now.replace(hour=23, minute=59, second=0, microsecond=0) + timedelta(days=later)
				exam_kind = rng.choice([Deadline.TEST, Deadline.EXAM])
				Deadline.objects.create(course=course, kind=exam_kind, due_at=first,
					title=('Mid-semester test' if exam_kind == Deadline.TEST else 'First semester exam') + DMARK)
				Deadline.objects.create(course=course, kind=Deadline.ASSIGNMENT, due_at=second, title='Assignment 2' + DMARK)
				d_added += 2
			# Some classmates have already answered today's question, so results have numbers.
			from courses.today import question_for
			q = question_for(course, now.date())
			if q:
				students = [e.user for e in CourseEnrollment.objects.filter(course=course).select_related('user') if not e.user.last_login]
				keys = [k for k, _ in q.options]
				for u in students[:12]:
					choice = q.correct if rng.random() < 0.6 else rng.choice(keys)
					DailyAnswer.objects.get_or_create(question=q, user=u, day=now.date(), defaults={'choice': choice})
		self.stdout.write(self.style.SUCCESS(f'Added {q_added} questions and {d_added} deadlines. Open Home to see the Today strip.'))
