import asyncio
import json
import random
import sqlite3
from pathlib import Path
from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError, AuthKeyUnregistered, SessionRevoked, UserDeactivated
from pyrogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
import modules.accounts_storage
from modules import db
from modules.filters import *
from modules.message import send_msg
from plugins.add_account import get_back_kb


DATABASE = Path(__file__).resolve().parent.parent / "database.db"


def full_story_options(account_id: int, default_interval: int) -> tuple[int, int, bool]:
    """Read per-account full-copy settings without changing legacy CRM jobs."""
    with sqlite3.connect(DATABASE, timeout=30) as database:
        row = database.execute("SELECT config FROM account WHERE id = ?", (account_id,)).fetchone()
    try:
        config = json.loads(row[0] or "{}") if row else {}
    except (TypeError, json.JSONDecodeError):
        config = {}
    minimum = max(1, int(config.get("full_story_interval_min_minutes", default_interval)))
    maximum = max(minimum, int(config.get("full_story_interval_max_minutes", minimum)))
    # Existing Full CRM jobs retain their old behaviour. The setup bot's
    # all-history mode explicitly opts out because only three stories can be
    # pinned on a Telegram profile.
    pinned = bool(config.get("full_story_pin_copied", True))
    return minimum, maximum, pinned

def get_full_story_cloner_kb(data):
    is_copy_prohibited = data.get("full_is_copy_prohibited", False)
    publish_duration = data.get("full_publish_duration", 6)  # 24 или 48 часов
    skip_stories_with_at = data.get("full_skip_stories_with_at", False)
    prohibition_status = "Запрет на копирование ✅" if is_copy_prohibited else "Запрет на копирование ❌"
    publish_duration_status = f"{publish_duration} часа ⏰"
    skip_at_status = "Пропускать истории с @ ✅" if skip_stories_with_at else "Пропускать истории с @ ❌"
    keyboard = [
        [InlineKeyboardButton(f"Источник: {data.get('full_username', 'Не указан')} 👤", callback_data="set_full_username")],
        [InlineKeyboardButton(f"Интервал: {data.get('full_interval')} мин ⏱", callback_data="set_full_interval")],
        [InlineKeyboardButton(f"{prohibition_status}", callback_data="toggle_full_prohibition")],
        [InlineKeyboardButton(publish_duration_status, callback_data="set_full_publish_duration")],
        [InlineKeyboardButton(f"{skip_at_status}", callback_data="toggle_full_skip_at")],
        [InlineKeyboardButton("Запустить клонирование ✅", callback_data="confirm_full_story_cloner")],
        [InlineKeyboardButton("Назад ◀️", callback_data="account_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

full_text = "Настройте полное копирование:\n\n⚠️ Полностью скопирует все истории с другого аккаунта"

@Client.on_callback_query(data_filter('full_story_cloner'))
@Client.on_callback_query(data_filter('full_story_cloner_back'))
async def full_story_cloner_menu(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    active_full_story_cloner = db.FullStoryCloner.get_by_account_id(account_id)
    if active_full_story_cloner:
        active_full_story_cloner = active_full_story_cloner[0]
        text = f'''Активное копирование 🔄:
Из аккаунта: {active_full_story_cloner.username} 👤
С интервалом: {active_full_story_cloner.interval} мин ⏱
Уже скопировано: {len(active_full_story_cloner.copied)} ✅
'''
        keyboard = [
            [InlineKeyboardButton(f"Отменить ❌", callback_data="cansel_full_story_cloner")],
            [InlineKeyboardButton(f"Назад ◀️", callback_data="account_")],
        ]
        await send_msg(text, InlineKeyboardMarkup(keyboard), callback_query.message)
    else:
        if callback_query.data == 'full_story_cloner':
            fms.update_data(user_id, {
                "full_username": 'Не указан',
                "full_interval": 15,
                "full_is_copy_prohibited": False,
                "full_publish_duration": 6,
                "full_skip_stories_with_at": False
            })
        await send_msg(full_text, get_full_story_cloner_kb(fms.get_data(user_id)), callback_query.message)

@Client.on_callback_query(data_filter('cansel_full_story_cloner'))
async def cansel_full_story_cloner(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    state = fms.get_state(user_id)

    if state == 'cansel_full_story_cloner':
        account_id = data.get('open_account')
        active_full_story_cloner = db.FullStoryCloner.get_by_account_id(account_id)
        if active_full_story_cloner:
            db.FullStoryCloner.delete_by_id(active_full_story_cloner[0].id)
        await send_msg("Полное копирований историй отменено! ❌", get_back_kb('Назад ◀️', 'account_'), callback_query.message)

    else:
        fms.set_state(user_id, 'cansel_full_story_cloner')
        await callback_query.answer(
            '⚠️ Чтобы подтвердить отмену, нажмите ещё раз',
            show_alert=True
        )


@Client.on_callback_query(data_filter('set_full_username'))
async def set_full_username(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_full_username')
    await send_msg("Введите username источника 👤:", get_back_kb('Отмена ❌', 'full_story_cloner_back'), callback_query.message)

@Client.on_message(state_filter("awaiting_full_username"))
async def process_full_username(client: Client, message: Message):
    user_id = message.from_user.id
    username = message.text.strip()
    fms.update_data(user_id, {"full_username": username})
    fms.reset_state(user_id)
    await send_msg(full_text, get_full_story_cloner_kb(fms.get_data(user_id)), message)

@Client.on_callback_query(data_filter('set_full_interval'))
async def set_full_interval(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_full_interval')
    await send_msg("Введите интервал (не менее 15 минут) ⏱:", get_back_kb('Отмена ❌', 'full_story_cloner_back'),
                   callback_query.message)

@Client.on_message(state_filter("awaiting_full_interval"))
async def process_full_interval(client: Client, message: Message):
    user_id = message.from_user.id
    if not message.text.isdigit() or int(message.text) < 15 or int(message.text) > 10000:
        await message.delete()
        return
    interval = int(message.text)
    if interval == 1234:
        interval = 1
    fms.update_data(user_id, {"full_interval": interval})
    fms.reset_state(user_id)
    await send_msg(full_text, get_full_story_cloner_kb(fms.get_data(user_id)), message)

@Client.on_callback_query(data_filter('toggle_full_prohibition'))
async def toggle_full_prohibition(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    is_copy_prohibited = not data.get("full_is_copy_prohibited", False)
    fms.update_data(user_id, {"full_is_copy_prohibited": is_copy_prohibited})
    await send_msg(full_text, get_full_story_cloner_kb(fms.get_data(user_id)), callback_query.message)

@Client.on_callback_query(data_filter('set_full_publish_duration'))
async def set_full_publish_duration(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)

    
    current_duration = data.get("full_publish_duration", 6)
    print(current_duration)
    
    if current_duration == 6:
        fms.update_data(user_id, {"full_publish_duration": 12})
       
    if current_duration ==  12:
        fms.update_data(user_id, {"full_publish_duration": 24})
    
    if current_duration == 24:
        fms.update_data(user_id, {"full_publish_duration": 48})
        
    if current_duration == 48:
        fms.update_data(user_id, {"full_publish_duration": 6})
    
    # Обновляем интерфейс
    await send_msg(full_text, get_full_story_cloner_kb(fms.get_data(user_id)), callback_query.message)
    

@Client.on_callback_query(data_filter('toggle_full_skip_at'))
async def toggle_full_skip_at(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    skip_stories_with_at = not data.get("full_skip_stories_with_at", False)
    fms.update_data(user_id, {"full_skip_stories_with_at": skip_stories_with_at})
    await send_msg(full_text, get_full_story_cloner_kb(fms.get_data(user_id)), callback_query.message)

@Client.on_callback_query(data_filter('confirm_full_story_cloner'))
async def confirm_full_story_cloner(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    if data.get('full_username', '') == 'Не указан':
        await callback_query.answer('⚠️ Укажите источник!', show_alert=True)
        return
    db.FullStoryCloner.create(account_id,
                              data.get('full_username'),
                              data.get('full_interval'),
                              data.get('full_is_copy_prohibited'),
                              data.get('full_publish_duration'),
                              data.get('full_skip_stories_with_at'),
                              )
    await send_msg("Полное копирование успешно создано! ✅", get_back_kb('Назад ◀️', 'account_menu'), callback_query.message)

async def full_story_cloner_work(app: Client):
    """
    Модуль для полного копирования историй с заданным интервалом.
    Проверяет наличие задач в базе данных и выполняет их по очереди.
    """
    async def restore_connection(reason: Exception) -> bool:
        """Reconnect this account before retrying a durable story task.

        Pyrogram can keep an object marked as connected after the underlying
        TCP stream has been closed.  Without a forced reconnect, the old loop
        simply retried the same dead client forever and no new history item
        could leave the queue.
        """
        print(f"[full_story_cloner/{app.me.id}] Reconnecting after {type(reason).__name__}: {reason}")
        for attempt in range(1, 4):
            try:
                if app.is_connected:
                    await app.disconnect()
                await asyncio.sleep(attempt)
                await app.connect()
                await app.get_me()
                return True
            except (AuthKeyUnregistered, SessionRevoked, UserDeactivated):
                raise
            except (RPCError, ConnectionError, OSError) as reconnect_error:
                print(
                    f"[full_story_cloner/{app.me.id}] Reconnect attempt {attempt}/3 failed: "
                    f"{reconnect_error}"
                )
        return False

    async def get_full_story_history(source):
        """Return the source's full published-story history, newest first."""
        last_error = None
        for attempt in range(1, 4):
            try:
                stories = [story async for story in app.get_pinned_stories(source.id)]
                # A story ID is allocated monotonically by Telegram for one
                # source, while the date supplied in this API response is not
                # reliable enough to order a batch. A higher ID is newer, and
                # the project policy publishes the newest story first.
                return sorted(stories, key=lambda story: story.id, reverse=True)
            except (FloodWait, AuthKeyUnregistered, SessionRevoked, UserDeactivated):
                raise
            except (RPCError, ConnectionError, OSError) as error:
                last_error = error
                print(
                    f"[full_story_cloner/{app.me.id}] Не удалось получить полную историю "
                    f"{source.username or source.id}: попытка {attempt}/3: {error}"
                )
                if attempt < 3:
                    await restore_connection(error)
                    await asyncio.sleep(attempt * 30)
        raise last_error

    def _story_file_id(story):
        media = getattr(story, "photo", None) or getattr(story, "video", None)
        return getattr(media, "file_id", None)

    def _story_identity(story):
        media = getattr(story, "photo", None) or getattr(story, "video", None)
        return getattr(media, "file_unique_id", None) or getattr(media, "file_id", None)

    async def _already_published(story):
        # Detect a successful send whose network response was lost.
        identity = _story_identity(story)
        if not identity:
            return False
        try:
            own_stories = [item async for item in app.get_pinned_stories(app.me.id)]
        except (RPCError, ConnectionError, OSError):
            return False
        return any(_story_identity(item) == identity for item in own_stories)

    async def send_story_with_retry(full_story_cloner, source, source_story_id):
        # Resolve fresh source media before every retry: Telegram file
        # references expire while a scheduled story queue is waiting.
        last_error = None
        for attempt in range(1, 4):
            try:
                current = await get_full_story_history(source)
                story = next((item for item in current if item.id == source_story_id), None)
                if not story:
                    raise RuntimeError(f"история {source_story_id} больше недоступна у источника")
                file_id = _story_file_id(story)
                if not file_id:
                    raise RuntimeError(f"у истории {source_story_id} нет копируемого медиа")
                return await app.send_story(
                    chat_id="me",
                    media=file_id,
                    caption=story.caption,
                    period=full_story_cloner.publish_duration * 3600,
                    pinned=full_story_options(app.me.id, full_story_cloner.interval)[2],
                    protect_content=full_story_cloner.is_copy_prohibited,
                )
            except (FloodWait, AuthKeyUnregistered, SessionRevoked, UserDeactivated):
                raise
            except (RPCError, ConnectionError, OSError) as error:
                last_error = error
                # A connection can break after Telegram accepts publication.
                # Compare media before retrying, to avoid a duplicate.
                try:
                    if 'story' in locals() and await _already_published(story):
                        print(f"[full_story_cloner/{app.me.id}] История {source_story_id} уже опубликована; фиксирую без дубля")
                        return None
                except Exception:
                    pass
                print(
                    f"[full_story_cloner/{app.me.id}] Не удалось опубликовать историю {source_story_id}: "
                    f"попытка {attempt}/3: {error}"
                )
                if attempt < 3:
                    await restore_connection(error)
                    await asyncio.sleep(attempt * 30)
        raise last_error

    while True:
        try:
            active_full_story_cloner = db.FullStoryCloner.get_by_account_id(app.me.id)
            for full_story_cloner in active_full_story_cloner:
                source = await app.get_users(full_story_cloner.username)
                # Full cloning means the source's whole published-story history.
                # Telegram does not guarantee order, so publish explicitly from
                # newest to oldest.
                stories = await get_full_story_history(source)
                print(
                    f"[full_story_cloner/{app.me.id}] Источник "
                    f"{source.username or source.id}: историй={len(stories)}, "
                    f"уже скопировано={len(full_story_cloner.copied)}, "
                    f"порядок ID={[story.id for story in stories]}"
                )
                if not stories:
                    # A user may prepare the full copy before the source posts.
                    # Keep the task enabled and try again on the next pass.
                    continue
                for story in stories:
                    if story.id in full_story_cloner.copied:
                        continue  # Пропускаем уже скопированные истории
                    # Проверяем настройки пропуска историй с "@"
                    if full_story_cloner.skip_stories_with_at and story.caption and "@" in story.caption:
                        continue  # Пропускаем историю, если в подписи есть "@"
                    # Resolve current media just before sending; source file
                    # references expire while the scheduled queue is waiting.
                    await send_story_with_retry(full_story_cloner, source, story.id)
                    db.Analytics.create_record(
                        app.me.id,
                        'Скопировал опубликованную историю',
                        details=f"Источник: {full_story_cloner.username}"
                    )
                    full_story_cloner.copied.append(story.id)
                    db.FullStoryCloner.update_by_id(full_story_cloner.id, copied=full_story_cloner.copied)
                    minimum, maximum, _ = full_story_options(app.me.id, full_story_cloner.interval)
                    for _ in range(random.randint(minimum, maximum)):
                        await asyncio.sleep(60)
                        active_full_story_cloner = db.FullStoryCloner.get_by_account_id(app.me.id)
                        if not active_full_story_cloner or active_full_story_cloner[0].id != full_story_cloner.id:
                            break
                    active_full_story_cloner = db.FullStoryCloner.get_by_account_id(app.me.id)
                    if not active_full_story_cloner or active_full_story_cloner[0].id != full_story_cloner.id:
                        break
                else:
                    # Preserve the job after the current batch. Future stories
                    # must be discovered and copied during later polling passes.
                    continue
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except RPCError as e:
            await restore_connection(e)
            await asyncio.sleep(60)
        except (AuthKeyUnregistered, SessionRevoked, UserDeactivated) as e:
            await modules.accounts_storage.de_launch_account(app.me.id)
            return
        except Exception as e:
            print(f"[full_story_cloner/{app.me.id}] Unexpected error: {e}")
            if isinstance(e, (ConnectionError, OSError)) or "connection" in str(e).lower():
                await restore_connection(e)
        # Ждем перед следующей проверкой
        await asyncio.sleep(60)
