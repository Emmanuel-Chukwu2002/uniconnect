"""
The real-time side of Messages.

Each open UniConnect tab opens ONE WebSocket (ws/chat/). On connect
the consumer joins:
    user_<id>            -> this user's tabs (badges, calls, new chats)
    conv_<id> (each one) -> every conversation the user belongs to
so a message is broadcast once to conv_<id> and every member's tabs
get it, whichever chat they have open.

Every message from the browser is validated here: the user must be a
member of the conversation, content is length-checked, and nothing the
browser says about who it is is trusted (the user comes from the
session cookie via AuthMiddlewareStack).
"""
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from . import services as S
from .models import Call, Conversation, Message, MessageReaction, UserPresence

User = get_user_model()
TYPING_MIN_INTERVAL = 2.0  # seconds between "typing" events per chat
ALLOWED_EMOJI_LEN = 16


class ChatConsumer(AsyncJsonWebsocketConsumer):

	# ------------------------------------------------------------------
	# Connection
	# ------------------------------------------------------------------
	async def connect(self):
		self.user = self.scope.get('user')
		if not self.user or not self.user.is_authenticated:
			await self.close(code=4401)  # not signed in
			return
		self.conv_groups = set()
		self.last_typing = {}
		await self.accept()
		await self.channel_layer.group_add(S.group_user(self.user.pk), self.channel_name)
		for conv_id in await database_sync_to_async(S.user_conversation_ids)(self.user):
			await self._join(conv_id)

		came_online = await self._presence(+1)
		if came_online:
			await self._broadcast_presence()
		# Anything sent while this user was offline has now been delivered.
		changed = await database_sync_to_async(S.mark_delivered)(self.user)
		await self._send_receipts(changed)
		await self.send_json({'type': 'hello', 'user': self.user.pk, 'unread_chats': await self._unread_chats()})

	async def disconnect(self, code):
		if not getattr(self, 'user', None) or not self.user.is_authenticated:
			return
		await self.channel_layer.group_discard(S.group_user(self.user.pk), self.channel_name)
		for group in list(getattr(self, 'conv_groups', [])):
			await self.channel_layer.group_discard(group, self.channel_name)
		went_offline = await self._presence(-1)
		if went_offline:
			await self._broadcast_presence()

	async def _join(self, conv_id):
		group = S.group_conv(conv_id)
		if group not in self.conv_groups:
			await self.channel_layer.group_add(group, self.channel_name)
			self.conv_groups.add(group)

	# ------------------------------------------------------------------
	# From the browser
	# ------------------------------------------------------------------
	async def receive_json(self, content, **kwargs):
		handlers = {
			'message': self.on_message, 'typing': self.on_typing, 'read': self.on_read,
			'delivered': self.on_delivered, 'react': self.on_react, 'delete': self.on_delete, 'call': self.on_call,
		}
		handler = handlers.get(content.get('type')) if isinstance(content, dict) else None
		if handler is None:
			return await self.send_json({'type': 'error', 'error': 'Unknown action.'})
		try:
			await handler(content)
		except (ValueError, TypeError):
			await self.send_json({'type': 'error', 'error': 'Invalid request.', 'client_id': content.get('client_id')})

	async def on_message(self, data):
		conv_id = int(data.get('conversation'))
		text = str(data.get('content') or '').strip()
		if not text:
			raise ValueError
		if len(text) > Message.MAX_LENGTH:
			return await self.send_json({'type': 'error', 'error': 'Message is too long.', 'client_id': data.get('client_id')})
		payload = await self._save_message(conv_id, text, data.get('reply_to'))
		if payload is None:
			return await self.send_json({'type': 'error', 'error': "You can't send messages to this chat.", 'client_id': data.get('client_id')})
		payload['client_id'] = str(data.get('client_id') or '')[:40]
		await self.channel_layer.group_send(S.group_conv(conv_id), {'type': 'chat.event', 'payload': {'type': 'message', 'message': payload}})
		await database_sync_to_async(S.push_unread_counts)(conv_id, exclude_user=self.user.pk)

	async def on_typing(self, data):
		conv_id = int(data.get('conversation'))
		state = bool(data.get('state'))
		now = time.monotonic()
		# Throttle: at most one "typing" per chat every 2 seconds.
		if state and now - self.last_typing.get(conv_id, 0) < TYPING_MIN_INTERVAL:
			return
		self.last_typing[conv_id] = now if state else 0
		if S.group_conv(conv_id) not in self.conv_groups:
			return
		await self.channel_layer.group_send(S.group_conv(conv_id), {'type': 'chat.event', 'payload': {
			'type': 'typing', 'conversation': conv_id, 'user': self.user.pk,
			'name': self.user.first_name or self.user.username, 'state': state,
		}})

	async def on_read(self, data):
		conv_id = int(data.get('conversation'))
		if S.group_conv(conv_id) not in self.conv_groups:
			return
		changed = await database_sync_to_async(S.mark_read)(self.user, conv_id)
		await self._send_receipts(changed)
		# "Seen by N" in a group's Chat tab (static/js/group-chat.js): who has
		# read up to when — only for people who share read receipts.
		seen_at = await self._read_receipt_at(conv_id)
		if seen_at:
			await self.channel_layer.group_send(S.group_conv(conv_id), {'type': 'chat.event', 'payload': {
				'type': 'seen', 'conversation': conv_id, 'user': self.user.pk, 'at': seen_at,
			}})
		# Every tab of this user updates its unread badges.
		await self.channel_layer.group_send(S.group_user(self.user.pk), {'type': 'chat.event', 'payload': {
			'type': 'unread', 'conversation': conv_id, 'read': True, 'unread_chats': await self._unread_chats(),
		}})

	async def on_delivered(self, data):
		conv_id = int(data.get('conversation'))
		if S.group_conv(conv_id) not in self.conv_groups:
			return
		changed = await database_sync_to_async(S.mark_delivered)(self.user, [conv_id])
		await self._send_receipts(changed)
		await self.send_json({'type': 'unread', 'conversation': conv_id, 'unread_chats': await self._unread_chats()})

	async def on_react(self, data):
		msg_id = int(data.get('message'))
		emoji = str(data.get('emoji') or '')[:ALLOWED_EMOJI_LEN]
		result = await self._react(msg_id, emoji)
		if result:
			conv_id, reactions = result
			await self.channel_layer.group_send(S.group_conv(conv_id), {'type': 'chat.event', 'payload': {
				'type': 'reaction', 'conversation': conv_id, 'message': msg_id, 'reactions': reactions,
				'user': self.user.pk, 'emoji': emoji,
			}})

	async def on_delete(self, data):
		msg_id = int(data.get('message'))
		conv_id = await self._delete(msg_id)
		if conv_id:
			await self.channel_layer.group_send(S.group_conv(conv_id), {'type': 'chat.event', 'payload': {
				'type': 'deleted', 'conversation': conv_id, 'message': msg_id,
			}})

	async def on_call(self, data):
		action = data.get('action')
		if action == 'start':
			result = await self._call_start(int(data.get('user')), data.get('kind'))
			if result is None:
				return await self.send_json({'type': 'error', 'error': "Can't call this person."})
			call, caller, callee, online = result
			info = {'type': 'call', 'call': call, 'caller': caller, 'callee': callee}
			await self.channel_layer.group_send(S.group_user(caller['id']), {'type': 'chat.event', 'payload': {**info, 'state': 'ringing' if online else 'unavailable'}})
			if online:
				await self.channel_layer.group_send(S.group_user(callee['id']), {'type': 'chat.event', 'payload': {**info, 'state': 'incoming'}})
			return
		if action in ('accept', 'decline', 'end', 'cancel'):
			result = await self._call_update(int(data.get('call')), action)
			if result:
				call, caller_id, callee_id, state = result
				for uid in (caller_id, callee_id):
					await self.channel_layer.group_send(S.group_user(uid), {'type': 'chat.event', 'payload': {
						'type': 'call', 'call': call, 'state': state,
					}})

	# ------------------------------------------------------------------
	# From the channel layer (other users / views)
	# ------------------------------------------------------------------
	async def chat_event(self, event):
		await self.send_json(event['payload'])

	async def chat_join(self, event):
		"""A new chat was created that this user is in: listen to it."""
		await self._join(event['conversation'])
		await self.send_json({'type': 'conversation_added', 'conversation': event['conversation']})

	# ------------------------------------------------------------------
	# Database helpers
	# ------------------------------------------------------------------
	@database_sync_to_async
	def _save_message(self, conv_id, text, reply_to=None):
		conv = Conversation.objects.filter(pk=conv_id).first()
		if not conv or not S.can_post(conv, self.user):
			return None
		msg = S.create_message(conv, self.user, Message.TEXT, text, reply_to=S.reply_target(conv, reply_to))
		return S.serialize_message(Message.objects.select_related('sender__student_profile', 'reply_to__sender').get(pk=msg.pk))

	@database_sync_to_async
	def _read_receipt_at(self, conv_id):
		at = (S.Participant.objects.filter(conversation_id=conv_id, user=self.user)
			.values_list('last_read_receipt_at', flat=True).first())
		return at.isoformat() if at else None

	@database_sync_to_async
	def _unread_chats(self):
		return S.unread_chats_count(self.user)

	@database_sync_to_async
	def _presence(self, delta):
		"""Count open connections; returns True when this changes online/offline."""
		with transaction.atomic():
			pres, _ = UserPresence.objects.select_for_update().get_or_create(user=self.user)
			before = pres.connections
			pres.connections = max(0, before + delta)
			if pres.connections == 0:
				pres.last_seen = timezone.now()
			pres.save()
			return (before == 0) != (pres.connections == 0)

	async def _broadcast_presence(self):
		state = await database_sync_to_async(S.presence_of)(self.user)
		for group in list(self.conv_groups):
			await self.channel_layer.group_send(group, {'type': 'chat.event', 'payload': {
				'type': 'presence', 'user': self.user.pk, **state,
			}})

	async def _send_receipts(self, changed):
		for conv_id, items in changed.items():
			await self.channel_layer.group_send(S.group_conv(conv_id), {'type': 'chat.event', 'payload': {
				'type': 'receipt', 'conversation': conv_id, 'items': items,
			}})

	@database_sync_to_async
	def _react(self, msg_id, emoji):
		msg = Message.objects.filter(pk=msg_id, is_deleted=False).exclude(kind=Message.SYSTEM).first()
		if not msg or not S.participant(msg.conversation, self.user):
			return None
		existing = MessageReaction.objects.filter(message=msg, user=self.user).first()
		if not emoji or (existing and existing.emoji == emoji):
			# Same emoji again (or empty) removes your reaction, like WhatsApp.
			MessageReaction.objects.filter(message=msg, user=self.user).delete()
		else:
			MessageReaction.objects.update_or_create(message=msg, user=self.user, defaults={'emoji': emoji, 'created_at': timezone.now()})
		return msg.conversation_id, S.reactions_summary(msg)

	@database_sync_to_async
	def _delete(self, msg_id):
		msg = Message.objects.filter(pk=msg_id, sender=self.user, is_deleted=False).first()
		if not msg:
			return None
		if msg.attachment:
			# A forwarded copy may share the stored file (chat/forwarding.py): keep it while one does.
			if not Message.objects.filter(attachment=msg.attachment.name, is_deleted=False).exclude(pk=msg.pk).exists():
				msg.attachment.delete(save=False)
		msg.is_deleted = True
		msg.content = ''
		msg.attachment = ''
		msg.save(update_fields=['is_deleted', 'content', 'attachment', 'updated_at'])
		msg.reactions.all().delete()
		if msg.pinned_at:                     # a deleted message leaves the pinned bar
			from . import pins
			Message.objects.filter(pk=msg.pk).update(pinned_at=None, pinned_by=None)
			pins.broadcast(msg.conversation)
		return msg.conversation_id

	@database_sync_to_async
	def _call_start(self, callee_id, kind):
		callee = User.objects.filter(pk=callee_id, is_active=True).select_related('student_profile').first()
		if not callee or callee.pk == self.user.pk:
			return None
		online = UserPresence.objects.filter(user=callee, connections__gt=0).exists()
		call = Call.objects.create(
			caller=self.user, callee=callee, kind=Call.VIDEO if kind == 'video' else Call.AUDIO,
			status=Call.RINGING if online else Call.MISSED, ended_at=None if online else timezone.now(),
		)
		return {'id': call.pk, 'kind': call.kind}, S.person(self.user), S.person(callee), online

	@database_sync_to_async
	def _call_update(self, call_id, action):
		call = Call.objects.filter(pk=call_id).filter(caller=self.user).first() or \
			Call.objects.filter(pk=call_id, callee=self.user).first()
		if not call:
			return None
		now = timezone.now()
		is_callee = call.callee_id == self.user.pk
		if action == 'accept' and is_callee and call.status == Call.RINGING:
			call.status, call.answered_at = Call.ANSWERED, now
			state = 'connected'
		elif action == 'decline' and is_callee and call.status == Call.RINGING:
			call.status, call.ended_at = Call.DECLINED, now
			state = 'declined'
		elif action == 'cancel' and not is_callee and call.status == Call.RINGING:
			# Caller hung up (or it rang out) before an answer: a missed call.
			call.status, call.ended_at = Call.MISSED, now
			state = 'missed'
		elif action == 'end' and call.status == Call.ANSWERED and not call.ended_at:
			call.ended_at = now
			state = 'ended'
		else:
			return None
		call.save()
		return {'id': call.pk, 'kind': call.kind, 'duration': call.duration_seconds}, call.caller_id, call.callee_id, state
