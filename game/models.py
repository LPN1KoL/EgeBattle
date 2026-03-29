import uuid

from django.db import models


class TelegramUser(models.Model):
    tg_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=64, null=True, blank=True)
    first_name = models.CharField(max_length=128)
    total_score = models.IntegerField(default=0)
    games_played = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Telegram-пользователь'
        verbose_name_plural = 'Telegram-пользователи'

    def __str__(self):
        return f'{self.first_name} (@{self.username or "—"}) [{self.tg_id}]'


SUBJECT_CHOICES = [
    ('math', 'Математика'),
    ('russian', 'Русский язык'),
    ('physics', 'Физика'),
    ('social', 'Обществознание'),
    ('informatics', 'Информатика'),
]

DEFAULT_SUBJECTS = ['math', 'russian']


def default_subjects():
    return ['math', 'russian']

DIFFICULTY_CHOICES = [(i, str(i)) for i in range(1, 6)]


class Task(models.Model):
    text = models.TextField()
    correct_answer = models.CharField(max_length=512, null=True, blank=True)
    difficulty = models.PositiveSmallIntegerField(choices=DIFFICULTY_CHOICES)
    subject = models.CharField(max_length=20, choices=SUBJECT_CHOICES)
    task_type = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Задача'
        verbose_name_plural = 'Задачи'
        indexes = [
            models.Index(fields=['subject', 'task_type']),
            models.Index(fields=['subject', 'difficulty']),
        ]

    def __str__(self):
        return f'[{self.subject}] #{self.task_type} (d={self.difficulty}) {self.text[:60]}'


class TaskImage(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='images')
    url = models.URLField(max_length=512)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Изображение к задаче'
        verbose_name_plural = 'Изображения к задачам'
        unique_together = [('task', 'order')]
        ordering = ['order']

    def __str__(self):
        return f'Image #{self.order} for Task #{self.task_id}'


class TaskAnswer(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='answers')
    text = models.CharField(max_length=512)
    is_correct = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Вариант ответа'
        verbose_name_plural = 'Варианты ответов'
        unique_together = [('task', 'order')]
        ordering = ['order']

    def __str__(self):
        mark = '+' if self.is_correct else '-'
        return f'[{mark}] {self.text[:40]}'


ROOM_STATUS_CHOICES = [
    ('waiting', 'Ожидание'),
    ('in_progress', 'Идёт игра'),
    ('finished', 'Завершена'),
]


class Room(models.Model):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    creator = models.ForeignKey(
        TelegramUser, on_delete=models.SET_NULL, null=True, related_name='created_rooms',
    )
    status = models.CharField(max_length=16, choices=ROOM_STATUS_CHOICES, default='waiting')
    subjects = models.JSONField(default=default_subjects)
    task_count = models.PositiveSmallIntegerField(default=5)
    max_players = models.PositiveSmallIntegerField(default=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Комната'
        verbose_name_plural = 'Комнаты'

    def __str__(self):
        return f'Room {self.uuid} [{self.status}]'


SESSION_STATUS_CHOICES = [
    ('active', 'Активна'),
    ('finished', 'Завершена'),
]


class GameSession(models.Model):
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name='sessions')
    tasks = models.ManyToManyField(Task, through='SessionTask')
    status = models.CharField(max_length=16, choices=SESSION_STATUS_CHOICES, default='active')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Игровая сессия'
        verbose_name_plural = 'Игровые сессии'

    def __str__(self):
        return f'Session #{self.id} (Room {self.room.uuid})'


class SessionTask(models.Model):
    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name='session_tasks')
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField()
    time_limit = models.PositiveSmallIntegerField()

    class Meta:
        verbose_name = 'Задача в сессии'
        verbose_name_plural = 'Задачи в сессиях'
        unique_together = [('session', 'task')]
        ordering = ['order']

    def __str__(self):
        return f'Session #{self.session_id} Task #{self.order}'


class RoomPlayer(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='players')
    player = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='room_entries')
    chosen_difficulty = models.PositiveSmallIntegerField(choices=DIFFICULTY_CHOICES, default=2)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Игрок в комнате'
        verbose_name_plural = 'Игроки в комнатах'
        unique_together = [('room', 'player')]

    def __str__(self):
        return f'{self.player} in Room {self.room.uuid}'


class PlayerResult(models.Model):
    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name='results')
    player = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='results')
    session_task = models.ForeignKey(SessionTask, on_delete=models.CASCADE, related_name='results')
    given_answer = models.CharField(max_length=512, null=True, blank=True)
    is_correct = models.BooleanField(null=True)
    score_delta = models.SmallIntegerField(default=0)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Результат игрока'
        verbose_name_plural = 'Результаты игроков'
        unique_together = [('session', 'player', 'session_task')]

    def __str__(self):
        return f'Player {self.player_id} Task {self.session_task.order}: {self.score_delta}'


class PlayerSessionSummary(models.Model):
    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name='summaries')
    player = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='summaries')
    total_score = models.IntegerField(default=0)
    correct_count = models.PositiveSmallIntegerField(default=0)
    wrong_count = models.PositiveSmallIntegerField(default=0)
    skipped_count = models.PositiveSmallIntegerField(default=0)
    place = models.PositiveSmallIntegerField(null=True)
    chosen_difficulty = models.PositiveSmallIntegerField()

    class Meta:
        verbose_name = 'Итог игрока за сессию'
        verbose_name_plural = 'Итоги игроков за сессии'
        unique_together = [('session', 'player')]

    def __str__(self):
        return f'Player {self.player_id} Session #{self.session_id}: {self.total_score} pts (#{self.place})'
