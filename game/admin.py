from django.contrib import admin

from .models import (
    GameSession, PlayerResult, PlayerSessionSummary, Room, RoomPlayer,
    SessionTask, Task, TaskAnswer, TaskImage, TelegramUser,
)


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ('tg_id', 'username', 'first_name', 'total_score', 'games_played', 'created_at')
    search_fields = ('username', 'first_name', 'tg_id')


class TaskImageInline(admin.TabularInline):
    model = TaskImage
    extra = 0


class TaskAnswerInline(admin.TabularInline):
    model = TaskAnswer
    extra = 0


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject', 'task_type', 'difficulty', 'short_text')
    list_filter = ('subject', 'difficulty', 'task_type')
    search_fields = ('text',)
    inlines = [TaskImageInline, TaskAnswerInline]

    @admin.display(description='Текст')
    def short_text(self, obj):
        return obj.text[:80] + '...' if len(obj.text) > 80 else obj.text


class RoomPlayerInline(admin.TabularInline):
    model = RoomPlayer
    extra = 0


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('uuid', 'creator', 'status', 'task_count', 'max_players', 'created_at')
    list_filter = ('status',)
    inlines = [RoomPlayerInline]


class SessionTaskInline(admin.TabularInline):
    model = SessionTask
    extra = 0


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'room', 'status', 'started_at', 'finished_at')
    list_filter = ('status',)
    inlines = [SessionTaskInline]


@admin.register(PlayerResult)
class PlayerResultAdmin(admin.ModelAdmin):
    list_display = ('player', 'session', 'session_task', 'is_correct', 'score_delta')
    list_filter = ('is_correct',)


@admin.register(PlayerSessionSummary)
class PlayerSessionSummaryAdmin(admin.ModelAdmin):
    list_display = ('player', 'session', 'total_score', 'correct_count', 'wrong_count', 'place')
