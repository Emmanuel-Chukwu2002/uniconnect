"""
Sample data for Messages, so the section doesn't look empty: chats with
other students (some unread), a pinned "Message yourself" note, a class
group, an archived chat, a community with an Announcements group, call
history and a few status updates.

Usage:
    python manage.py seed_chat <your username>
    python manage.py seed_chat <your username> --undo     (removes it again)

The other people are your second account (if any) and the simulated
sim_ students. Everything created is recorded in ml_data/demo_chat.json,
which --undo uses, so nothing else is touched.
"""
import io
import json
import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from chat import services as S
from chat.models import (
	Call, Community, CommunityMember, Conversation, ConversationParticipant as Participant, Message, MessageReaction,
)
from feed.models import Story

User = get_user_model()
RECORD = settings.BASE_DIR / 'ml_data' / 'demo_chat.json'

# (minutes ago, who: 'me' or 'them', text)
DIRECT_SCRIPTS = [
	[(3000, 'them', 'Good evening, have you started the project write-up?'), (2990, 'me', 'Yes o, chapter three is almost done'),
	 (2985, 'them', 'Nice one! Send me your table of contents when you can'), (2900, 'me', 'Okay, I will send it tonight'),
	 (55, 'them', 'Did you see the new timetable for the defence?'), (52, 'them', 'Ours is on Thursday 🙏')],
	[(1500, 'me', 'Are you coming for the lecture tomorrow?'), (1490, 'them', 'Yes, 8am right?'),
	 (1488, 'me', 'Yes, CSC 411 at the ICT hall'), (1480, 'them', 'Thank you boss 🙌')],
	[(400, 'them', 'Abeg, which chapter did the lecturer say we should read?'), (398, 'me', 'Chapter 5 and 6, network security'),
	 (397, 'them', 'Okay, done 👍'), (12, 'them', 'Check out this post on UniConnect: http://127.0.0.1:8000/home/')],
	[(5000, 'them', 'Congratulations on your result 🎉'), (4990, 'me', 'Thank you so much 😊'),
	 (4980, 'them', 'You deserve it. Keep it up!')],
	[(90, 'me', 'I no get money for costume day anymore 😂'), (88, 'them', 'Lol same here'), (85, 'them', 'We go manage am')],
]
GROUP_SCRIPT = [
	(2000, 0, 'Good morning everyone. Class rep here: test holds on Friday by 10am.'),
	(1990, 1, 'Which venue please?'), (1985, 0, 'LT 2, the same place as last week.'),
	(600, 2, 'Has anyone gotten the past questions for CSC 421?'), (590, 'me', 'I have them, I will drop them here'),
	(30, 3, 'Please who has the slides for today\'s class?'), (25, 1, 'I do, sending now'), (8, 4, 'Thank you!'),
]
STATUS_COLOURS = [((33, 192, 99), (16, 53, 41)), ((83, 189, 235), (2, 126, 181)), ((241, 92, 109), (120, 30, 60))]


class Command(BaseCommand):
	help = "Fill Messages with sample chats, groups, a community, calls and status updates for one user."

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
			self.stdout.write(self.style.WARNING('Removing the previous sample data first.'))
			self.undo()

		others = list(User.objects.exclude(pk=me.pk).exclude(username__startswith='sim_').filter(is_active=True)[:1])
		others += list(User.objects.filter(username__startswith='sim_').order_by('?')[:12])
		if len(others) < 8:
			raise CommandError('Need at least 8 other accounts (run: python manage.py generate_simulated_data).')
		rec = {'conversations': [], 'communities': [], 'calls': [], 'stories': []}
		now = timezone.now()
		ago = lambda minutes: now - timedelta(minutes=minutes)

		with transaction.atomic():
			# ----- direct chats -----
			for other, script in zip(others[:len(DIRECT_SCRIPTS)], DIRECT_SCRIPTS):
				conv, created = S.direct_conversation(me, other)
				if not created:
					continue  # never touch a real existing chat
				rec['conversations'].append(conv.pk)
				conv.created_at = ago(script[0][0] + 5)
				conv.save(update_fields=['created_at'])
				self._play(conv, me, {'me': me, 'them': other}, script, ago)
				mine = Participant.objects.get(conversation=conv, user=me)
				theirs = Participant.objects.get(conversation=conv, user=other)
				last = conv.messages.order_by('-created_at').first()
				# Their side has read everything up to now except the newest of mine (shows grey vs blue ticks).
				theirs.last_delivered_at = now
				theirs.last_read_receipt_at = theirs.last_read_at = ago(3) if script is not DIRECT_SCRIPTS[1] else ago(1600)
				theirs.save()
				# Your side: unread if the last message is theirs and recent.
				mine.last_delivered_at = now
				mine.last_read_at = mine.last_read_receipt_at = (ago(60) if last.sender_id == other.pk and script[-1][0] < 100 else now)
				mine.save()

			# ----- message yourself (pinned) -----
			self_conv, created = S.direct_conversation(me, me)
			if created:
				rec['conversations'].append(self_conv.pk)
				self._play(self_conv, me, {'me': me}, [(500, 'me', 'Project to-do: finish chapter 4, print 3 copies, book the defence slot')], ago)
				Participant.objects.filter(conversation=self_conv, user=me).update(is_pinned=True, last_read_at=now)

			# ----- a class group (unread) -----
			members = others[:6]
			group = S.create_group(me, 'CSC 400L Class', members, description='Class updates for 400 level Computer Science')
			rec['conversations'].append(group.pk)
			Message.objects.filter(conversation=group).update(created_at=ago(2100))
			cast = {i: m for i, m in enumerate(members)}
			cast['me'] = me
			self._play(group, me, cast, [(m, w, t) for m, w, t in GROUP_SCRIPT], ago)
			Participant.objects.filter(conversation=group).exclude(user=me).update(last_delivered_at=now, last_read_at=ago(20), last_read_receipt_at=ago(20))
			Participant.objects.filter(conversation=group, user=me).update(last_read_at=ago(40), is_favourite=True)
			last_mine = group.messages.filter(sender=me).last()
			if last_mine:
				MessageReaction.objects.create(message=last_mine, user=members[2], emoji='🙏', created_at=ago(580))
				MessageReaction.objects.create(message=last_mine, user=members[3], emoji='❤️', created_at=ago(570))

			# ----- an archived chat -----
			arch_other = others[6]
			arch, created = S.direct_conversation(me, arch_other)
			if created:
				rec['conversations'].append(arch.pk)
				self._play(arch, me, {'me': me, 'them': arch_other}, [(9000, 'them', 'Bsc project defence 17/10 — see you there'), (8990, 'me', 'See you!')], ago)
				Participant.objects.filter(conversation=arch, user=me).update(is_archived=True, last_read_at=now)

			# ----- a community -----
			community = Community.objects.create(name='Computer Science Department', description='Announcements and groups for CSC students', created_by=me, created_at=ago(9000))
			rec['communities'].append(community.pk)
			CommunityMember.objects.create(community=community, user=me, role=CommunityMember.ADMIN)
			for m in others[:8]:
				CommunityMember.objects.create(community=community, user=m)
			ann = S.create_group(me, 'Announcements', others[:8], community=community, is_announcement=True)
			rec['conversations'].append(ann.pk)
			Message.objects.filter(conversation=ann).update(created_at=ago(710))
			self._play(ann, me, {'me': me}, [(700, 'me', 'Welcome to the community! Department announcements will be posted here.')], ago)
			Participant.objects.filter(conversation=ann).update(last_read_at=now, last_delivered_at=now, last_read_receipt_at=now)
			group.community = community
			group.save(update_fields=['community'])
			prep = S.create_group(others[1], 'Project Defence Prep', others[1:5], community=community)
			rec['conversations'].append(prep.pk)
			Message.objects.filter(conversation=prep).update(created_at=ago(320))
			self._play(prep, me, {0: others[1], 1: others[2]}, [(300, 0, 'Let us share our slides here before the defence'), (280, 1, 'Good idea')], ago)

			# ----- call history -----
			calls = [
				(others[0], me, Call.AUDIO, Call.ANSWERED, 70, 185), (me, others[1], Call.VIDEO, Call.ANSWERED, 600, 412),
				(others[2], me, Call.AUDIO, Call.MISSED, 1500, 0), (me, others[3], Call.AUDIO, Call.MISSED, 2900, 0),
				(others[4], me, Call.VIDEO, Call.DECLINED, 4300, 0),
			]
			for caller, callee, kind, status, minutes, secs in calls:
				c = Call.objects.create(caller=caller, callee=callee, kind=kind, status=status, started_at=ago(minutes))
				if status == Call.ANSWERED:
					c.answered_at = ago(minutes) + timedelta(seconds=8)
					c.ended_at = c.answered_at + timedelta(seconds=secs)
				else:
					c.ended_at = ago(minutes) + timedelta(seconds=20)
				c.save()
				rec['calls'].append(c.pk)

			for conv_id in rec['conversations']:
				S._recompute([conv_id])

		# ----- status updates (UniConnect Stories) -----
		student = getattr(me, 'student_profile', None)
		posters = [o for o in others if getattr(o, 'student_profile', None) and student and o.student_profile.university_id == student.university_id][:3]
		for i, poster in enumerate(posters):
			story = Story(user=poster, caption=['Exam week mood 📚', 'Department football match today ⚽', 'Final year loading 🎓'][i])
			story.image.save(f'demo_status_{poster.pk}.png', ContentFile(self._status_image(i, story.caption)), save=False)
			story.save()
			Story.objects.filter(pk=story.pk).update(created_at=now - timedelta(minutes=13 + i * 20))
			rec['stories'].append(story.pk)

		RECORD.parent.mkdir(parents=True, exist_ok=True)
		RECORD.write_text(json.dumps(rec, indent=2))
		self.stdout.write(self.style.SUCCESS(
			f"Done: {len(rec['conversations'])} chats/groups, 1 community, {len(rec['calls'])} calls, {len(rec['stories'])} status updates.\n"
			f"Open /messages/. To remove it: python manage.py seed_chat {me.username} --undo"
		))

	def _play(self, conv, me, cast, script, ago):
		for minutes, who, text in script:
			sender = cast[who] if who in cast else None
			msg = Message.objects.create(conversation=conv, sender=sender, content=text, created_at=ago(minutes))
			Conversation.objects.filter(pk=conv.pk).update(last_message_at=msg.created_at)

	def _status_image(self, i, caption):
		from PIL import Image, ImageDraw
		top, bottom = STATUS_COLOURS[i % len(STATUS_COLOURS)]
		img = Image.new('RGB', (720, 1280))
		draw = ImageDraw.Draw(img)
		for y in range(1280):
			t = y / 1279
			draw.line([(0, y), (720, y)], fill=tuple(int(top[k] * (1 - t) + bottom[k] * t) for k in range(3)))
		for r in range(6):
			x, y = random.randint(60, 660), random.randint(100, 1180)
			draw.ellipse([x - 40, y - 40, x + 40, y + 40], outline=(255, 255, 255), width=4)
		buf = io.BytesIO()
		img.save(buf, 'PNG')
		return buf.getvalue()

	def undo(self):
		if not RECORD.exists():
			self.stdout.write('Nothing to undo.')
			return
		rec = json.loads(RECORD.read_text())
		Conversation.objects.filter(pk__in=rec.get('conversations', [])).delete()
		Community.objects.filter(pk__in=rec.get('communities', [])).delete()
		Call.objects.filter(pk__in=rec.get('calls', [])).delete()
		for story in Story.objects.filter(pk__in=rec.get('stories', [])):
			story.image.delete(save=False)
			story.delete()
		RECORD.unlink()
		self.stdout.write(self.style.SUCCESS('Removed the sample Messages data.'))
