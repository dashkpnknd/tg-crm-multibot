import random
from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.errors import FloodWait, RPCError, AuthKeyUnregistered, SessionRevoked, UserDeactivated
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from modules import db
from modules.filters import *
from modules.message import send_msg
from plugins.add_account import get_back_kb
import asyncio
import modules

def get_story_reactions_kb(account: db.Account):
    config = account.config or {}
    is_reactions_enabled = config.get("is_reactions_enabled", False)
    reactions_status = "Включено ✅" if is_reactions_enabled else "Выключено ❌"
    keyboard = [
        [InlineKeyboardButton(f"{reactions_status}", callback_data="toggle_reactions")],
        [InlineKeyboardButton("Настроить эмодзи ❤️", callback_data="set_reaction_emojis")],
        [InlineKeyboardButton("Копировать настройки 🔄", callback_data="reaction_copy_settings")],
        [InlineKeyboardButton("Назад ◀️", callback_data="account_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

reaction_text = "Настройки реакций на истории:\n\n⚠️ Будут ставиться реакции на истории всех с кем у вас есть диалог"

@Client.on_callback_query(data_filter('story_reactions'))
async def story_reactions(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    await send_msg(reaction_text, get_story_reactions_kb(account), callback_query.message)

@Client.on_callback_query(data_filter('toggle_reactions'))
async def toggle_reactions(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    is_reactions_enabled = not config.get("is_reactions_enabled", False)
    config["is_reactions_enabled"] = is_reactions_enabled
    db.Account.update_by_id(account_id, config=config)
    account = db.Account.get_by_id(account_id)
    await send_msg(reaction_text, get_story_reactions_kb(account), callback_query.message)

@Client.on_callback_query(data_filter('set_reaction_emojis'))
async def set_reaction_emojis(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    current_emojis = config.get('reaction_emojis', [])
    emojis_list = ", ".join(current_emojis) if current_emojis else "Список пуст 📋"
    text = (f"<b>Текущие эмодзи:</b>\n<code>{emojis_list}</code>\n\n"
            "Введите новые эмодзи через запятую (например: ❤️,👍,🔥):")
    await send_msg(text, get_back_kb('Отмена ❌', 'story_reactions'), callback_query.message)
    fms.set_state(user_id, 'awaiting_reaction_emojis')

@Client.on_message(state_filter("awaiting_reaction_emojis"))
async def process_reaction_emojis(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    new_emojis = [x.strip() for x in message.text.split(',')]
    config = account.config or {}
    config["reaction_emojis"] = [emoji for emoji in new_emojis if emoji]
    db.Account.update_by_id(account_id, config=config)
    account = db.Account.get_by_id(account_id)
    fms.reset_state(user_id)
    await send_msg(reaction_text, get_story_reactions_kb(account), message)


def get_accounts_for_copy_kb(accounts):
    keyboard = []
    for account in accounts:
        keyboard.append([InlineKeyboardButton(account.username, callback_data=f"copy_reaction_settings_from_{account.id}")])
    keyboard.append([InlineKeyboardButton("Отмена ❌", callback_data="story_reactions")])
    return InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(data_filter('reaction_copy_settings'))
async def copy_settings(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    accounts = db.Account.get_by_owner(user_id)
    if not accounts:
        await callback_query.answer("⚠️ У вас нет других аккаунтов для копирования настроек", show_alert=True)
        return
    fms.set_state(user_id, 'awaiting_reaction_copy_username')
    await send_msg(
        'Выберите аккаунт, с которого нужно скопировать настройки:',
        get_accounts_for_copy_kb(accounts),
        callback_query.message
    )


@Client.on_callback_query(data_filter_startswith('copy_reaction_settings_from_'))
async def select_source_account(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    source_account_id = int(callback_query.data.split('_')[4])
    target_account_id = data.get('open_account')

    if source_account_id == target_account_id:
        await callback_query.answer("⚠️ Выберите другой аккаунт", show_alert=True)
        return

    source_account = db.Account.get_by_id(source_account_id)
    target_account = db.Account.get_by_id(target_account_id)

    if not source_account or not target_account:
        await callback_query.answer("⚠️ Один из аккаунтов не найден", show_alert=True)
        return

    # Копируем конфигурацию
    source_config = source_account.config or {}
    target_config = target_account.config or {}
    target_config.update({
        "is_reactions_enabled": source_config.get("is_reactions_enabled"),
        "reaction_emojis": source_config.get("reaction_emojis", [])
    })
    db.Account.update_by_id(target_account_id, config=target_config)

    fms.reset_state(user_id)
    await callback_query.answer("✅ Настройки успешно скопированы", show_alert=True)
    await send_msg(reaction_text, get_story_reactions_kb(target_account), callback_query.message)


@Client.on_message(state_filter("awaiting_reaction_copy_username"))
async def process_reaction_copy_username(client: Client, message: Message):
    user_id = message.from_user.id
    target_account_id = fms.get_data(user_id).get('open_account')
    username = message.text.strip()

    try:
        # Убираем символ @ если он есть
        username = username.replace('@', '').strip()

        # Ищем аккаунт по username
        source_account = db.Account.get_by_username(username)

        if not source_account:
            raise ValueError(f"Аккаунт с username '{username}' не найден.")

        if source_account.id == target_account_id:
            await send_msg("⚠️ Выберите другой аккаунт",
                           get_back_kb("Попробовать снова", "copy_reaction_settings_from_username"), message)
            return

        # Копируем настройки
        source_config = source_account.config or {}
        target_account = db.Account.get_by_id(target_account_id)
        target_config = target_account.config or {}

        target_config.update({
            "is_reactions_enabled": source_config.get("is_reactions_enabled"),
            "reaction_emojis": source_config.get("reaction_emojis", [])
        })

        db.Account.update_by_id(target_account_id, config=target_config)

        await send_msg("✅ Настройки успешно скопированы!", get_story_reactions_kb(target_account), message)

    except Exception as e:
        await send_msg(f"⚠️ Ошибка: {str(e)}", get_back_kb("Попробовать снова", "copy_reaction_settings_from_username"),
                       message)

    finally:
        fms.reset_state(user_id)

async def story_reactions_work(app: Client):
    cursor = app.storage.conn.cursor()
    account_id = app.me.id
    async def create_table():
        cursor.execute("""
                SELECT name 
                FROM sqlite_master 
                WHERE type='table' AND name='processed_stories';
            """)
        table_exists = cursor.fetchone()
        if not table_exists:
            cursor.execute("""
                    CREATE TABLE processed_stories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        story_id TEXT NOT NULL UNIQUE
                    );
                """)
            await app.storage.save()
    async def normalize_table():
        cursor.execute("SELECT story_id FROM processed_stories")
        rows = cursor.fetchall()
        for row in rows:
            story_id = row[0]
            if ":" not in str(story_id):
                cursor.execute("DELETE FROM processed_stories WHERE story_id = ?", (story_id,))
        await app.storage.save()
    def get_story_key(chat_id, story_id):
        return f"{chat_id}:{story_id}"
    async def is_story_processed(chat_id, story_id):
        story_key = get_story_key(chat_id, story_id)
        cursor.execute("SELECT story_id FROM processed_stories WHERE story_id = ?", (story_key,))
        return cursor.fetchone() is not None
    async def mark_story_as_processed(chat_id, story_id):
        story_key = get_story_key(chat_id, story_id)
        cursor.execute("INSERT OR IGNORE INTO processed_stories (story_id) VALUES (?)", (story_key,))
        await app.storage.save()
    await create_table()
    await normalize_table()
    while True:
        try:
            account = db.Account.get_by_id(account_id)
            if not account:
                print(f"[story_reactions/{account_id}] Аккаунт не найден в базе")
                await asyncio.sleep(60)
                continue
            config = account.config or {}
            if not config.get("is_reactions_enabled", False):
                print(f"[story_reactions/{account_id}] Реакции выключены")
                await asyncio.sleep(60)
                continue
            reaction_emojis = config.get("reaction_emojis", [])
            if not reaction_emojis:
                print(f"[story_reactions/{account_id}] Эмодзи не настроены")
                await asyncio.sleep(60)
                continue
            checked_dialogs = 0
            found_stories = 0
            liked_stories = 0
            print(f"[story_reactions/{account_id}] Старт обхода историй, emojis={reaction_emojis}")
            async for dialog in app.get_dialogs():
                if dialog.chat.type != ChatType.PRIVATE:
                    continue
                checked_dialogs += 1
                if checked_dialogs % 25 == 0:
                    print(f"[story_reactions/{account_id}] Проверено диалогов: {checked_dialogs}, найдено сторис: {found_stories}, лайков: {liked_stories}")
                async for story in app.get_chat_stories(dialog.chat.id):
                    found_stories += 1
                    if await is_story_processed(dialog.chat.id, story.id):
                        continue
                    emoji = random.choice(reaction_emojis)
                    try:
                        await app.send_reaction(
                            chat_id="<REDACTED>"
                            story_id=story.id,
                            emoji=emoji
                        )
                        chat_name = dialog.chat.username or dialog.chat.first_name or dialog.chat.title or dialog.chat.id
                        db.Analytics.create_record(
                            app.me.id,
                            'Лайкнул историю',
                            details=f"Кому: {chat_name}\nЭмодзи: {emoji}"
                        )
                        liked_stories += 1
                        print(f"[story_reactions/{account_id}] Лайкнул историю {story.id} в чате {dialog.chat.id} emoji={emoji}")
                        await mark_story_as_processed(dialog.chat.id, story.id)
                        await asyncio.sleep(10)
                    except Exception as e:
                        print(f"[story_reactions/{account_id}] Ошибка отправки реакции в чат {dialog.chat.id}, story={story.id}: {e} ❌")
                        await asyncio.sleep(5)
                await asyncio.sleep(2)
            print(f"[story_reactions/{account_id}] Обход завершен: диалогов={checked_dialogs}, сторис={found_stories}, лайков={liked_stories}")
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except RPCError as e:
            await asyncio.sleep(60)
        except (AuthKeyUnregistered, SessionRevoked, UserDeactivated) as e:
            await modules.accounts_storage.de_launch_account(app.me.id)
            return
        except Exception as e:
            print(f"Неожиданная ошибка: {e} ❗")
            await asyncio.sleep(60)
        await asyncio.sleep(300)
