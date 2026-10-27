"""
Sample books for the Bookshop, so it doesn't look empty in a demo:
textbooks, past questions, lecture notes, novels and more, listed by the
simulated sim_ students of your university (plus two of your own, so
"My books" has something in it), with some saves and views.

Usage:
    python manage.py seed_bookshop <your username>
    python manage.py seed_bookshop <your username> --undo    (removes them again)

Everything created is recorded in ml_data/demo_bookshop.json, which
--undo uses, so real listings are never touched.
"""
import io
import json
import random
import textwrap
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Department, StudentProfile
from bookshop.models import Book, BookSave, BookView

User = get_user_model()
RECORD = settings.BASE_DIR / 'ml_data' / 'demo_bookshop.json'

# (title, author, category, course code, price, condition, description)
BOOKS = [
	('Introduction to Algorithms', 'Thomas H. Cormen', 'textbook', 'CSC 311', 15000, 'good', 'Third edition. A few pencil notes in chapters 2–4, otherwise clean. The standard text for algorithms.'),
	('Operating System Concepts', 'Abraham Silberschatz', 'textbook', 'CSC 411', 12000, 'like_new', '9th edition, barely used. Covers processes, memory, file systems — everything for CSC 411.'),
	('Computer Networking: A Top-Down Approach', 'James F. Kurose', 'textbook', 'CSC 433', 11000, 'good', 'Great for the networking course and the lab. Cover slightly bent.'),
	('Database System Concepts', 'Silberschatz, Korth & Sudarshan', 'textbook', 'CSC 322', 9500, 'fair', 'Some highlighting, all pages intact.'),
	('Artificial Intelligence: A Modern Approach', 'Stuart Russell & Peter Norvig', 'textbook', 'CSC 421', 18000, 'new', 'Brand new, still in the wrapper. Bought two by mistake.'),
	('Discrete Mathematics and Its Applications', 'Kenneth H. Rosen', 'textbook', 'MTH 211', 8000, 'good', 'Solutions to odd-numbered exercises at the back. Very helpful for MTH 211.'),
	('Calculus: Early Transcendentals', 'James Stewart', 'textbook', 'MTH 101', 9000, 'good', 'Used for one semester. No missing pages.'),
	('Engineering Mathematics', 'K. A. Stroud', 'textbook', 'MTH 201', 7500, 'like_new', 'The classic Stroud — step-by-step examples for every topic.'),
	('Organic Chemistry', 'Paula Yurkanis Bruice', 'textbook', 'CHM 231', 10000, 'fair', 'Older edition but the content is the same. Some water marks on the cover.'),
	('Principles of Economics', 'N. Gregory Mankiw', 'textbook', 'ECO 101', 8500, 'good', 'Clear explanations, lots of examples. Perfect for 100 level.'),
	('Fundamentals of Physics', 'Halliday, Resnick & Walker', 'textbook', 'PHY 101', 13000, 'good', 'Volume 1 and 2 in one book. Light underlining.'),
	('Software Engineering', 'Ian Sommerville', 'textbook', 'CSC 341', 9000, 'new', 'Brand new 10th edition.'),
	('Statistics for Business and Economics', 'Paul Newbold', 'textbook', 'STA 211', 7000, 'good', 'Includes the formula sheet I made.'),
	('Communication in English', 'GST Unit', 'textbook', 'GST 111', 2500, 'new', 'The official GST 111 text. Brand new.'),
	('Nigerian Peoples and Culture', 'GST Unit', 'textbook', 'GST 112', 2000, 'good', 'Official GST 112 text, clean copy.'),
	('CSC 411 Past Questions (2015–2024)', 'Computer Science Students', 'past_questions', 'CSC 411', 1500, 'new', 'Ten years of past questions, neatly bound, with marking guides for 2019–2024.'),
	('MTH 101 Past Questions & Solutions', 'Mathematics Students\' Association', 'past_questions', 'MTH 101', 1200, 'good', 'Worked solutions for every question.'),
	('GST 111 Past Questions', 'GST Unit', 'past_questions', 'GST 111', 800, 'new', 'Objective and theory questions with answers.'),
	('Data Structures — Handwritten Notes', 'Chiamaka O.', 'lecture_notes', 'CSC 211', 1500, 'good', 'Complete, colour-coded notes from last session. Trees, graphs and hashing explained simply.'),
	('Thermodynamics Summary Notes', 'Engr. Okafor', 'lecture_notes', 'MEE 211', 1000, 'good', 'Short summary of every topic, great for revision.'),
	('Things Fall Apart', 'Chinua Achebe', 'novel', '', 2500, 'good', 'The African classic. Lightly read.'),
	('Purple Hibiscus', 'Chimamanda Ngozi Adichie', 'novel', '', 3000, 'like_new', 'Read once.'),
	('Half of a Yellow Sun', 'Chimamanda Ngozi Adichie', 'novel', '', 3500, 'good', 'Paperback in good shape.'),
	('Americanah', 'Chimamanda Ngozi Adichie', 'novel', '', 4000, 'new', 'Brand new paperback.'),
	('Arrow of God', 'Chinua Achebe', 'novel', '', 2000, 'fair', 'Old copy, spine worn but all pages there.'),
	('The Famished Road', 'Ben Okri', 'novel', '', 2800, 'good', 'Booker Prize winner. Good condition.'),
	('Atomic Habits', 'James Clear', 'self_help', '', 5000, 'like_new', 'Life-changing. Hardly any marks.'),
	('Rich Dad Poor Dad', 'Robert T. Kiyosaki', 'self_help', '', 3000, 'good', 'Popular finance classic.'),
	('Deep Work', 'Cal Newport', 'self_help', '', 4500, 'new', 'For anyone struggling to focus during exams.'),
	('IELTS Practice Tests', 'Cambridge English', 'professional', '', 6000, 'good', 'Answers filled in pencil — easy to rub off.'),
	('Financial Accounting Study Pack', 'ICAN', 'professional', '', 7000, 'like_new', 'Official ICAN study pack.'),
	('The Purpose Driven Life', 'Rick Warren', 'religious', '', 2500, 'good', 'Clean copy.'),
]
MINE = [
	('Python Crash Course', 'Eric Matthes', 'textbook', 'CSC 201', 6500, 'like_new', 'Beginner-friendly Python with projects. Hardly used.'),
	('Clean Code', 'Robert C. Martin', 'professional', '', 7000, 'good', 'Every programmer should read this.'),
]
PREFIX_DEPARTMENT = {
	'CSC': 'Computer Science', 'MTH': 'Mathematics', 'CHM': 'Chemistry', 'ECO': 'Economics', 'PHY': 'Physics',
	'STA': 'Statistics', 'MEE': 'Mechanical Engineering',
}
SPOTS = ['Faculty of Science gate', 'Main library entrance', 'Student Union Building', 'Hostel B lobby', 'ICT Centre',
		 'Faculty of Engineering car park', 'Chapel of Redemption', 'Abuja Hall junction']
PHOTO_COVERS = {'Atomic Habits', 'Things Fall Apart', 'Introduction to Algorithms', 'CSC 411 Past Questions (2015–2024)',
				'Americanah', 'Engineering Mathematics', 'Deep Work', 'Python Crash Course'}
PHOTO_COLOURS = [((240, 236, 227), (35, 35, 35)), ((20, 20, 20), (245, 197, 24)), ((176, 32, 45), (255, 255, 255)),
				 ((12, 74, 110), (255, 255, 255)), ((255, 140, 0), (20, 20, 20)), ((46, 125, 50), (255, 255, 255))]


class Command(BaseCommand):
	help = 'Fill the Bookshop with sample books for one user (and --undo to remove them).'

	def add_arguments(self, parser):
		parser.add_argument('username')
		parser.add_argument('--undo', action='store_true')

	def handle(self, *args, **opts):
		me = User.objects.filter(username=opts['username']).first()
		if not me:
			raise CommandError(f"No user '{opts['username']}'.")
		if opts['undo']:
			return self.undo()
		if RECORD.exists():
			self.stdout.write(self.style.WARNING('Removing the previous sample books first.'))
			self.undo()
		student = getattr(me, 'student_profile', None)
		if not student:
			raise CommandError(f'{me.username} has no student profile.')
		sellers = list(User.objects.filter(student_profile__university=student.university, username__startswith='sim_')
					   .exclude(pk=me.pk).select_related('student_profile')[:40])
		if len(sellers) < 5:
			sellers += list(User.objects.filter(student_profile__university=student.university).exclude(pk=me.pk)[:10])
		if not sellers:
			raise CommandError('No other students at this university (run: python manage.py generate_simulated_data).')
		depts = {d.name: d for d in Department.objects.filter(faculty__university=student.university)}
		rng = random.Random(42)
		now = timezone.now()
		ids = []
		with transaction.atomic():
			rows = [(b, rng.choice(sellers)) for b in BOOKS] + [(b, me) for b in MINE]
			for i, ((title, author, cat, code, price, cond, desc), seller) in enumerate(rows):
				dept = depts.get(PREFIX_DEPARTMENT.get(code[:3], '')) if code else None
				book = Book(seller=seller, title=title, author=author, category=cat, course_code=code, price=price,
							condition=cond, description=desc, department=dept,
							meetup_spot=rng.choice(SPOTS), contact_phone=rng.choice(['', '', f'080{rng.randint(10000000, 99999999)}']),
							edition=rng.choice(['', '', '2nd edition', '3rd edition', '2021 edition']) if cat == 'textbook' else '')
				if title in PHOTO_COVERS:
					book.cover.save(f'demo_{i}.png', ContentFile(self._cover(title, author, i)), save=False)
				book.save()
				Book.objects.filter(pk=book.pk).update(created_at=now - timedelta(hours=rng.randint(1, 24 * 20)))
				ids.append(book.pk)
			books = list(Book.objects.filter(pk__in=ids))
			for status, n in ((Book.STATUS_RESERVED, 2), (Book.STATUS_SOLD, 2)):
				for b in rng.sample([b for b in books if b.seller_id != me.pk and b.status == Book.STATUS_AVAILABLE], n):
					Book.objects.filter(pk=b.pk).update(status=status)
			others = sellers + [me]
			for b in books:
				for u in rng.sample(others, min(len(others), rng.randint(0, 9))):
					if u.pk != b.seller_id:
						BookView.objects.get_or_create(book=b, user=u)
				for u in rng.sample(sellers, min(len(sellers), rng.randint(0, 4))):
					if u.pk != b.seller_id:
						BookSave.objects.get_or_create(book=b, user=u)
			for b in rng.sample([b for b in books if b.seller_id != me.pk], 3):
				BookSave.objects.get_or_create(book=b, user=me)
		RECORD.parent.mkdir(parents=True, exist_ok=True)
		RECORD.write_text(json.dumps({'books': ids}, indent=2))
		self.stdout.write(self.style.SUCCESS(
			f'Added {len(ids)} books ({len(MINE)} of them yours, 3 saved by you). Open /bookshop/.\n'
			f'To remove them: python manage.py seed_bookshop {me.username} --undo'))

	def _cover(self, title, author, i):
		"""A simple printed-looking cover photo (for books that 'have a photo')."""
		from PIL import Image, ImageDraw, ImageFont
		bg, fg = PHOTO_COLOURS[i % len(PHOTO_COLOURS)]
		img = Image.new('RGB', (600, 900), bg)
		d = ImageDraw.Draw(img)
		big = small = None
		for bold, regular in (('arialbd.ttf', 'arial.ttf'), ('DejaVuSans-Bold.ttf', 'DejaVuSans.ttf'),
							  ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')):
			try:
				big, small = ImageFont.truetype(bold, 62), ImageFont.truetype(regular, 30)
				break
			except OSError:
				continue
		if big is None:
			try:
				big, small = ImageFont.load_default(size=58), ImageFont.load_default(size=30)
			except TypeError:  # very old Pillow
				big = small = ImageFont.load_default()
		d.rectangle([40, 40, 560, 860], outline=fg, width=4)
		y = 180
		for line in textwrap.wrap(title.upper(), 12)[:6]:
			w = d.textlength(line, font=big)
			d.text(((600 - w) / 2, y), line, fill=fg, font=big)
			y += 78
		d.line([220, y + 30, 380, y + 30], fill=fg, width=4)
		w = d.textlength(author, font=small)
		d.text(((600 - w) / 2, 760), author, fill=fg, font=small)
		buf = io.BytesIO()
		img.save(buf, 'PNG')
		return buf.getvalue()

	def undo(self):
		if not RECORD.exists():
			self.stdout.write('Nothing to undo.')
			return
		ids = json.loads(RECORD.read_text()).get('books', [])
		for b in Book.objects.filter(pk__in=ids):
			if b.cover:
				b.cover.delete(save=False)
			b.delete()
		RECORD.unlink()
		self.stdout.write(self.style.SUCCESS('Removed the sample books.'))
