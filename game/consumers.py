import asyncio
import json
import random

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from .models import (
    GameSession, PlayerResult, PlayerSessionSummary, Room, RoomPlayer,
    SessionTask, Task, TelegramUser,
)

# Shared game state across consumer instances
_game_states = {}

# Track connected players and cleanup timers per room
_room_connections = {}   # room_uuid -> set of channel_names
_room_cleanup_timers = {}  # room_uuid -> asyncio.Task

ROOM_EMPTY_TIMEOUT = 120  # seconds

BID_TIME = 60
SOLVE_TIME = 150
BID_VALUES = [1, 2, 3, 4, 5]


def get_game_state(session_id):
    if session_id not in _game_states:
        _game_states[session_id] = {
            'current_order': 0,
            'phase': 'idle',
            'bids': {},
            'answered': set(),
            'players': {},
            'total_tasks': 0,
            'started': False,
            'timers': {},
            'round_subject': None,
            'round_task_type': None,
            'player_tasks': {},
            'player_session_tasks': {},
        }
    return _game_states[session_id]


class RoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_uuid = self.scope['url_route']['kwargs']['room_uuid']
        self.group_name = f'room_{self.room_uuid}'
        self.player_id = self.scope['session'].get('player_id')

        if not self.player_id:
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        player_info = await self._join_room()
        if player_info is None:
            await self.close()
            return

        # Track connection and cancel cleanup timer
        room_key = self.room_uuid
        if room_key not in _room_connections:
            _room_connections[room_key] = set()
        _room_connections[room_key].add(self.channel_name)

        cleanup_timer = _room_cleanup_timers.pop(room_key, None)
        if cleanup_timer:
            cleanup_timer.cancel()

        await self.channel_layer.group_send(self.group_name, {
            'type': 'player_joined',
            'player': player_info,
        })

        room_state = await self._get_room_state()
        await self.send(text_data=json.dumps({
            'type': 'room_state',
            **room_state,
        }))

    async def disconnect(self, close_code):
        if hasattr(self, 'player_id') and self.player_id:
            await self.channel_layer.group_send(self.group_name, {
                'type': 'player_left',
                'tg_id': await self._get_tg_id(),
            })

        # Untrack connection and schedule cleanup if room is empty
        room_key = self.room_uuid
        conns = _room_connections.get(room_key)
        if conns:
            conns.discard(self.channel_name)
            if not conns:
                del _room_connections[room_key]
                _room_cleanup_timers[room_key] = asyncio.ensure_future(
                    self._cleanup_empty_room(room_key)
                )

        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get('type')

        if msg_type == 'settings_update':
            if await self._is_creator():
                await self._update_settings(data)
                await self.channel_layer.group_send(self.group_name, {
                    'type': 'settings_updated',
                    'settings': data.get('settings', {}),
                })

        elif msg_type == 'game_start':
            if await self._is_creator():
                session_id = await self._start_game()
                if session_id:
                    await self.channel_layer.group_send(self.group_name, {
                        'type': 'redirect_to_game',
                        'session_id': session_id,
                    })

    async def player_joined(self, event):
        await self.send(text_data=json.dumps({
            'type': 'player_joined',
            'player': event['player'],
        }))

    async def player_left(self, event):
        await self.send(text_data=json.dumps({
            'type': 'player_left',
            'tg_id': event['tg_id'],
        }))

    async def settings_updated(self, event):
        await self.send(text_data=json.dumps({
            'type': 'settings_update',
            'settings': event['settings'],
        }))

    async def redirect_to_game(self, event):
        await self.send(text_data=json.dumps({
            'type': 'redirect_to_game',
            'session_id': event['session_id'],
        }))

    @staticmethod
    async def _cleanup_empty_room(room_key):
        """Удалить комнату через 2 минуты, если никто не подключился."""
        await asyncio.sleep(ROOM_EMPTY_TIMEOUT)
        # Проверяем, что за это время никто не подключился
        if room_key in _room_connections:
            return
        _room_cleanup_timers.pop(room_key, None)
        await RoomConsumer._delete_waiting_room(room_key)

    @staticmethod
    @database_sync_to_async
    def _delete_waiting_room(room_key):
        try:
            room = Room.objects.get(uuid=room_key, status='waiting')
            room.delete()
        except Room.DoesNotExist:
            pass

    @database_sync_to_async
    def _join_room(self):
        try:
            room = Room.objects.get(uuid=self.room_uuid, status='waiting')
            player = TelegramUser.objects.get(id=self.player_id)
        except (Room.DoesNotExist, TelegramUser.DoesNotExist):
            return None

        if room.players.count() >= room.max_players:
            return None

        rp, _ = RoomPlayer.objects.get_or_create(room=room, player=player)
        return {
            'tg_id': player.tg_id,
            'username': player.username or player.first_name,
        }

    @database_sync_to_async
    def _get_room_state(self):
        room = Room.objects.get(uuid=self.room_uuid)
        players = []
        for rp in room.players.select_related('player').all():
            players.append({
                'tg_id': rp.player.tg_id,
                'username': rp.player.username or rp.player.first_name,
            })
        return {
            'subjects': room.subjects,
            'task_count': room.task_count,
            'max_players': room.max_players,
            'creator_tg_id': room.creator.tg_id if room.creator else None,
            'players': players,
        }

    @database_sync_to_async
    def _is_creator(self):
        try:
            room = Room.objects.select_related('creator').get(uuid=self.room_uuid)
            return room.creator_id == self.player_id
        except Room.DoesNotExist:
            return False

    @database_sync_to_async
    def _get_tg_id(self):
        try:
            return TelegramUser.objects.get(id=self.player_id).tg_id
        except TelegramUser.DoesNotExist:
            return None

    @database_sync_to_async
    def _update_settings(self, data):
        settings = data.get('settings', {})
        room = Room.objects.get(uuid=self.room_uuid)
        if 'subjects' in settings:
            room.subjects = settings['subjects']
        if 'task_count' in settings:
            room.task_count = max(1, min(20, int(settings['task_count'])))
        room.save()

    @database_sync_to_async
    def _start_game(self):
        room = Room.objects.get(uuid=self.room_uuid)
        if room.status != 'waiting':
            return None

        subjects = room.subjects or ['math', 'russian']
        if not Task.objects.filter(subject__in=subjects).exists():
            return None

        room.status = 'in_progress'
        room.save()

        session = GameSession.objects.create(room=room)
        return session.id


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = int(self.scope['url_route']['kwargs']['session_id'])
        self.group_name = f'game_{self.session_id}'
        self.player_id = self.scope['session'].get('player_id')

        if not self.player_id:
            await self.close()
            return

        self.tg_id = await self._get_tg_id()

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        session_info = await self._get_session_info()
        if not session_info:
            await self.close()
            return

        state = get_game_state(self.session_id)
        state['players'][self.player_id] = self.channel_name
        state['total_tasks'] = session_info['total_tasks']
        if 'room_settings' not in state:
            state['room_settings'] = session_info.get('room_settings', {})
        if 'expected_players' not in state:
            state['expected_players'] = session_info.get('expected_players', 1)

        # Отправить текущий счёт при подключении
        scores = await self._get_scores()
        await self.send(text_data=json.dumps({
            'type': 'score_update',
            'scores': scores,
        }))

        if not state['started']:
            # Все игроки подключились — стартуем сразу
            if len(state['players']) >= state['expected_players']:
                state['started'] = True
                await self._start_bid(0)
            elif not state.get('start_timer'):
                # Первый игрок — запускаем таймер ожидания остальных
                state['start_timer'] = asyncio.ensure_future(
                    self._wait_and_start()
                )
        elif state['phase'] == 'bidding':
            # Игрок подключился после начала раунда — отправить ему текущий bid_start
            await self.send(text_data=json.dumps({
                'type': 'bid_start',
                'order': state['current_order'],
                'subject': state['round_subject'],
                'task_type': state['round_task_type'],
                'bid_time': BID_TIME,
                'total_tasks': state['total_tasks'],
            }))
            # Отправить уже сделанные ставки
            for pid, diff in state['bids'].items():
                tg_id = await self._get_tg_id_for(pid)
                username = await self._get_username_for(pid)
                await self.send(text_data=json.dumps({
                    'type': 'player_bid',
                    'tg_id': tg_id,
                    'username': username,
                    'difficulty': diff,
                }))

    async def disconnect(self, close_code):
        state = get_game_state(self.session_id)
        state['players'].pop(self.player_id, None)
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if not state['players']:
            _game_states.pop(self.session_id, None)

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get('type')
        state = get_game_state(self.session_id)

        if msg_type == 'choose_difficulty':
            difficulty = data.get('difficulty', 1)
            if difficulty not in BID_VALUES:
                difficulty = 1
            if state['phase'] != 'bidding':
                return
            if self.player_id in state['bids']:
                return

            state['bids'][self.player_id] = difficulty

            task_result = await self._select_task_for_player(
                state['round_subject'], state['round_task_type'],
                difficulty, state['current_order'],
            )

            if task_result:
                state['player_tasks'][self.player_id] = task_result['task_id']
                state['player_session_tasks'][self.player_id] = task_result['session_task_id']
                task_data = task_result['task_data']
            else:
                task_data = None

            username = await self._get_username_for(self.player_id)
            await self.channel_layer.group_send(self.group_name, {
                'type': 'player_bid',
                'tg_id': self.tg_id,
                'username': username,
                'difficulty': difficulty,
            })

            if task_data:
                await self.channel_layer.send(self.channel_name, {
                    'type': 'task_start',
                    'task': task_data,
                })

            timer = asyncio.ensure_future(
                self._player_solve_timer(self.player_id, state['current_order'])
            )
            state['timers'][self.player_id] = timer

            if len(state['bids']) >= len(state['players']):
                bid_timer = state.get('bid_timer')
                if bid_timer:
                    bid_timer.cancel()

        elif msg_type == 'answer_submitted':
            answer = data.get('answer', '')
            await self._handle_answer(answer)

        elif msg_type == 'skip_task':
            await self._handle_answer(None, skipped=True)

        elif msg_type == 'new_game':
            if state['phase'] != 'finished':
                return
            if state.get('new_game_created'):
                return
            state['new_game_created'] = True
            room_uuid = await self._create_new_room(state)
            if room_uuid:
                await self.channel_layer.group_send(self.group_name, {
                    'type': 'redirect_to_lobby',
                    'room_uuid': room_uuid,
                })

    async def _wait_and_start(self):
        """Ждём до 3 секунд, пока все игроки подключатся."""
        state = get_game_state(self.session_id)
        for _ in range(30):  # 30 * 0.1 = 3 секунды
            await asyncio.sleep(0.1)
            if state.get('started'):
                return
            if len(state['players']) >= state.get('expected_players', 1):
                break
        if not state.get('started'):
            state['started'] = True
            await self._start_bid(0)

    async def _start_bid(self, order):
        state = get_game_state(self.session_id)
        state['current_order'] = order
        state['phase'] = 'bidding'
        state['bids'] = {}
        state['answered'] = set()
        state['player_tasks'] = {}
        state['player_session_tasks'] = {}
        for t in state.get('timers', {}).values():
            t.cancel()
        state['timers'] = {}

        if order >= state['total_tasks']:
            await self._finish_game()
            return

        topic = await self._pick_round_topic()
        if not topic:
            await self._finish_game()
            return

        state['round_subject'] = topic['subject']
        state['round_task_type'] = topic['task_type']

        await self.channel_layer.group_send(self.group_name, {
            'type': 'bid_start',
            'data': {
                'order': order,
                'subject': topic['subject'],
                'task_type': topic['task_type'],
                'bid_time': BID_TIME,
                'total_tasks': state['total_tasks'],
            },
        })

        state['bid_timer'] = asyncio.ensure_future(self._bid_countdown(order))

    async def _bid_countdown(self, order):
        state = get_game_state(self.session_id)
        await asyncio.sleep(BID_TIME)
        if state['current_order'] != order or state['phase'] != 'bidding':
            return
        await self._force_bids(order)

    async def _force_bids(self, order):
        state = get_game_state(self.session_id)
        if state['current_order'] != order or state['phase'] != 'bidding':
            return

        unbid = [pid for pid in state['players'] if pid not in state['bids']]

        for pid in unbid:
            state['bids'][pid] = 1
            tg_id = await self._get_tg_id_for(pid)

            task_result = await self._select_task_for_player(
                state['round_subject'], state['round_task_type'], 1, order,
            )

            if task_result:
                state['player_tasks'][pid] = task_result['task_id']
                state['player_session_tasks'][pid] = task_result['session_task_id']

            username = await self._get_username_for(pid)
            await self.channel_layer.group_send(self.group_name, {
                'type': 'player_bid',
                'tg_id': tg_id,
                'username': username,
                'difficulty': 1,
            })

            channel = state['players'].get(pid)
            if channel and task_result:
                await self.channel_layer.send(channel, {
                    'type': 'task_start',
                    'task': task_result['task_data'],
                })
                timer = asyncio.ensure_future(
                    self._player_solve_timer(pid, order)
                )
                state['timers'][pid] = timer

    async def _player_solve_timer(self, player_id, order):
        state = get_game_state(self.session_id)
        await asyncio.sleep(SOLVE_TIME)
        if state['current_order'] != order:
            return
        if player_id not in state['answered']:
            await self._force_player_timeout(player_id, order)

    async def _force_player_timeout(self, player_id, order):
        state = get_game_state(self.session_id)
        if player_id in state['answered']:
            return
        state['answered'].add(player_id)

        bid = state['bids'].get(player_id, 1)
        session_task_id = state['player_session_tasks'].get(player_id)
        if not session_task_id:
            if len(state['answered']) >= len(state['players']):
                await self._end_task()
            return

        result = await self._record_answer(player_id, session_task_id, None, bid)

        if result:
            channel = state['players'].get(player_id)
            if channel:
                await self.channel_layer.send(channel, {
                    'type': 'direct_message',
                    'data': {
                        'type': 'answer_result',
                        'is_correct': result['is_correct'],
                        'correct_answer': result['correct_answer'],
                        'score_delta': result['score_delta'],
                    },
                })

        await self.channel_layer.group_send(self.group_name, {
            'type': 'score_update',
            'scores': await self._get_scores(),
        })

        if len(state['answered']) >= len(state['players']):
            await self._end_task()

    async def _handle_answer(self, answer, skipped=False):
        state = get_game_state(self.session_id)
        if self.player_id in state['answered']:
            return
        state['answered'].add(self.player_id)

        timer = state['timers'].get(self.player_id)
        if timer:
            timer.cancel()

        bid = state['bids'].get(self.player_id, 1)
        session_task_id = state['player_session_tasks'].get(self.player_id)
        if not session_task_id:
            return

        result = await self._record_answer(self.player_id, session_task_id, answer, bid)

        if result:
            await self.send(text_data=json.dumps({
                'type': 'answer_result',
                'is_correct': result['is_correct'],
                'correct_answer': result['correct_answer'],
                'score_delta': result['score_delta'],
                'skipped': skipped,
            }))

        await self.channel_layer.group_send(self.group_name, {
            'type': 'score_update',
            'scores': await self._get_scores(),
        })

        if len(state['answered']) >= len(state['players']):
            await self._end_task()

    async def _end_task(self):
        state = get_game_state(self.session_id)
        order = state['current_order']
        state['phase'] = 'showing_answer'

        await self.channel_layer.group_send(self.group_name, {
            'type': 'task_end',
            'correct_answer': '',
        })
        await asyncio.sleep(3)

        next_order = order + 1
        if next_order >= state['total_tasks']:
            await self._finish_game()
        else:
            await self._start_bid(next_order)

    async def _finish_game(self):
        state = get_game_state(self.session_id)
        state['phase'] = 'finished'
        results = await self._calculate_results()
        await self.channel_layer.group_send(self.group_name, {
            'type': 'game_over',
            'results': results,
        })

    # --- Channel layer handlers ---

    async def bid_start(self, event):
        await self.send(text_data=json.dumps({
            'type': 'bid_start',
            **event['data'],
        }))

    async def player_bid(self, event):
        await self.send(text_data=json.dumps({
            'type': 'player_bid',
            'tg_id': event['tg_id'],
            'username': event.get('username', ''),
            'difficulty': event['difficulty'],
        }))

    async def task_start(self, event):
        await self.send(text_data=json.dumps({
            'type': 'task_start',
            **event['task'],
        }))

    async def score_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'score_update',
            'scores': event['scores'],
        }))

    async def task_end(self, event):
        await self.send(text_data=json.dumps({
            'type': 'task_end',
            'correct_answer': event['correct_answer'],
        }))

    async def game_over(self, event):
        await self.send(text_data=json.dumps({
            'type': 'game_over',
            'results': event['results'],
        }))

    async def redirect_to_lobby(self, event):
        await self.send(text_data=json.dumps({
            'type': 'redirect_to_lobby',
            'room_uuid': event['room_uuid'],
        }))

    async def direct_message(self, event):
        await self.send(text_data=json.dumps(event['data']))

    # --- DB helpers ---

    @database_sync_to_async
    def _create_new_room(self, state):
        try:
            creator = TelegramUser.objects.get(id=self.player_id)
        except TelegramUser.DoesNotExist:
            return None

        room_settings = state.get('room_settings', {})
        room = Room.objects.create(
            creator=creator,
            subjects=room_settings.get('subjects', ['math', 'russian']),
            task_count=room_settings.get('task_count', 5),
        )
        return str(room.uuid)

    @database_sync_to_async
    def _get_session_info(self):
        try:
            session = GameSession.objects.select_related('room').get(id=self.session_id)
            room = session.room
            if not room:
                return None
            expected_players = RoomPlayer.objects.filter(room=room).count()
            return {
                'total_tasks': room.task_count,
                'expected_players': expected_players,
                'room_settings': {
                    'subjects': room.subjects,
                    'task_count': room.task_count,
                },
            }
        except GameSession.DoesNotExist:
            return None

    @database_sync_to_async
    def _pick_round_topic(self):
        session = GameSession.objects.select_related('room').get(id=self.session_id)
        subjects = session.room.subjects or ['math', 'russian']

        available_subjects = list(
            Task.objects.filter(subject__in=subjects)
            .values_list('subject', flat=True).distinct()
        )
        if not available_subjects:
            return None
        subject = random.choice(available_subjects)

        available_types = list(
            Task.objects.filter(subject=subject)
            .values_list('task_type', flat=True).distinct()
        )
        if not available_types:
            return None
        task_type = random.choice(available_types)

        return {'subject': subject, 'task_type': task_type}

    @database_sync_to_async
    def _select_task_for_player(self, subject, task_type, difficulty, order):
        # Exact match: subject + task_type + difficulty
        tasks = list(Task.objects.filter(
            subject=subject, task_type=task_type, difficulty=difficulty,
        ))

        if not tasks:
            # Fallback: same subject + type, any difficulty
            tasks = list(Task.objects.filter(subject=subject, task_type=task_type))

        if not tasks:
            return None

        task = random.choice(tasks)

        st, _ = SessionTask.objects.get_or_create(
            session_id=self.session_id,
            task=task,
            defaults={'order': order, 'time_limit': SOLVE_TIME},
        )

        images = list(task.images.values_list('url', flat=True))
        answers = list(task.answers.order_by('order').values('text', 'order'))

        return {
            'task_id': task.id,
            'session_task_id': st.id,
            'task_data': {
                'order': order,
                'text': task.text,
                'images': images,
                'answers': answers,
                'time_limit': SOLVE_TIME,
                'task_type': task.task_type,
                'subject': task.subject,
            },
        }

    @database_sync_to_async
    def _get_tg_id(self):
        try:
            return TelegramUser.objects.get(id=self.player_id).tg_id
        except TelegramUser.DoesNotExist:
            return None

    @database_sync_to_async
    def _get_tg_id_for(self, player_id):
        try:
            return TelegramUser.objects.get(id=player_id).tg_id
        except TelegramUser.DoesNotExist:
            return None

    @database_sync_to_async
    def _get_username_for(self, player_id):
        try:
            p = TelegramUser.objects.get(id=player_id)
            return p.username or p.first_name
        except TelegramUser.DoesNotExist:
            return ''

    @database_sync_to_async
    def _record_answer(self, player_id, session_task_id, answer, bid):
        try:
            st = SessionTask.objects.select_related('task').get(id=session_task_id)
        except SessionTask.DoesNotExist:
            return None

        if PlayerResult.objects.filter(
            session_id=self.session_id, player_id=player_id, session_task=st
        ).exists():
            return None

        task = st.task

        if answer is None:
            is_correct = None
            score_delta = -bid * 10
        else:
            is_correct = self._check_answer(task, answer)
            score_delta = bid * 10 if is_correct else -bid * 10

        PlayerResult.objects.create(
            session_id=self.session_id,
            player_id=player_id,
            session_task=st,
            given_answer=answer,
            is_correct=is_correct,
            score_delta=score_delta,
            answered_at=timezone.now() if answer is not None else None,
        )

        correct_answers = list(task.answers.filter(is_correct=True).values_list('text', flat=True))
        correct_answer_text = ', '.join(correct_answers) if correct_answers else (task.correct_answer or '')

        return {
            'is_correct': is_correct,
            'correct_answer': correct_answer_text,
            'score_delta': score_delta,
        }

    def _normalize_answer(self, text):
        return text.strip().lower().replace(',', '.')

    def _check_answer(self, task, answer):
        normalized = self._normalize_answer(answer)
        task_answers = list(task.answers.all())
        if task_answers:
            correct_texts = [self._normalize_answer(a.text) for a in task_answers if a.is_correct]
            return normalized in correct_texts
        if task.correct_answer:
            correct_variants = [self._normalize_answer(v) for v in task.correct_answer.split('|')]
            return normalized in correct_variants
        return False

    @database_sync_to_async
    def _get_scores(self):
        from django.db.models import Sum
        session = GameSession.objects.get(id=self.session_id)
        players = RoomPlayer.objects.filter(room=session.room).select_related('player')
        scores = []
        for rp in players:
            total = PlayerResult.objects.filter(
                session=session, player=rp.player
            ).aggregate(total=Sum('score_delta'))['total'] or 0
            scores.append({
                'tg_id': rp.player.tg_id,
                'username': rp.player.username or rp.player.first_name,
                'total_score': total,
            })
        return sorted(scores, key=lambda x: x['total_score'], reverse=True)

    @database_sync_to_async
    def _calculate_results(self):
        from django.db.models import Sum, Count, Q
        session = GameSession.objects.get(id=self.session_id)

        if session.status == 'finished':
            summaries_qs = PlayerSessionSummary.objects.filter(
                session=session
            ).select_related('player').order_by('place')
            return [{
                'tg_id': s.player.tg_id,
                'username': s.player.username or s.player.first_name,
                'total_score': s.total_score,
                'correct_count': s.correct_count,
                'wrong_count': s.wrong_count,
                'skipped_count': s.skipped_count,
                'place': s.place,
            } for s in summaries_qs]

        session.status = 'finished'
        session.finished_at = timezone.now()
        session.save()

        room = session.room
        players = RoomPlayer.objects.filter(room=room).select_related('player')
        summaries = []
        for rp in players:
            agg = PlayerResult.objects.filter(
                session=session, player=rp.player
            ).aggregate(
                total=Sum('score_delta'),
                correct=Count('id', filter=Q(is_correct=True)),
                wrong=Count('id', filter=Q(is_correct=False)),
                skipped=Count('id', filter=Q(is_correct__isnull=True)),
            )
            summaries.append({
                'player': rp.player,
                'total_score': agg['total'] or 0,
                'correct_count': agg['correct'],
                'wrong_count': agg['wrong'],
                'skipped_count': agg['skipped'],
            })

        summaries.sort(key=lambda x: x['total_score'], reverse=True)

        results = []
        for place, s in enumerate(summaries, 1):
            PlayerSessionSummary.objects.get_or_create(
                session=session,
                player=s['player'],
                defaults={
                    'total_score': s['total_score'],
                    'correct_count': s['correct_count'],
                    'wrong_count': s['wrong_count'],
                    'skipped_count': s['skipped_count'],
                    'place': place,
                    'chosen_difficulty': 0,
                },
            )
            s['player'].total_score += s['total_score']
            s['player'].games_played += 1
            s['player'].save()

            results.append({
                'tg_id': s['player'].tg_id,
                'username': s['player'].username or s['player'].first_name,
                'total_score': s['total_score'],
                'correct_count': s['correct_count'],
                'wrong_count': s['wrong_count'],
                'skipped_count': s['skipped_count'],
                'place': place,
            })

        # Delete room after all results are saved
        if room:
            session.room = None
            session.save(update_fields=['room'])
            room.delete()

        return results
