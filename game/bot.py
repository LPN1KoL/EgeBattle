import hashlib
import hmac

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.deep_linking import create_start_link
from django.conf import settings

router = Router()


def make_auth_link(room_uuid: str, tg_id: int, username: str, first_name: str, base_url: str) -> str:
    secret = settings.HMAC_SECRET
    msg = f'{tg_id}:{username}'.encode()
    h = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f'{base_url}/room/{room_uuid}/?tg_id={tg_id}&username={username}&first_name={first_name}&hash={h}'


@router.message(CommandStart(deep_link=True))
async def cmd_start_deep(message: Message, bot: Bot):
    """Друг перешёл по ссылке t.me/bot?start=<room_uuid>"""
    room_uuid = message.text.split(maxsplit=1)[1] if ' ' in message.text else ''
    if not room_uuid:
        return await cmd_start_plain(message)

    from game.models import Room, TelegramUser

    try:
        room = await Room.objects.select_related('creator').aget(uuid=room_uuid)
    except Room.DoesNotExist:
        await message.answer('Комната не найдена или уже завершена.')
        return

    if room.status != 'waiting':
        await message.answer('Игра в этой комнате уже началась или завершена.')
        return

    player, _ = await TelegramUser.objects.aget_or_create(
        tg_id=message.from_user.id,
        defaults={
            'username': message.from_user.username or '',
            'first_name': message.from_user.first_name or 'Player',
        },
    )

    base_url = settings.BASE_URL
    link = make_auth_link(
        str(room.uuid),
        message.from_user.id,
        message.from_user.username or message.from_user.first_name,
        message.from_user.first_name or 'Player',
        base_url,
    )

    creator_name = ''
    if room.creator:
        creator_name = room.creator.username or room.creator.first_name

    await message.answer(
        f'Тебя пригласили в комнату!\n'
        f'Создатель: {creator_name}\n\n'
        f'Твоя персональная ссылка:\n{link}'
    )


@router.message(CommandStart(deep_link=False))
async def cmd_start_plain(message: Message):
    """Обычный /start без параметров"""
    await message.answer(
        'EGE Battle — многопользовательская игра на решение задач ЕГЭ!\n\n'
        'Команды:\n'
        '/play — создать комнату и пригласить друзей\n'
        '/games — открытые комнаты\n'
        '/leaderboard — таблица лидеров'
    )


@router.message(Command('play'))
async def cmd_play(message: Message, bot: Bot):
    from game.models import Room, TelegramUser

    player, _ = await TelegramUser.objects.aget_or_create(
        tg_id=message.from_user.id,
        defaults={
            'username': message.from_user.username or '',
            'first_name': message.from_user.first_name or 'Player',
        },
    )

    room = await Room.objects.acreate(
        creator=player,
        subjects=['math', 'russian'],
        task_count=5,
    )

    base_url = settings.BASE_URL
    my_link = make_auth_link(
        str(room.uuid),
        message.from_user.id,
        message.from_user.username or message.from_user.first_name,
        message.from_user.first_name or 'Player',
        base_url,
    )

    invite_link = await create_start_link(bot, str(room.uuid))

    await message.answer(
        f'Комната создана!\n\n'
        f'Твоя ссылка для входа:\n{my_link}\n\n'
        f'Ссылка-приглашение для друзей:\n{invite_link}\n'
        f'Отправь её друзьям — каждый получит свою персональную ссылку.'
    )


@router.message(Command('games'))
async def cmd_games(message: Message):
    """Показать комнаты в режиме ожидания"""
    from game.models import Room

    rooms = []
    async for room in Room.objects.filter(status='waiting').select_related('creator').order_by('-created_at')[:10]:
        rooms.append(room)

    if not rooms:
        await message.answer('Сейчас нет открытых комнат. Создай свою — /play')
        return

    base_url = settings.BASE_URL
    buttons = []
    for room in rooms:
        creator_name = ''
        if room.creator:
            creator_name = room.creator.username or room.creator.first_name
        label = creator_name
        link = make_auth_link(
            str(room.uuid),
            message.from_user.id,
            message.from_user.username or message.from_user.first_name,
            message.from_user.first_name or 'Player',
            base_url,
        )
        buttons.append([InlineKeyboardButton(text=label, url=link)])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer('Открытые комнаты:', reply_markup=keyboard)


@router.message(Command('leaderboard'))
async def cmd_leaderboard(message: Message):
    base_url = settings.BASE_URL
    await message.answer(f'Таблица лидеров:\n{base_url}/leaderboard/')


def get_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


def get_bot() -> Bot:
    return Bot(token=settings.BOT_TOKEN)
