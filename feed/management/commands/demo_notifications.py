"""
Makes some of the simulated students (the sim_ accounts) interact with
one real student's account, so the notification system has something
to show: likes, comments, a reply, a comment like, an @mention, follow
requests and a new follower. Everything goes through the same notify()
calls the real views use, so it looks exactly like real activity.

The sim_ accounts can't log in, which is why this is a command rather
than something you click through.

Usage:
    python manage.py demo_notifications <username>
    python manage.py demo_notifications <username> --undo   (removes it all again)

Everything it creates is recorded in ml_data/demo_notifications.json,
which is what --undo uses, so it never touches anything else.
"""
import json
import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from feed.models import Comment, CommentLike, Follow, Like, Notification, Post
from feed.notifications import notify, notify_mentions

User = get_user_model()
RECORD = settings.BASE_DIR / 'ml_data' / 'demo_notifications.json'

POST_COMMENTS = [
	"Nice one! 🔥",
	"This is really good, well done.",
	"Wow, I love this 😍",
	"Facts! Couldn't agree more.",
	"Can you share more about this in class tomorrow?",
	"Congrats bro, you deserve it 👏",
]
REPLIES = ["Totally agree with you 💯", "Exactly what I was thinking!", "😂😂 you're right"]


class Command(BaseCommand):
	help = "Make simulated students like, comment on and follow a real account, to test notifications."

	def add_arguments(self, parser):
		parser.add_argument('username', help="Your UniConnect username (e.g. UNN-2022249381)")
		parser.add_argument('--undo', action='store_true', help="Remove everything a previous run created.")

	def handle(self, *args, **options):
		try:
			me = User.objects.get(username=options['username'])
		except User.DoesNotExist:
			real = User.objects.exclude(username__startswith='sim_').values_list('username', flat=True)
			raise CommandError(f"No user '{options['username']}'. Real accounts: {', '.join(real)}")

		if options['undo']:
			return self.undo(me)

		if RECORD.exists():
			self.stdout.write(self.style.WARNING(
				"A previous demo run is still in place. Removing it first so nothing is doubled."
			))
			self.undo(me)

		sims = list(User.objects.filter(username__startswith='sim_').select_related('student_profile'))
		if len(sims) < 12:
			raise CommandError("Not enough sim_ accounts. Run: python manage.py generate_simulated_data")
		rng = random.Random()
		rng.shuffle(sims)

		posts = list(Post.objects.filter(author=me).order_by('-created_at')[:3])
		created = {'likes': [], 'comments': [], 'comment_likes': [], 'follows': [], 'notifications': []}
		now = timezone.now()

		def stamp(notification, minutes_ago):
			"""Spread the activity out in time so it reads like real use."""
			if notification:
				notification.created_at = now - timedelta(minutes=minutes_ago)
				notification.save(update_fields=['created_at'])
				created['notifications'].append(notification.pk)

		def free(users, exclude_ids):
			return [u for u in users if u.pk not in exclude_ids]

		if posts:
			# 1. Six people like your latest post -> "A, B and 4 other people liked your ...".
			post = posts[0]
			already = set(Like.objects.filter(post=post).values_list('user_id', flat=True))
			for i, sim in enumerate(free(sims, already)[:6]):
				like = Like.objects.create(user=sim, post=post)
				created['likes'].append(like.pk)
				stamp(notify(me, sim, Notification.LIKE_POST, post=post), 5 + i * 7)

			# 2. Two comments on it -> "A and B commented on your ..."
			for i, sim in enumerate(sims[6:8]):
				c = Comment.objects.create(post=post, author=sim, content=POST_COMMENTS[i])
				created['comments'].append(c.pk)
				stamp(notify(me, sim, Notification.COMMENT, post=post, comment=c), 12 + i * 20)

		if len(posts) > 1:
			# 3. Three likes and one comment on an older post.
			post = posts[1]
			already = set(Like.objects.filter(post=post).values_list('user_id', flat=True))
			for i, sim in enumerate(free(sims[8:], already)[:3]):
				like = Like.objects.create(user=sim, post=post)
				created['likes'].append(like.pk)
				stamp(notify(me, sim, Notification.LIKE_POST, post=post), 60 * 5 + i * 30)
			sim = sims[11]
			c = Comment.objects.create(post=post, author=sim, content=rng.choice(POST_COMMENTS[2:]))
			created['comments'].append(c.pk)
			stamp(notify(me, sim, Notification.COMMENT, post=post, comment=c), 60 * 26)

		# 4. A reply to one of your comments, and a like on it.
		mine = Comment.objects.filter(author=me).order_by('-created_at').first()
		if mine:
			sim = sims[12 % len(sims)]
			reply = Comment.objects.create(post=mine.post, author=sim, parent=mine, content=rng.choice(REPLIES))
			created['comments'].append(reply.pk)
			stamp(notify(me, sim, Notification.REPLY, post=mine.post, comment=reply), 40)
			sim = sims[13 % len(sims)]
			if not CommentLike.objects.filter(user=sim, comment=mine).exists():
				cl = CommentLike.objects.create(user=sim, comment=mine)
				created['comment_likes'].append(cl.pk)
				stamp(notify(me, sim, Notification.LIKE_COMMENT, post=mine.post, comment=mine), 90)

		# 5. Someone @mentions you on another student's post.
		other = Post.objects.exclude(author=me).order_by('-created_at').first()
		if other:
			sim = sims[14 % len(sims)]
			c = Comment.objects.create(post=other, author=sim, content=f"@{me.username} you need to see this 👀")
			created['comments'].append(c.pk)
			before = set(Notification.objects.filter(recipient=me).values_list('pk', flat=True))
			notify_mentions(c.content, sim, other, c)
			for n in Notification.objects.filter(recipient=me).exclude(pk__in=before):
				stamp(n, 25)

		# 6. Follow requests (waiting for you to Confirm/Delete) and one new follower.
		has_row = set(Follow.objects.filter(following=me).values_list('follower_id', flat=True))
		not_following = free(sims[15:], has_row)
		for i, sim in enumerate(not_following[:2]):
			f = Follow.objects.create(follower=sim, following=me, status=Follow.STATUS_PENDING)
			created['follows'].append(f.pk)
			stamp(notify(me, sim, Notification.FOLLOW_REQUEST), 3 + i * 50)
		for sim in not_following[2:3]:
			f = Follow.objects.create(follower=sim, following=me, status=Follow.STATUS_ACCEPTED)
			created['follows'].append(f.pk)
			stamp(notify(me, sim, Notification.FOLLOW), 60 * 30)

		RECORD.parent.mkdir(parents=True, exist_ok=True)
		RECORD.write_text(json.dumps(created, indent=2))

		total = Notification.objects.filter(pk__in=created['notifications']).count()
		self.stdout.write(self.style.SUCCESS(
			f"Done: {total} notifications for {me.get_full_name() or me.username} "
			f"({len(created['likes'])} likes, {len(created['comments'])} comments, "
			f"{len(created['comment_likes'])} comment like, {len(created['follows'])} follows).\n"
			f"Refresh UniConnect and look at the bell. To remove it all: "
			f"python manage.py demo_notifications {me.username} --undo"
		))

	def undo(self, me):
		if not RECORD.exists():
			self.stdout.write("Nothing to undo.")
			return
		created = json.loads(RECORD.read_text())
		counts = [
			Notification.objects.filter(pk__in=created.get('notifications', [])).delete()[0],
			Like.objects.filter(pk__in=created.get('likes', [])).delete()[0],
			CommentLike.objects.filter(pk__in=created.get('comment_likes', [])).delete()[0],
			Comment.objects.filter(pk__in=created.get('comments', [])).delete()[0],
			Follow.objects.filter(pk__in=created.get('follows', [])).delete()[0],
		]
		# If you confirmed a demo follow request, the sim account got an
		# "accepted your follow request" notification; remove those too.
		counts.append(Notification.objects.filter(
			recipient__username__startswith='sim_', actor=me, type=Notification.FOLLOW_ACCEPTED,
		).delete()[0])
		RECORD.unlink()
		self.stdout.write(self.style.SUCCESS(f"Removed the demo activity ({sum(counts)} rows)."))
