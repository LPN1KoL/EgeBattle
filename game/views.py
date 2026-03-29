import asyncio
import hashlib
import hmac
import json

from django.conf import settings
from collections import defaultdict

from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt

from .models import (
    GameSession, PlayerResult, PlayerSessionSummary, Room, SUBJECT_CHOICES, TelegramUser,
)


def home_view(request):
    return render(request, 'game/home.html', {
        'bot_username': settings.BOT_USERNAME,
        'player_id': request.session.get('player_id'),
    })


def auth_view(request, room_uuid):
    tg_id = request.GET.get('tg_id')
    username = request.GET.get('username', '')
    first_name = request.GET.get('first_name', username)
    received_hash = request.GET.get('hash', '')

    if not tg_id or not received_hash:
        return HttpResponseForbidden('Missing parameters')

    secret = settings.HMAC_SECRET
    if not secret:
        return HttpResponseForbidden('Server misconfigured')

    msg = f'{tg_id}:{username}'.encode()
    expected_hash = hmac.new(
        secret.encode(), msg, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(received_hash, expected_hash):
        return HttpResponseForbidden('Invalid signature')

    player, _ = TelegramUser.objects.get_or_create(
        tg_id=int(tg_id),
        defaults={'username': username, 'first_name': first_name or 'Player'},
    )
    if username and player.username != username:
        player.username = username
        player.save(update_fields=['username'])

    request.session['player_id'] = player.id
    return redirect('lobby', room_uuid=room_uuid)


def dev_auth_view(request, room_uuid):
    """Dev-only auth without HMAC — for testing."""
    tg_id = request.GET.get('tg_id', '12345')
    username = request.GET.get('username', 'dev_user')
    first_name = request.GET.get('first_name', username)

    player, _ = TelegramUser.objects.get_or_create(
        tg_id=int(tg_id),
        defaults={'username': username, 'first_name': first_name or 'Player'},
    )
    request.session['player_id'] = player.id
    return redirect('lobby', room_uuid=room_uuid)


def lobby_view(request, room_uuid):
    player_id = request.session.get('player_id')
    if not player_id:
        return HttpResponseForbidden('Not authenticated')

    room = get_object_or_404(Room, uuid=room_uuid)
    player = get_object_or_404(TelegramUser, id=player_id)

    return render(request, 'game/lobby.html', {
        'room': room,
        'player': player,
        'room_uuid': str(room_uuid),
        'bot_username': settings.BOT_USERNAME,
    })


def game_view(request, session_id):
    player_id = request.session.get('player_id')
    if not player_id:
        return HttpResponseForbidden('Not authenticated')

    session = get_object_or_404(GameSession, id=session_id)
    player = get_object_or_404(TelegramUser, id=player_id)

    return render(request, 'game/game.html', {
        'session': session,
        'player': player,
        'session_id': session_id,
        'room_uuid': str(session.room.uuid),
    })


def result_view(request, session_id):
    player_id = request.session.get('player_id')
    if not player_id:
        return HttpResponseForbidden('Not authenticated')

    session = get_object_or_404(GameSession, id=session_id)
    summaries = session.summaries.select_related('player').order_by('place')

    return render(request, 'game/result.html', {
        'session': session,
        'summaries': summaries,
    })


def leaderboard_view(request):
    players = TelegramUser.objects.filter(
        games_played__gt=0
    ).order_by('-total_score')[:50]

    return render(request, 'game/leaderboard.html', {
        'players': players,
    })


def profile_view(request):
    player_id = request.session.get('player_id')
    if not player_id:
        return HttpResponseForbidden('Not authenticated')

    player = get_object_or_404(TelegramUser, id=player_id)
    history = PlayerSessionSummary.objects.filter(
        player=player
    ).select_related('session', 'session__room').order_by('-session__started_at')

    # Subject/type statistics
    subject_names = dict(SUBJECT_CHOICES)
    stats_qs = (
        PlayerResult.objects.filter(player=player)
        .values('session_task__task__subject', 'session_task__task__task_type')
        .annotate(
            total=Count('id'),
            correct=Count('id', filter=Q(is_correct=True)),
        )
        .order_by('session_task__task__subject', 'session_task__task__task_type')
    )

    subject_stats = defaultdict(lambda: {'total': 0, 'correct': 0, 'types': {}})
    for row in stats_qs:
        subj = row['session_task__task__subject']
        ttype = row['session_task__task__task_type']
        total = row['total']
        correct = row['correct']
        s = subject_stats[subj]
        s['total'] += total
        s['correct'] += correct
        s['types'][ttype] = {'total': total, 'correct': correct}

    subject_stats_list = []
    for subj, data in sorted(subject_stats.items(), key=lambda x: x[0]):
        types_list = sorted(data['types'].items())
        subject_stats_list.append({
            'name': subject_names.get(subj, subj),
            'total': data['total'],
            'correct': data['correct'],
            'types': [{'type': t, 'total': d['total'], 'correct': d['correct']} for t, d in types_list],
        })

    avg_score = round(player.total_score / player.games_played, 1) if player.games_played > 0 else 0

    return render(request, 'game/profile.html', {
        'player': player,
        'history': history,
        'subject_stats': subject_stats_list,
        'avg_score': avg_score,
    })


def new_game_view(request):
    player_id = request.session.get('player_id')
    if not player_id:
        return HttpResponseForbidden('Not authenticated')

    player = get_object_or_404(TelegramUser, id=player_id)
    room = Room.objects.create(
        creator=player,
        subjects=['math', 'russian'],
        task_count=5,
    )
    return redirect('lobby', room_uuid=room.uuid)


@csrf_exempt
def webhook_view(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    from aiogram.types import Update
    from .bot import get_bot, get_dispatcher

    bot = get_bot()
    dp = get_dispatcher()

    update = Update.model_validate(json.loads(request.body))
    asyncio.run(dp.feed_update(bot, update))

    return HttpResponse('ok')
