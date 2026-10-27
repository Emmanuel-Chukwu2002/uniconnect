from django.contrib import admin

from .models import (
	Call, ChatSettings, Community, CommunityMember, Conversation, ConversationParticipant, Message, MessageReaction,
	UserPresence,
)


class ParticipantInline(admin.TabularInline):
	model = ConversationParticipant
	extra = 0
	raw_id_fields = ('user',)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
	list_display = ('id', 'kind', 'name', 'community', 'is_announcement', 'last_message_at')
	list_filter = ('kind', 'is_announcement')
	inlines = [ParticipantInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
	list_display = ('id', 'conversation', 'sender', 'kind', 'content', 'created_at', 'delivered_at', 'read_at')
	list_filter = ('kind',)
	raw_id_fields = ('conversation', 'sender')


class CommunityMemberInline(admin.TabularInline):
	model = CommunityMember
	extra = 0
	raw_id_fields = ('user',)


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
	list_display = ('name', 'created_by', 'created_at')
	inlines = [CommunityMemberInline]


@admin.register(Call)
class CallAdmin(admin.ModelAdmin):
	list_display = ('caller', 'callee', 'kind', 'status', 'started_at')
	list_filter = ('kind', 'status')


admin.site.register(MessageReaction)
admin.site.register(UserPresence)
admin.site.register(ChatSettings)
