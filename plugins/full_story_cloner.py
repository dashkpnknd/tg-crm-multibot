import asyncio
from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError, AuthKeyUnregistered, SessionRevoked, UserDeactivated
from pyrogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
import modules.accounts_storage
from modules import db
from modules.filters import *
from modules.message import send_msg
from plugins.add_account import get_back_kb

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
    while True:
        try:
            active_full_story_cloner = db.FullStoryCloner.get_by_account_id(app.me.id)
            for full_story_cloner in active_full_story_cloner:
                async for story in app.get_pinned_stories(full_story_cloner.username):
                    if story.id in full_story_cloner.copied:
                        continue  # Пропускаем уже скопированные истории
                    # Проверяем настройки пропуска историй с "@"
                    if full_story_cloner.skip_stories_with_at and story.caption and "@" in story.caption:
                        continue  # Пропускаем историю, если в подписи есть "@"
                    # Получаем ID файла из истории
                    file_id = getattr(story.photo, 'file_id', None) or getattr(story.video, 'file_id', None)
                    if not file_id:
                        continue
                    # Отправляем историю себе
                    await app.send_story(
                        chat_id="<REDACTED>"
                        media=file_id,
                        caption=story.caption,
                        period=full_story_cloner.publish_duration * 3600,
                        pinned=True,
                        protect_content=full_story_cloner.is_copy_prohibited
                    )
                    db.Analytics.create_record(
                        app.me.id,
                        'Скопировал закрепленную историю',
                        details=f"Источник: {full_story_cloner.username}"
                    )
                    full_story_cloner.copied.append(story.id)
                    db.FullStoryCloner.update_by_id(full_story_cloner.id, copied=full_story_cloner.copied)
                    for _ in range(full_story_cloner.interval):
                        await asyncio.sleep(60)
                        active_full_story_cloner = db.FullStoryCloner.get_by_account_id(app.me.id)
                        if not active_full_story_cloner or active_full_story_cloner[0].id != full_story_cloner.id:
                            break
                    active_full_story_cloner = db.FullStoryCloner.get_by_account_id(app.me.id)
                    if not active_full_story_cloner or active_full_story_cloner[0].id != full_story_cloner.id:
                        break
                else:
                    db.FullStoryCloner.delete_by_id(full_story_cloner.id)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except RPCError as e:
            await asyncio.sleep(60)
        except (AuthKeyUnregistered, SessionRevoked, UserDeactivated) as e:
            await modules.accounts_storage.de_launch_account(app.me.id)
            return
        except Exception as e:
            print(f"FullStoryCloner Unexpected error: {e}")
        # Ждем перед следующей проверкой
        await asyncio.sleep(60)
