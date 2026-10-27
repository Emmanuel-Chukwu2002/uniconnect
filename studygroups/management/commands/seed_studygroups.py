"""Fills Groups with sample groups so you can see how they look.

    python manage.py seed_studygroups            add the samples (safe to run again)
    python manage.py seed_studygroups --reset    remove the samples first (and the old
                                                 study-group samples), then add them

For every university with at least two students it adds 12 study groups
(Algebra Warriors, Biology Lovers, …) with threads, comments and upvotes — you
join four of them — and 14 sample groups of
every type (Academic, Project, Departmental, Hostel, Social, Professional)
and privacy, each started by one of its students, with members, their group
chats in Messages, an announcement, a poll with votes, a post with comments,
and a couple of files in class and project groups.

Everyone at that university who has signed in at least once (so: you) is
added as a member of most samples, so their Posts and Files tabs show. One
sample is full and one has stopped taking members, so every badge shows.
Every sample says it is a sample in its description; --reset removes only those.
"""
import random

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from accounts.models import StudentProfile, University
from studygroups import chat
from studygroups.models import (GroupComment, GroupFile, GroupPollOption, GroupPollVote, GroupPost, GroupPostLike,
	StudyGroup as G, StudyGroupMember as M)

MARK = 'Sample group added by seed_studygroups.'

# type, privacy, course code, name, description, mode, schedule, place, limit, extras
#   extras: 'full' (no room left), 'closed' (not taking members), 'files' (add sample files)
SAMPLES = [
	(G.ACADEMIC, G.PUBLIC, 'COS 401', '400 Level', 'Class group for COS 401: announcements, assignments, lecture notes and questions.',
	 G.IN_PERSON, 'Lectures: Tuesdays 10am', 'LT 2', None, {'files'}),
	(G.ACADEMIC, G.PRIVATE, 'CSC 411', 'Exam prep — past questions', 'We go through past questions together, one topic a week. Bring your notes.',
	 G.IN_PERSON, 'Mondays & Thursdays, 4–6pm', 'Faculty library, 2nd floor', 12, {'files'}),
	(G.ACADEMIC, G.PUBLIC, 'MTH 201', 'Linear algebra problem sets', 'Weekly call to work through the assignment before it is due. Cameras optional.',
	 G.ONLINE, 'Wednesdays, 8–9pm', '', None, set()),
	(G.ACADEMIC, G.PUBLIC, 'ECO 202', 'Microeconomics reading group', 'Small group reading the textbook chapter by chapter. This one is full, so you can see a full group.',
	 G.IN_PERSON, 'Thursdays, 5pm', 'Social Sciences lounge', 4, {'full'}),
	(G.PROJECT, G.INVITE, '', 'Final-year project team — Smart Attendance', 'Our final-year project: a QR-code attendance system. Tasks, files and meeting notes live here.',
	 G.BOTH, 'Saturdays, 10am', 'Computer lab 3', 6, {'files'}),
	(G.PROJECT, G.PRIVATE, '', 'Hackathon squad: Team Byte', 'Preparing for the next campus hackathon. Designers and backend devs welcome — ask to join.',
	 G.ONLINE, 'Sundays, 7pm', '', 8, set()),
	(G.DEPARTMENTAL, G.PUBLIC, '', 'Computer Science Students', 'Everyone in the department: notices from the HOD, timetable changes and general questions.',
	 '', '', '', None, set()),
	(G.DEPARTMENTAL, G.PRIVATE, '', '300 Level Class Reps', 'Coordination between course reps and the level adviser.',
	 '', '', '', 15, set()),
	(G.HOSTEL, G.INVITE, '', 'Block C, Room 12', 'Roommates: cleaning rota, light bills and who is buying gas this month.',
	 '', '', '', 6, set()),
	(G.HOSTEL, G.PUBLIC, '', 'Eni Njoku Hall — Floor 2', 'Floor group for water and light updates, lost and found, and quiet hours.',
	 '', '', '', None, set()),
	(G.SOCIAL, G.PUBLIC, '', 'Campus Hangout — Friday games night', 'Board games, FIFA and suya every Friday. Everyone is welcome.',
	 G.IN_PERSON, 'Fridays, 7pm', 'Student Union Building', None, set()),
	(G.SOCIAL, G.PUBLIC, '', 'Weekend football', 'Five-a-side on Saturday mornings. Not taking new players this month.',
	 G.IN_PERSON, 'Saturdays, 7am', 'Sports complex, pitch B', 20, {'closed'}),
	(G.PROFESSIONAL, G.PUBLIC, '', 'UI/UX Design Team', 'Learning Figma together and giving each other feedback on real projects.',
	 G.ONLINE, 'Tuesdays, 8pm', '', 30, set()),
	(G.PROFESSIONAL, G.PUBLIC, '', 'Django Developers Circle', 'For students building with Python and Django. Share what you are building and get help.',
	 G.ONLINE, 'Every other Thursday, 8pm', '', None, set()),
]

# Study groups in the style of the Groups dashboard: (course code, name, about, you join it?, threads)
#   thread: (title, body, [comments])
STUDY = [
	('MTH 101', 'Algebra Warriors', 'We crack algebra together — quadratics, sequences, matrices. Post the question you are stuck on.', True, [
		('Quadratic equations: when to use the formula?', 'I am having problems in differential equations and quadratics. Can somebody help me? When do I factorise and when do I use the formula?',
		 ['Try factorising first; if it does not split nicely in 30 seconds, use the formula.', 'Check the discriminant first — it tells you what kind of roots to expect.']),
		('Past questions 2019–2023', 'Start with past questions from 2019–2023. Share your solutions here so we can compare.',
		 ['Uploaded my 2021 solutions.', 'Question 4 in 2022 is tricky — use completing the square.', 'Thanks, this helped!']),
	]),
	('BIO 101', 'Biology Lovers', 'Cells, genetics and everything alive. Diagrams welcome.', True, [
		('Mitosis vs meiosis — quick summary?', 'Can someone summarise the difference between mitosis and meiosis in a few lines?',
		 ['Mitosis: 2 identical cells. Meiosis: 4 different cells with half the chromosomes.', 'Draw the stages — it sticks better.']),
		('Practical on Thursday', 'Who has the manual for the microscope practical?', ['I have it, will drop it in Files.']),
	]),
	('MEE 201', 'Rockers of Mech', 'Mechanics, statics and dynamics — free-body diagrams every day.', True, [
		('Free-body diagram for a ladder', 'How do you draw the free-body diagram for a ladder leaning on a smooth wall?',
		 ['Normal force from the wall is horizontal, from the floor vertical, plus friction at the floor.', 'Take moments about the foot of the ladder.']),
	]),
	('CHM 101', 'Chem Solutions', 'General chemistry: moles, bonding and balancing equations.', True, [
		('Balancing redox equations', 'Is there an easy way to balance redox equations in acidic solution?',
		 ['Half-equation method: balance O with water, H with H+, then electrons.', 'Practise 5 a day and it becomes easy.']),
		('Mole concept test next week', 'Test 1 covers moles and stoichiometry. Let us revise on Saturday.', ['I am in.', 'Count me in too.']),
	]),
	('HIS 101', 'History Fanatics', 'African and world history — dates, causes and essays.', False, [
		('Causes of the First World War', 'What are the four main causes we are expected to discuss?', ['MAIN: militarism, alliances, imperialism, nationalism.']),
	]),
	('PHY 101', 'Fantastic Fizix', 'Physics problems explained simply. No question is too small.', False, [
		('Projectile motion trick', 'Treat horizontal and vertical motion separately — it saves time.', ['This is the best tip.', 'And the time of flight links them.']),
	]),
	('CHM 201', 'Organic Doubts', 'All your organic chemistry doubts: mechanisms, naming and reactions.', False, [
		('SN1 vs SN2', 'How do I know which mechanism a reaction follows?', ['Look at the substrate: tertiary leans SN1, primary SN2.']),
	]),
	('CHM 202', 'Non-Polar Solvents Only', 'Physical chemistry and solutions. Like dissolves like.', False, [
		('Raoult’s law question', 'Can someone explain negative deviation from Raoult’s law?', ['Stronger attractions between the two liquids than in each pure liquid.']),
	]),
	('PHY 301', 'Fans of Stephen Hawking', 'Cosmology, black holes and modern physics reading club.', False, [
		('Book of the month', 'This month: A Brief History of Time, chapters 1–3.', ['Started it last night!', 'Chapter 2 on space and time is great.']),
	]),
	('CHM 102', "Let's Solve Reactions", 'One reaction a day, solved step by step.', False, [
		('Today: combustion of ethanol', 'Write and balance the equation for burning ethanol in air.', ['C2H5OH + 3O2 → 2CO2 + 3H2O']),
	]),
	('MTH 202', 'Simple Complex', 'Complex numbers made simple — Argand diagrams and De Moivre.', False, [
		('De Moivre’s theorem', 'How do I use De Moivre to find cube roots of unity?', ['Write 1 as cos 0 + i sin 0, then divide the angle by 3 and add 2πk/3.']),
	]),
	('CSC 201', 'Code & Coffee', 'Programming practice in Python and C. Bring your bugs.', False, [
		('Recursion clicked for me', 'Thinking of the base case first finally made recursion make sense.', ['Same here!', 'Try the Tower of Hanoi next.']),
	]),
]

# What gets posted, per group type: (announcement, post, comments, poll question, poll options)
CONTENT = {
	G.ACADEMIC: ('Our lecturer has moved the assignment deadline to Friday. Please check the updated instructions in Files.',
		"Does anyone have last year's past questions? I can only find 2021.",
		['I have 2022 — uploading it to Files now.', 'Check the department library too, they keep copies.'],
		'When should we meet to revise this week?', ['Monday, 4pm', 'Wednesday, 5pm', 'Saturday, 10am']),
	G.PROJECT: ('Supervisor meeting moved to Thursday 11am. Bring your chapter drafts.',
		'Pushed the login screen and the QR scanner. Can someone test it on Android?',
		['Tested on my Tecno — works, but the camera is slow to open.', 'Nice! I will review the code tonight.'],
		'Which database should we use?', ['PostgreSQL', 'MySQL', 'SQLite for now']),
	G.DEPARTMENTAL: ('The departmental week starts on Monday. Dress code: corporate on Tuesday, native on Friday.',
		'Is the timetable for second semester out yet?',
		['Yes, it is on the notice board by the HOD office.', 'Thanks!'],
		'Which day works for the departmental dinner?', ['Friday', 'Saturday']),
	G.HOSTEL: ('There will be no water from 9am to 2pm tomorrow because of repairs. Fill your buckets tonight.',
		'Someone left a blue umbrella in the reading room — it is with the porter.',
		['That is mine, thank you!'],
		'Should we contribute for a new extension box?', ['Yes, ₦1,000 each', 'No, we manage']),
	G.SOCIAL: ('This Friday we have a FIFA tournament — winner gets free suya!',
		'Who is bringing the Ludo board?',
		['I will bring it.', 'Bring Whot cards too.'],
		'What should we play this week?', ['FIFA', 'Monopoly', 'Card games', 'Movie night']),
	G.PROFESSIONAL: ('New challenge this week: redesign the course registration page. Share your Figma link by Sunday.',
		'Here is a free course I found useful for getting started — happy to share notes.',
		['Thanks, starting it today.', 'This is great, adding it to Files.'],
		'Which topic should we cover next session?', ['Design systems', 'Prototyping', 'Portfolio reviews']),
}

OUTLINE_TXT = """Course outline (sample)

Week 1-2   Introduction and revision of prerequisites
Week 3-5   Core topics, with a tutorial sheet each week
Week 6     Test 1 (20%)
Week 7-10  Advanced topics and group assignment
Week 11    Test 2 (20%)
Week 12    Revision

Exam: 60%. Attendance is taken in every lecture.
This file was added by seed_studygroups to show how Files look.
"""


def tiny_pdf(title, lines):
	"""A small, valid one-page PDF with a few lines of text (no libraries needed)."""
	def esc(t):
		return t.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
	text = ['BT', '/F1 20 Tf', '72 760 Td', f'({esc(title)}) Tj', '/F1 12 Tf', '0 -34 Td']
	for line in lines:
		text += [f'({esc(line)}) Tj', '0 -18 Td']
	text.append('ET')
	stream = '\n'.join(text).encode('latin-1', 'replace')
	objs = [
		b'<< /Type /Catalog /Pages 2 0 R >>',
		b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
		b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
		b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
		b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
	]
	out, offsets = bytearray(b'%PDF-1.4\n'), []
	for i, body in enumerate(objs, 1):
		offsets.append(len(out))
		out += f'{i} 0 obj\n'.encode() + body + b'\nendobj\n'
	xref = len(out)
	out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode()
	for off in offsets:
		out += f'{off:010d} 00000 n \n'.encode()
	out += f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
	return bytes(out)


class Command(BaseCommand):
	help = 'Adds sample groups (python manage.py seed_studygroups [--reset]).'

	def add_arguments(self, parser):
		parser.add_argument('--reset', action='store_true', help='Remove earlier samples first.')

	def handle(self, *args, **opts):
		samples = G.objects.filter(description__contains=MARK)
		if opts['reset']:
			n = 0
			for g in samples:
				for f in g.files.all():
					f.file.delete(save=False)
				g.delete()
				n += 1
			self.stdout.write(f'Removed {n} sample groups.')
		rng = random.Random(401)
		added = 0
		for uni in University.objects.all():
			students = list(StudentProfile.objects.filter(university=uni, user__is_active=True).select_related('user', 'department', 'level'))
			if len(students) < 2:
				continue
			real = [s for s in students if s.user.last_login]
			for kind, privacy, code, name, about, mode, schedule, place, limit, extras in SAMPLES:
				if G.objects.filter(university=uni, name=name, description__contains=MARK).exists():
					continue
				owner = rng.choice([s for s in students if s not in real] or students)
				group = G.objects.create(
					university=uni, created_by=owner.user, group_type=kind, privacy=privacy, course_code=code, name=name,
					mode=mode, schedule=schedule, place=place, max_members=limit,
					meeting_link='https://meet.google.com/abc-defg-hij' if mode in (G.ONLINE, G.BOTH) else '',
					department=owner.department, level=owner.level if kind in (G.ACADEMIC, G.DEPARTMENTAL) else None,
					description=f'{about}\n\n{MARK}', is_open='closed' not in extras,
				)
				M.objects.create(group=group, user=owner.user, role=M.OWNER)
				chat.create_chat(group)

				others = [s for s in students if s.user_id != owner.user_id and s not in real]
				if 'full' in extras:
					members = rng.sample(others, k=min(len(others), limit - 1))
				else:
					room = (limit or 40) - 1 - len(real)
					members = rng.sample(others, k=max(0, min(len(others), room, rng.randint(4, 18))))
					members += [s for s in real if s.user_id != owner.user_id]
				for i, s in enumerate(members):
					M.objects.create(group=group, user=s.user, role=M.ADMIN if i == 0 and len(members) > 4 else M.MEMBER)
					chat.add_member(group, s.user)
				if privacy == G.PRIVATE and len(others) > len(members) + 2:
					for s in rng.sample([o for o in others if o not in members], k=2):
						M.objects.create(group=group, user=s.user, status=M.PENDING)

				people = [owner.user] + [s.user for s in members]
				self._content(group, owner.user, people, rng, 'files' in extras)
				added += 1
			added += self._study(uni, students, real, rng)
		self.stdout.write(self.style.SUCCESS(f'Added {added} sample groups. Open /groups/ to see them.'))

	def _study(self, uni, students, real, rng):
		"""Study groups with threads, comments and upvotes (the Groups dashboard).
		You join the first four, so My Groups and Recent Activity fill up; the rest show in Picked For You."""
		from datetime import timedelta
		from django.utils import timezone
		added, now = 0, timezone.now()
		for code, name, about, you_join, threads in STUDY:
			if G.objects.filter(university=uni, name=name, description__contains=MARK).exists():
				continue
			others = [s for s in students if s not in real]
			owner = rng.choice(others or students)
			group = G.objects.create(
				university=uni, created_by=owner.user, group_type=G.ACADEMIC, privacy=G.PUBLIC, course_code=code, name=name,
				mode=rng.choice([G.IN_PERSON, G.ONLINE, G.BOTH]), schedule=rng.choice(['Mondays, 4pm', 'Wednesdays, 6pm', 'Saturdays, 10am']),
				department=owner.department, level=owner.level, description=f'{about}\n\n{MARK}')
			M.objects.create(group=group, user=owner.user, role=M.OWNER)
			chat.create_chat(group)
			members = rng.sample([s for s in others if s != owner], k=min(len(others) - 1, rng.randint(6, 26)))
			if you_join:
				members += [s for s in real if s.user_id != owner.user_id]
			for s in members:
				M.objects.create(group=group, user=s.user)
				chat.add_member(group, s.user)
			people = [owner.user] + [s.user for s in members]
			bots = [u for u in people if not u.last_login] or people
			mine = [u for u in people if u.last_login]
			for n, (title, body, comments) in enumerate(threads):
				author = mine[0] if mine and you_join and n == 1 and code == 'MTH 101' else rng.choice(bots)
				when = now - timedelta(hours=rng.randint(2, 120))
				post = GroupPost.objects.create(group=group, author=author, title=title, body=body)
				GroupPost.objects.filter(pk=post.pk).update(created_at=when)
				for i, line in enumerate(comments):
					c = GroupComment.objects.create(post=post, author=rng.choice(bots), body=line)
					GroupComment.objects.filter(pk=c.pk).update(created_at=when + timedelta(minutes=20 * (i + 1)))
				for u in rng.sample(bots, k=min(len(bots), rng.randint(3, 18))):
					GroupPostLike.objects.get_or_create(post=post, user=u)
			added += 1
		return added

	def _content(self, group, owner, people, rng, with_files):
		announcement, text, comments, question, options = CONTENT[group.group_type]
		voters = people[:]
		rng.shuffle(voters)

		poll = GroupPost.objects.create(group=group, author=rng.choice(people), body=question, poll_multiple=False)
		opts = [GroupPollOption.objects.create(post=poll, text=t, position=i) for i, t in enumerate(options)]
		weights = [rng.randint(1, 5) for _ in opts]
		for u in voters[:max(1, len(voters) * 2 // 3)]:
			if u.last_login:   # leave your own vote to you
				continue
			GroupPollVote.objects.create(option=rng.choices(opts, weights)[0], post=poll, user=u)

		post = GroupPost.objects.create(group=group, author=rng.choice(people[1:] or people), body=text)
		for line in comments:
			GroupComment.objects.create(post=post, author=rng.choice(people), body=line)
		for u in rng.sample(people, k=min(len(people), rng.randint(1, 6))):
			if not u.last_login:
				GroupPostLike.objects.get_or_create(post=post, user=u)

		ann = GroupPost.objects.create(group=group, author=owner, body=announcement, is_announcement=True, pinned=True)
		for u in rng.sample(people, k=min(len(people), rng.randint(2, 8))):
			if not u.last_login:
				GroupPostLike.objects.get_or_create(post=ann, user=u)

		if with_files:
			label = group.course_code or 'Project'
			pdf = tiny_pdf(f'{label} - Course outline', [line for line in OUTLINE_TXT.splitlines()[2:] if line])
			for name, data in ((f'{label} course outline.pdf', pdf), ('Assignment 2 instructions.txt', OUTLINE_TXT.encode())):
				f = GroupFile(group=group, uploaded_by=rng.choice(people), name=name, size=len(data))
				f.file.save(name, ContentFile(data), save=True)
