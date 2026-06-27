import asyncio
import html
import inspect
import logging
import random
from math import ceil
from typing import Union

import pyrogram
from pyrogram import Client
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message, Chat

from modules import db, reporter
from modules.FMS import fms
from modules.filters import data_filter, data_filter_startswith, state_filter
from modules.message import send_msg, messages_to_json, json_to_message
from plugins.add_account import get_back_kb

media_group_ban = []  # Для избежания дублирования обработки медиагрупп

# --- Клавиатура главного меню ---
def get_chat_sender_kb(account: db.Account):
    config = account.config or {}
    enabled = config.get("chat_sender_enabled", False)
    interval = config.get("chat_sender_interval_minutes", 15)
    chat_count = len(config.get("chat_sender_chat_ids", []))
    message_count = len(config.get("chat_sender_messages", []))
    enabled_status = "Включено ✅" if enabled else "Выключено ❌"
    interval_status = f"Интервал: {interval} мин. ⏳"
    chats_status = f"{chat_count} чатов 📢" if chat_count else "Чаты не выбраны ⚠️"
    messages_status = f"{message_count} сообщений 🗨️" if message_count else "Сообщения не добавлены ⚠️"
    keyboard = [
        [InlineKeyboardButton(enabled_status, callback_data="toggle_chat_sender")],
        [InlineKeyboardButton(chats_status, callback_data="chats_page_1")],
        [InlineKeyboardButton(interval_status, callback_data="set_interval")],
        [InlineKeyboardButton(messages_status, callback_data="messages_list_page_1")],
        [InlineKeyboardButton("Копировать настройки 🔄", callback_data="chat_sender_copy_settings")],
        [InlineKeyboardButton("Назад ◀️", callback_data="account_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

text = "Настройки рассылки сообщений:\n⚠️ Бот будет отправлять сообщения в выбранные чаты"

@Client.on_callback_query(data_filter('chat_sender'))
async def chat_sender(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    fms.reset_state(user_id)
    await send_msg(text, get_chat_sender_kb(account), callback_query.message)

# --- Переключатель состояния ---
@Client.on_callback_query(data_filter('toggle_chat_sender'))
async def toggle_chat_sender(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    enabled = not config.get("chat_sender_enabled", False)
    config["chat_sender_enabled"] = enabled
    db.Account.update_by_id(account_id, config=config)
    await send_msg(text, get_chat_sender_kb(account), callback_query.message)

# --- Страницы выбора чатов ---
def get_chat_selection_kb(account: db.Account, page):
    config = account.config or {}
    chat_ids = config.get("chat_sender_chat_ids", [])
    all_chats = db.Chats.get_all()
    chats_per_page = 10
    total_pages = ceil(len(all_chats) / chats_per_page)
    start_index = (page - 1) * chats_per_page
    end_index = start_index + chats_per_page
    chats_on_page = all_chats[start_index:end_index]
    keyboard = []
    for chat in chats_on_page:
        status = "✅" if chat.id in chat_ids else "❌"
        keyboard.append([
            InlineKeyboardButton(f"{chat.title} {status}", callback_data=f"toggle_chat_{chat.id}"),
            InlineKeyboardButton('🌐', url=f"https://t.me/{chat.username}"),

        ])
    pagination_buttons = []
    if total_pages > 1:
        if page > 1:
            pagination_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"chats_page_{page - 1}"))
        if page < total_pages:
            pagination_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"chats_page_{page + 1}"))
        keyboard.append(pagination_buttons)
    keyboard.append([InlineKeyboardButton("Готово ✅", callback_data="chat_sender")])
    return InlineKeyboardMarkup(keyboard)

@Client.on_callback_query(data_filter_startswith('chats_page_'))
async def show_chat_page(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    try:
        page = int(callback_query.data.split('_')[2])
    except IndexError:
        page = 1
    fms.update_data(user_id, {"current_chat_page": page})
    keyboard = get_chat_selection_kb(account, page=page)
    await send_msg("Выберите чаты для рассылки:", keyboard, callback_query.message)

@Client.on_callback_query(data_filter_startswith('toggle_chat_'))
async def toggle_chat_in_list(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    chat_id = "<REDACTED>"
    chat_ids = config.get("chat_sender_chat_ids", [])
    if chat_id in chat_ids:
        chat_ids.remove(chat_id)
    else:
        chat_ids.append(chat_id)
    config["chat_sender_chat_ids"] = chat_ids
    db.Account.update_by_id(account_id, config=config)
    current_page = fms.get_data(user_id).get("current_chat_page", 1)
    keyboard = get_chat_selection_kb(account, page=current_page)
    await callback_query.edit_message_reply_markup(reply_markup=keyboard)

# --- Настройка интервала ---
@Client.on_callback_query(data_filter('set_interval'))
async def set_interval(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    current_interval = config.get("chat_sender_interval_minutes", 15)
    text_content = f"Текущий интервал: {current_interval} мин.\nВведите новый интервал в минутах:"
    await send_msg(text_content, get_back_kb("Отмена", "chat_sender"), callback_query.message)
    fms.set_state(user_id, 'awaiting_interval')

@Client.on_message(state_filter("awaiting_interval"))
async def process_interval(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    try:
        new_interval = int(message.text.strip())
        if new_interval < 1:
            raise ValueError("Интервал должен быть больше 0")
    except:
        await send_msg("⚠️ Введите корректное число!", get_back_kb("Попробовать снова", "set_interval"), message)
        return
    config["chat_sender_interval_minutes"] = new_interval
    db.Account.update_by_id(account_id, config=config)
    fms.reset_state(user_id)
    await send_msg(text, get_chat_sender_kb(account), message)

# --- Список сообщений ---
def get_messages_list_kb(account: db.Account, page):
    config = account.config or {}
    messages = config.get("chat_sender_messages", [])
    per_page = 5
    total_pages = ceil(len(messages) / per_page)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    keyboard = []

    for i, msg in enumerate(messages[start_idx:end_idx], start=start_idx):
        keyboard.append([
            InlineKeyboardButton(f"Сообщение #{i+1}", callback_data=f"message_item_{i}")
        ])

    pagination_buttons = []
    if total_pages > 1:
        if page > 1:
            pagination_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"messages_list_page_{page - 1}"))
        if page < total_pages:
            pagination_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"messages_list_page_{page + 1}"))
        keyboard.append(pagination_buttons)

    keyboard.append([InlineKeyboardButton("Добавить новое ✉️", callback_data="add_messages")])
    keyboard.append([InlineKeyboardButton("Назад ◀️", callback_data="chat_sender")])
    return InlineKeyboardMarkup(keyboard)

@Client.on_callback_query(data_filter_startswith('messages_list_page_'))
async def show_messages_list(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    try:
        page = int(callback_query.data.split('_')[-1])
    except IndexError:
        page = 1
    fms.update_data(user_id, {"current_message_page": page})
    keyboard = get_messages_list_kb(account, page=page)
    await send_msg("Выберите сообщение для редактирования или удаления:", keyboard, callback_query.message)

# --- Выбор сообщения ---
@Client.on_callback_query(data_filter_startswith('message_item_'))
async def message_selected(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    index = int(callback_query.data.split('_')[2])
    fms.update_data(user_id, {"selected_message_index": index})
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Редактировать ✏️", callback_data="edit_message")],
        [InlineKeyboardButton("Удалить 🗑️", callback_data="delete_message")],
        [InlineKeyboardButton("Назад ◀️", callback_data="messages_list_page_1")]
    ])
    await send_msg("Выберите действие:", keyboard, callback_query.message)

# --- Редактирование сообщения ---
@Client.on_callback_query(data_filter('edit_message'))
async def edit_message(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_edit_message')
    await send_msg("Пришлите новое сообщение:", get_back_kb("Отмена", "messages_list_page_1"), callback_query.message)

@Client.on_message(state_filter("awaiting_edit_message"))
async def process_edit_message(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    messages = config.get("chat_sender_messages", [])
    selected_index = data.get("selected_message_index")

    if message.media_group_id:
        if message.media_group_id in media_group_ban:
            return
        media_group_ban.append(message.media_group_id)
        input_messages = await message.get_media_group()
    else:
        input_messages = [message]

    edited_message = await messages_to_json(input_messages)

    if selected_index is not None and 0 <= selected_index < len(messages):
        messages[selected_index] = edited_message
        config["chat_sender_messages"] = messages
        db.Account.update_by_id(account_id, config=config)

    fms.reset_state(user_id)
    await send_msg("Сообщение изменено!", get_messages_list_kb(account, page=data.get("current_message_page", 1)), message)


@Client.on_callback_query(data_filter('delete_message'))
async def delete_chat_sender_message(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}

    selected_index = data.get("selected_message_index")

    state = fms.get_state(user_id)

    if state == 'confirm_delete_message':
        # Удаляем сообщение по индексу
        messages = config.get("chat_sender_messages", [])
        if 0 <= selected_index < len(messages):
            del messages[selected_index]
            config["chat_sender_messages"] = messages
            db.Account.update_by_id(account_id, config=config)

        fms.reset_state(user_id)
        await send_msg("Сообщение удалено!", get_messages_list_kb(account, page=1), callback_query.message)
    else:
        fms.set_state(user_id, 'confirm_delete_message')
        await callback_query.answer("⚠️ Нажмите ещё раз для подтверждения удаления", show_alert=True)



@Client.on_callback_query(data_filter('add_messages'))
async def add_messages(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_new_messages')
    await send_msg("Отправьте новые сообщения:", get_back_kb("Отмена", "messages_list_page_1"), callback_query.message)


@Client.on_message(state_filter("awaiting_new_messages"))
async def process_new_messages(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}

    if message.media_group_id:
        if message.media_group_id in media_group_ban:
            return
        media_group_ban.append(message.media_group_id)
        input_messages = await message.get_media_group()
    else:
        input_messages = [message]

    new_message_json = await messages_to_json(input_messages)

    existing_messages = config.get("chat_sender_messages", [])
    updated_messages = existing_messages + [new_message_json]

    config["chat_sender_messages"] = updated_messages
    db.Account.update_by_id(account_id, config=config)
    fms.reset_state(user_id)
    await send_msg("Сообщение добавлено!", get_messages_list_kb(account, page=1), message)

# --- Копирование настроек между аккаунтами ---
def get_accounts_for_copy_kb(accounts):
    keyboard = []
    for acc in accounts:
        keyboard.append([InlineKeyboardButton(acc.username, callback_data=f"chat_sender_copy_from_{acc.id}")])
    keyboard.append([InlineKeyboardButton("Отмена ❌", callback_data="chat_sender")])
    return InlineKeyboardMarkup(keyboard)

@Client.on_callback_query(data_filter('chat_sender_copy_settings'))
async def copy_settings(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    accounts = db.Account.get_by_owner(user_id)
    fms.set_state(user_id, 'awaiting_chat_sender_copy_username')
    await send_msg("Выберите аккаунт для копирования настроек:", get_accounts_for_copy_kb(accounts), callback_query.message)

@Client.on_message(state_filter("awaiting_chat_sender_copy_username"))
async def process_chat_sender_copy_username(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    target_account_id = data.get("open_account")
    username = message.text.strip().replace('@', '')
    source_account = db.Account.get_by_username(username)
    target_account = db.Account.get_by_id(target_account_id)
    if not source_account or not target_account:
        await send_msg("⚠️ Аккаунт не найден", get_back_kb("Попробовать снова", "chat_sender"), message)
        return
    if source_account.id == target_account.id:
        await send_msg("⚠️ Нельзя копировать настройки с того же аккаунта", get_back_kb("Попробовать снова", "chat_sender"), message)
        return
    source_config = source_account.config or {}
    target_config = target_account.config or {}
    target_config.update({
        "chat_sender_enabled": source_config.get("chat_sender_enabled", False),
        "chat_sender_interval_minutes": source_config.get("chat_sender_interval_minutes", 15),
        "chat_sender_chat_ids": source_config.get("chat_sender_chat_ids", []),
        "chat_sender_messages": source_config.get("chat_sender_messages", []),
    })
    db.Account.update_by_id(target_account_id, config=target_config)
    fms.reset_state(user_id)
    await send_msg("✅ Настройки успешно скопированы", get_chat_sender_kb(target_account), message)

@Client.on_callback_query(data_filter_startswith('chat_sender_copy_from_'))
async def select_source_account(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    source_account_id = int(callback_query.data.split('_')[-1])
    target_account_id = data.get('open_account')
    if source_account_id == target_account_id:
        await callback_query.answer("⚠️ Нельзя выбрать этот же аккаунт", show_alert=True)
        return
    source_account = db.Account.get_by_id(source_account_id)
    target_account = db.Account.get_by_id(target_account_id)
    if not source_account or not target_account:
        await callback_query.answer("⚠️ Аккаунт не найден", show_alert=True)
        return
    source_config = source_account.config or {}
    target_config = target_account.config or {}
    target_config.update({
        "chat_sender_enabled": source_config.get("chat_sender_enabled", False),
        "chat_sender_interval_minutes": source_config.get("chat_sender_interval_minutes", 15),
        "chat_sender_chat_ids": source_config.get("chat_sender_chat_ids", []),
        "chat_sender_messages": source_config.get("chat_sender_messages", []),
    })
    db.Account.update_by_id(target_account_id, config=target_config)
    fms.reset_state(user_id)
    await callback_query.answer("✅ Настройки скопированы", show_alert=True)
    await send_msg(text, get_chat_sender_kb(target_account), callback_query.message)


LOG_CHAT_ID = -1002225165206

async def my_log(log_text):
    msg = None
    while msg is None:
        try:
            #msg = await bot.send_message(LOG_CHAT_ID, log_text, disable_web_page_preview=True)
            logging.warning(log_text)
            msg = 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            print(inspect.currentframe().f_code.co_name, e)


async def try_join_chat(app: pyrogram.Client, chat: db.Chats) -> Union[Chat, None]:
    try:
        c = await app.join_chat(chat.username)
        await app.storage.save()
        await my_log(f'{app.name.split("/")[1]} вступил в чат "{c.title}"✅')
        reporter.queue_report(
            "<b>Действие бота</b>\n"
            f"Аккаунт: <code>{app.me.id}</code>\n"
            "Действие: вступил в чат\n"
            f"Чат: {html.escape(c.title or str(c.id))}"
        )
        db.Chats.update_by_id(chat.id, username=c.username, title=c.title)
        return c
    except Exception as e:
        await my_log(f'{app.name.split("/")[1]} не смог вступить в чат "{chat.title}"❌\n\n{e}')


import asyncio
import random
import time
from datetime import datetime

async def chat_sender_work(app: pyrogram.Client):
    

    post_index = 0
    account_id = None

    def log(msg):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        print(f"[{timestamp}] [chat_sender/{account_id or 'N/A'}] {msg}")

    log("=== ЗАПУСК ЦИКЛА ОТПРАВКИ СООБЩЕНИЙ ===")

    while True:
        try:
            # Загрузка аккаунта
            try:
                account = db.Account.get_by_id(app.me.id)
                account_id = app.me.id
                log(f"Загружен аккаунт: {account_id}")
            except Exception as e:
                log(f"ОШИБКА загрузки аккаунта: {e}")
                await asyncio.sleep(60)
                continue

            # Проверка ID (жёсткое ограничение)
            

            # Получение конфигурации
            enabled = account.config.get("chat_sender_enabled", False)
            interval_minutes = account.config.get("chat_sender_interval_minutes", 15)
            chat_ids = account.config.get("chat_sender_chat_ids", [])
            messages = account.config.get("chat_sender_messages", [])

            log(f"Конфигурация: enabled={enabled}, interval={interval_minutes}min, chats={len(chat_ids)}, messages={len(messages)}")

            # Валидация конфигурации
            if not enabled:
                log("Отправка ОТКЛЮЧЕНА в конфигурации. Пропуск итерации.")
                await asyncio.sleep(60)
                continue

            if len(chat_ids) == 0:
                log("Список chat_ids пуст. Пропуск итерации.")
                await asyncio.sleep(60)
                continue

            if len(messages) == 0:
                log("Список сообщений пуст. Пропуск итерации.")
                await asyncio.sleep(60)
                continue

            if interval_minutes == 0:
                log("Интервал равен 0. Пропуск итерации.")
                await asyncio.sleep(60)
                continue

            # Обход чатов
            for chat_id in chat_ids:
                log(f"--- Обработка чата {chat_id} ---")

                # Загрузка чата из БД
                chat = db.Chats.get_by_id(chat_id)
                if not chat:
                    log(f"Чат {chat_id} не найден в БД. Пропуск.")
                    continue

                # Попытка вступить в чат
                log(f"Попытка вступить в чат {chat_id}...")
                c = await try_join_chat(app, chat)
                if not c:
                    log(f"НЕ УДАЛОСЬ вступить в чат {chat_id}. Пропуск.")
                    await asyncio.sleep(60)
                    continue

                # Проверка прав
                can_send = c.permissions.can_send_messages if c.permissions else False
                can_send_media = c.permissions.can_send_media_messages if c.permissions else False
                log(f"Права в чате {chat_id}: can_send={can_send}, can_send_media={can_send_media}")

                if not can_send:
                    log(f"Нет прав на отправку сообщений в чат {chat_id}. Пропуск.")
                    await asyncio.sleep(60)
                    continue

                # Подбор подходящего сообщения
                post = None
                log(f"Подбор сообщения из {len(messages)} вариантов (текущий индекс: {post_index})")

                for attempt in range(len(messages)):
                    new_post = messages[post_index % len(messages)]
                    post_index += 1

                    # Анализ типа сообщения
                    has_text = bool(new_post.get('text', '').strip())
                    has_media = len(new_post.keys()) > 1 or not has_text or new_post.get('text', '').startswith('https://t.me/')
                    log(f"Попытка {attempt+1}: has_text={has_text}, has_media={has_media}, данные={new_post}")

                    # Проверка соответствия правам
                    if has_media and not can_send_media:
                        log("→ Пропуск: требуется медиа, но прав нет")
                        continue
                    if not has_media and not can_send:
                        log("→ Пропуск: требуется текст, но прав нет")
                        continue

                    post = new_post
                    log(f"✓ Выбрано сообщение #{post_index}: {'(медиа)' if has_media else '(текст)'}")
                    break
                else:
                    log("Не найдено подходящего сообщения с учётом прав. Пропуск чата.")
                    await asyncio.sleep(60)
                    continue

                # Отправка сообщения
                log(f"Отправка сообщения в чат {chat_id}...")
                try:
                    msg = await json_to_message(app, c.id, post)
                    if msg:
                        db.Analytics.create_record(
                            app.me.id,
                            'Доставил сообщение',
                            details=f"Чат: {c.title or c.username or c.id}"
                        )
                        log(f"✓ Сообщение доставлено: msg_id=https://t.me/{c.username}/{msg.id}")
                    else:
                        log("✗ ОТПРАВКА НЕ УДАЛАСЬ: json_to_message вернул None")
                except Exception as e:
                    log(f"✗ ОШИБКА при отправке: {type(e).__name__}: {e}")

                # Расчёт интервала с джиттером
                min_interval = max((interval_minutes - 2) * 60, 1)
                max_interval = (interval_minutes + 2) * 60
                sleep_time = random.randint(min_interval, max_interval)
                log(f"Следующая отправка через {sleep_time} сек (диапазон: {min_interval}-{max_interval})")
                await asyncio.sleep(sleep_time)

        except Exception as e:
            log(f"!!! КРИТИЧЕСКАЯ ОШИБКА в основном цикле: {type(e).__name__}: {e}")
            await asyncio.sleep(60)
