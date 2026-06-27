import asyncio
from datetime import datetime, timedelta

from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError, AuthKeyUnregistered, SessionRevoked, UserDeactivated
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from modules import db
from modules.filters import *
from modules.message import send_msg
from plugins.add_account import get_back_kb

import modules

STORY_CLONER_CONFIG_KEYS = (
    "is_copying_enabled",
    "copy_from_accounts",
    "is_copy_prohibited",
    "delete_if_original_deleted",
    "publish_duration",
    "skip_stories_with_at",
    "copy_to_channel_enabled",
    "copy_channel_id",
)


def split_list(text):
    return [x.strip().lstrip('@') for x in text.replace('\n', ',').split(',') if x.strip()]


def normalize_channel_id(text):
    value = text.strip()
    if not value or value in ("-", "нет", "off", "выкл"):
        return ""
    if value.startswith("https://t.me/"):
        value = value.rstrip("/").split("/")[-1]
    if value.startswith("@"):
        return value
    if value.lstrip("-").isdigit():
        return int(value)
    return f"@{value}"


def channel_label(channel_id):
    return str(channel_id) if channel_id else "Не указан"


def copy_story_cloner_config(source_config):
    return {key: source_config.get(key) for key in STORY_CLONER_CONFIG_KEYS}


async def send_story_to_channel(app, channel_id, story, media, caption, publish_period, protect_content):
    if not channel_id:
        return None

    try:
        return await app.send_story(
            channel_id,
            media=media,
            caption=caption,
            period=publish_period,
            pinned=False,
            protect_content=protect_content
        )
    except Exception as story_error:
        print(f"[story_cloner/{app.me.id}] Не удалось отправить историю в канал {channel_id}: {story_error}. Пробую постом.")

    if story.photo:
        return await app.send_photo(channel_id, media, caption=caption, protect_content=protect_content)
    if story.video:
        return await app.send_video(channel_id, media, caption=caption, protect_content=protect_content)
    return None

def get_story_cloner_kb(account: db.Account):
    config = account.config or {}
    is_copying_enabled = config.get("is_copying_enabled", False)
    is_copy_prohibited = config.get("is_copy_prohibited", False)
    delete_if_original_deleted = config.get("delete_if_original_deleted", False)
    publish_duration = config.get("publish_duration", 24)  # 24 или 48 часов
    skip_stories_with_at = config.get("skip_stories_with_at", False)
    copy_to_channel_enabled = config.get("copy_to_channel_enabled", False)
    copy_channel_id = config.get("copy_channel_id", "")
    copying_status = "Включено ✅" if is_copying_enabled else "Выключено ❌"
    prohibition_status = "Запрет на копирование ✅" if is_copy_prohibited else "Запрет на копирование ❌"
    delete_status = "Удалять если удалил оригинал ✅" if delete_if_original_deleted else "Удалять если удалил оригинал ❌"
    publish_duration_status = f"{publish_duration} часа ⏰"
    skip_at_status = "Пропускать истории с @ ✅" if skip_stories_with_at else "Пропускать истории с @ ❌"
    channel_status = "Репост в канал ✅" if copy_to_channel_enabled else "Репост в канал ❌"
    keyboard = [
        [InlineKeyboardButton(f"{copying_status}", callback_data="toggle_copying")],
        [InlineKeyboardButton("Настроить источники ⚙️", callback_data="set_copy_sources")],
        [InlineKeyboardButton(f"Канал: {channel_label(copy_channel_id)}", callback_data="set_copy_channel")],
        [InlineKeyboardButton(f"{channel_status}", callback_data="toggle_copy_to_channel")],
        [InlineKeyboardButton(f"{prohibition_status}", callback_data="toggle_prohibition")],
        [InlineKeyboardButton(f"{delete_status}", callback_data="toggle_delete_original")],
        [InlineKeyboardButton(publish_duration_status, callback_data="set_publish_duration")],
        [InlineKeyboardButton(f"{skip_at_status}", callback_data="toggle_skip_at")],
        [InlineKeyboardButton("Копировать настройки 🔄", callback_data="story_cloner_copy_settings")],
        [InlineKeyboardButton("Назад ◀️", callback_data="account_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


cloner_text = "Настройки копирования историй:\n\n⚠️ Будут копироваться новые истории с указанных аккаунтов"

@Client.on_callback_query(data_filter('story_cloner'))
async def story_cloner(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    fms.reset_state(user_id)
    await send_msg(cloner_text, get_story_cloner_kb(account), callback_query.message)


@Client.on_callback_query(data_filter('toggle_copying'))
async def toggle_copying(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)

    # Переключаем состояние копирования
    config = account.config or {}
    is_copying_enabled = not config.get("is_copying_enabled", False)
    config["is_copying_enabled"] = is_copying_enabled
    db.Account.update_by_id(account_id, config=config)
    await send_msg(cloner_text, get_story_cloner_kb(account), callback_query.message)


@Client.on_callback_query(data_filter('set_copy_sources'))
async def set_copy_sources(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    copy_from_accounts = config.get('copy_from_accounts', [])
    accounts_list = ", ".join(copy_from_accounts) if copy_from_accounts else "Список пуст"
    text = f"<b>Актуальный список:</b>\n<code>{accounts_list}</code>\n\nВведите новый список аккаунтов через запятую (например: user1, user2, user3):"
    await send_msg(text, get_back_kb('Отмена', 'story_cloner'), callback_query.message)
    fms.set_state(user_id, 'awaiting_copy_sources')


@Client.on_message(state_filter("awaiting_copy_sources"))
async def process_copy_sources(client: Client, message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)

    copy_from_accounts = split_list(message.text)
    config = account.config or {}
    config["copy_from_accounts"] = copy_from_accounts
    db.Account.update_by_id(account_id, config=config)

    # Сбрасываем состояние и возвращаемся к меню настроек
    fms.reset_state(user_id)
    await send_msg(cloner_text, get_story_cloner_kb(account), message)


@Client.on_callback_query(data_filter('set_copy_channel'))
async def set_copy_channel(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    current_channel = channel_label(config.get("copy_channel_id", ""))
    text = (
        f"<b>Текущий канал:</b> <code>{current_channel}</code>\n\n"
        "Введите id канала вида <code>-100...</code> или username канала.\n"
        "Чтобы убрать канал, отправьте <code>-</code>."
    )
    await send_msg(text, get_back_kb('Отмена', 'story_cloner'), callback_query.message)
    fms.set_state(user_id, 'awaiting_copy_channel')


@Client.on_message(state_filter("awaiting_copy_channel"))
async def process_copy_channel(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    channel_id = normalize_channel_id(message.text)
    config["copy_channel_id"] = channel_id
    config["copy_to_channel_enabled"] = bool(channel_id)
    db.Account.update_by_id(account_id, config=config)
    fms.reset_state(user_id)
    account = db.Account.get_by_id(account_id)
    await send_msg(cloner_text, get_story_cloner_kb(account), message)


@Client.on_callback_query(data_filter('toggle_copy_to_channel'))
async def toggle_copy_to_channel(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}

    if not config.get("copy_channel_id"):
        await callback_query.answer("Сначала укажите канал", show_alert=True)
        return

    config["copy_to_channel_enabled"] = not config.get("copy_to_channel_enabled", False)
    db.Account.update_by_id(account_id, config=config)
    account = db.Account.get_by_id(account_id)
    await send_msg(cloner_text, get_story_cloner_kb(account), callback_query.message)


@Client.on_callback_query(data_filter('toggle_prohibition'))
async def toggle_prohibition(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)

    # Переключаем запрет на копирование
    config = account.config or {}
    is_copy_prohibited = not config.get("is_copy_prohibited", False)
    config["is_copy_prohibited"] = is_copy_prohibited
    db.Account.update_by_id(account_id, config=config)

    await send_msg(cloner_text, get_story_cloner_kb(account), callback_query.message)


@Client.on_callback_query(data_filter('toggle_delete_original'))
async def toggle_delete_original(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)

    # Переключаем состояние удаления, если оригинал удален
    config = account.config or {}
    delete_if_original_deleted = not config.get("delete_if_original_deleted", False)
    config["delete_if_original_deleted"] = delete_if_original_deleted
    db.Account.update_by_id(account_id, config=config)

    await send_msg(cloner_text, get_story_cloner_kb(account), callback_query.message)


@Client.on_callback_query(data_filter('set_publish_duration'))
async def set_publish_duration(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)

    # Определяем последовательность значений
    durations = [6, 12, 24, 48]
    
    # Получаем текущее значение или используем 24 по умолчанию
    config = account.config or {}
    current_duration = config.get("publish_duration", 24)
    
    # Находим индекс текущего значения и вычисляем следующее по кругу
    try:
        current_index = durations.index(current_duration)
    except ValueError:
        current_index = 2  # индекс для 24 (значение по умолчанию)
    
    new_duration = durations[(current_index + 1) % len(durations)]
    
    # Сохраняем новое значение
    config["publish_duration"] = new_duration
    db.Account.update_by_id(account_id, config=config)
    
    # Обновляем интерфейс с новой клавиатурой (кнопка будет отображать новое значение)
    await send_msg(cloner_text, get_story_cloner_kb(account), callback_query.message)
    
    # Подтверждаем нажатие без уведомления
    


@Client.on_callback_query(data_filter('toggle_skip_at'))
async def toggle_skip_at(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)

    # Переключаем пропуск историй с "@"
    config = account.config or {}
    skip_stories_with_at = not config.get("skip_stories_with_at", False)
    config["skip_stories_with_at"] = skip_stories_with_at
    db.Account.update_by_id(account_id, config=config)

    await send_msg(cloner_text, get_story_cloner_kb(account), callback_query.message)

def get_accounts_for_copy_kb(accounts):
    keyboard = []
    for account in accounts:
        keyboard.append([InlineKeyboardButton(account.username, callback_data=f"story_cloner_copy_from_{account.id}")])
    keyboard.append([InlineKeyboardButton("Отмена ❌", callback_data="story_cloner")])
    return InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(data_filter('story_cloner_copy_settings'))
async def copy_settings(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    accounts = db.Account.get_by_owner(user_id)
    if not accounts:
        await callback_query.answer("⚠️ У вас нет других аккаунтов для копирования настроек", show_alert=True)
        return

    fms.set_state(user_id, 'awaiting_copy_username')

    await send_msg(
        'Выберите аккаунт, с которого нужно скопировать настройки:',
        get_accounts_for_copy_kb(accounts),
        callback_query.message
    )


@Client.on_message(state_filter("awaiting_copy_username"))
async def process_copy_username(client: Client, message: Message):
    user_id = message.from_user.id
    target_account_id = fms.get_data(user_id).get('open_account')

    username = message.text.strip()
    username.replace('@', '')

    try:
        # Ищем аккаунт в базе данных
        source_account = db.Account.get_by_username(username)
        if not source_account:
            raise ValueError("Аккаунт не найден в вашей базе")

        if source_account.id == target_account_id:
            await send_msg("⚠️ Выберите другой аккаунт", get_back_kb('Попробовать снова', 'story_cloner_copy_settings'), message)
            return

        # Копируем конфигурацию
        source_config = source_account.config or {}

        target_account = db.Account.get_by_id(target_account_id)
        target_config = target_account.config or {}
        target_config.update(copy_story_cloner_config(source_config))

        db.Account.update_by_id(target_account_id, config=target_config)

        await send_msg("✅ Настройки успешно скопированы", get_story_cloner_kb(target_account), message)
    except Exception as e:
        await send_msg(f"⚠️ Ошибка: {str(e)}", get_back_kb('Попробовать снова', 'story_cloner_copy_settings'), message)
    finally:
        fms.reset_state(user_id)


@Client.on_callback_query(data_filter_startswith('story_cloner_copy_from_'))
async def select_source_account(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    source_account_id = int(callback_query.data.split('_')[-1])
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
    target_config.update(copy_story_cloner_config(source_config))

    db.Account.update_by_id(target_account_id, config=target_config)

    fms.reset_state(user_id)
    await callback_query.answer("✅ Настройки успешно скопированы", show_alert=True)
    await send_msg(cloner_text, get_story_cloner_kb(target_account), callback_query.message)


def get_bulk_story_cloner_kb(data):
    copy_from_accounts = data.get("bulk_copy_from_accounts", [])
    target_account_ids = data.get("bulk_target_account_ids", [])
    copy_to_channel_enabled = data.get("bulk_copy_to_channel_enabled", False)
    copy_channel_id = data.get("bulk_copy_channel_id", "")
    is_copy_prohibited = data.get("bulk_is_copy_prohibited", False)
    delete_if_original_deleted = data.get("bulk_delete_if_original_deleted", False)
    publish_duration = data.get("bulk_publish_duration", 24)
    skip_stories_with_at = data.get("bulk_skip_stories_with_at", False)
    is_copying_enabled = data.get("bulk_is_copying_enabled", True)

    keyboard = [
        [InlineKeyboardButton("Включить ✅" if is_copying_enabled else "Выключить ❌", callback_data="bulk_toggle_copying")],
        [InlineKeyboardButton(f"Источники: {len(copy_from_accounts)}", callback_data="bulk_set_copy_sources")],
        [InlineKeyboardButton(f"Аккаунты: {len(target_account_ids)}", callback_data="bulk_select_accounts")],
        [InlineKeyboardButton(f"Канал: {channel_label(copy_channel_id)}", callback_data="bulk_set_copy_channel")],
        [InlineKeyboardButton("Репост в канал ✅" if copy_to_channel_enabled else "Репост в канал ❌", callback_data="bulk_toggle_copy_to_channel")],
        [InlineKeyboardButton("Запрет на копирование ✅" if is_copy_prohibited else "Запрет на копирование ❌", callback_data="bulk_toggle_prohibition")],
        [InlineKeyboardButton("Удалять если удалил оригинал ✅" if delete_if_original_deleted else "Удалять если удалил оригинал ❌", callback_data="bulk_toggle_delete_original")],
        [InlineKeyboardButton(f"{publish_duration} часа ⏰", callback_data="bulk_set_publish_duration")],
        [InlineKeyboardButton("Пропускать истории с @ ✅" if skip_stories_with_at else "Пропускать истории с @ ❌", callback_data="bulk_toggle_skip_at")],
        [InlineKeyboardButton("Применить ко всем выбранным ✅", callback_data="bulk_apply_story_cloner")],
        [InlineKeyboardButton("Назад ◀️", callback_data="accounts_")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_bulk_accounts_kb(user_id, page=1, accounts_per_page=8):
    accounts = db.Account.get_by_owner(user_id)
    data = fms.get_data(user_id)
    selected_ids = set(data.get("bulk_target_account_ids", []))
    total_pages = max(1, (len(accounts) + accounts_per_page - 1) // accounts_per_page)
    page = max(1, min(page, total_pages))
    start_index = (page - 1) * accounts_per_page
    accounts_on_page = accounts[start_index:start_index + accounts_per_page]

    keyboard = []
    for account in accounts_on_page:
        title = account.username or account.name or str(account.id)
        status = "🟢" if account.is_started else "⚪"
        selected = "✅" if account.id in selected_ids else "⬜"
        keyboard.append([
            InlineKeyboardButton(
                f"{selected} {status} {title}",
                callback_data=f"bulk_account_toggle_{account.id}"
            )
        ])

    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"bulk_accounts_page_{page - 1}"))
    pagination_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="bulk_accounts_noop"))
    if page < total_pages:
        pagination_buttons.append(InlineKeyboardButton("➡️", callback_data=f"bulk_accounts_page_{page + 1}"))
    keyboard.append(pagination_buttons)

    keyboard.append([
        InlineKeyboardButton("Все", callback_data="bulk_accounts_all"),
        InlineKeyboardButton("Активные", callback_data="bulk_accounts_active"),
        InlineKeyboardButton("Очистить", callback_data="bulk_accounts_clear"),
    ])
    keyboard.append([InlineKeyboardButton("Готово ✅", callback_data="bulk_settings")])
    return InlineKeyboardMarkup(keyboard)


def bulk_accounts_text(user_id):
    data = fms.get_data(user_id)
    selected_count = len(data.get("bulk_target_account_ids", []))
    return (
        "Выберите аккаунты для массовой настройки:\n\n"
        f"Выбрано: <b>{selected_count}</b>\n"
        "🟢 - аккаунт включен, ⚪ - аккаунт выключен"
    )


def bulk_text(data):
    return (
        "Массовая настройка копирования историй:\n\n"
        f"Источники: <code>{', '.join(data.get('bulk_copy_from_accounts', [])) or 'не указаны'}</code>\n"
        f"Аккаунтов выбрано: <b>{len(data.get('bulk_target_account_ids', []))}</b>\n"
        f"Канал: <code>{channel_label(data.get('bulk_copy_channel_id', ''))}</code>"
    )


def init_bulk_story_data(user_id):
    data = fms.get_data(user_id)
    defaults = {
        "bulk_copy_from_accounts": data.get("bulk_copy_from_accounts", []),
        "bulk_target_account_ids": data.get("bulk_target_account_ids", []),
        "bulk_copy_channel_id": data.get("bulk_copy_channel_id", ""),
        "bulk_copy_to_channel_enabled": data.get("bulk_copy_to_channel_enabled", False),
        "bulk_is_copying_enabled": data.get("bulk_is_copying_enabled", True),
        "bulk_is_copy_prohibited": data.get("bulk_is_copy_prohibited", False),
        "bulk_delete_if_original_deleted": data.get("bulk_delete_if_original_deleted", False),
        "bulk_publish_duration": data.get("bulk_publish_duration", 24),
        "bulk_skip_stories_with_at": data.get("bulk_skip_stories_with_at", False),
    }
    fms.update_data(user_id, defaults)
    return fms.get_data(user_id)


@Client.on_callback_query(data_filter('bulk_settings'))
async def bulk_settings(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.reset_state(user_id)
    data = init_bulk_story_data(user_id)
    await send_msg(bulk_text(data), get_bulk_story_cloner_kb(data), callback_query.message)


@Client.on_callback_query(data_filter('bulk_set_copy_sources'))
async def bulk_set_copy_sources(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_bulk_copy_sources')
    await send_msg(
        "Введите источники через запятую или с новой строки.\nНапример: <code>user1, user2, user3</code>",
        get_back_kb('Отмена', 'bulk_settings'),
        callback_query.message
    )


@Client.on_message(state_filter("awaiting_bulk_copy_sources"))
async def process_bulk_copy_sources(client: Client, message: Message):
    user_id = message.from_user.id
    fms.update_data(user_id, {"bulk_copy_from_accounts": split_list(message.text)})
    fms.reset_state(user_id)
    data = fms.get_data(user_id)
    await send_msg(bulk_text(data), get_bulk_story_cloner_kb(data), message)


@Client.on_callback_query(data_filter('bulk_set_copy_channel'))
async def bulk_set_copy_channel(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_bulk_copy_channel')
    await send_msg(
        "Введите канал для репоста: id <code>-100...</code> или username.\nЧтобы убрать канал, отправьте <code>-</code>.",
        get_back_kb('Отмена', 'bulk_settings'),
        callback_query.message
    )


@Client.on_message(state_filter("awaiting_bulk_copy_channel"))
async def process_bulk_copy_channel(client: Client, message: Message):
    user_id = message.from_user.id
    channel_id = normalize_channel_id(message.text)
    fms.update_data(user_id, {
        "bulk_copy_channel_id": channel_id,
        "bulk_copy_to_channel_enabled": bool(channel_id)
    })
    fms.reset_state(user_id)
    data = fms.get_data(user_id)
    await send_msg(bulk_text(data), get_bulk_story_cloner_kb(data), message)


@Client.on_callback_query(data_filter('bulk_select_accounts'))
async def bulk_select_accounts(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.reset_state(user_id)
    fms.update_data(user_id, {"bulk_accounts_page": 1})
    await send_msg(
        bulk_accounts_text(user_id),
        get_bulk_accounts_kb(user_id, 1),
        callback_query.message
    )


@Client.on_callback_query(data_filter('bulk_accounts_noop'))
async def bulk_accounts_noop(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()


@Client.on_callback_query(data_filter_startswith('bulk_accounts_page_'))
async def bulk_accounts_page(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    page = int(callback_query.data.split('_')[-1])
    fms.update_data(user_id, {"bulk_accounts_page": page})
    await send_msg(
        bulk_accounts_text(user_id),
        get_bulk_accounts_kb(user_id, page),
        callback_query.message
    )


@Client.on_callback_query(data_filter_startswith('bulk_account_toggle_'))
async def bulk_account_toggle(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    account_id = int(callback_query.data.split('_')[-1])
    accounts = db.Account.get_by_owner(user_id)
    allowed_ids = {account.id for account in accounts}
    if account_id not in allowed_ids:
        await callback_query.answer("Аккаунт не найден", show_alert=True)
        return

    data = fms.get_data(user_id)
    selected_ids = set(data.get("bulk_target_account_ids", []))
    if account_id in selected_ids:
        selected_ids.remove(account_id)
    else:
        selected_ids.add(account_id)

    page = data.get("bulk_accounts_page", 1)
    fms.update_data(user_id, {"bulk_target_account_ids": list(selected_ids)})
    await send_msg(
        bulk_accounts_text(user_id),
        get_bulk_accounts_kb(user_id, page),
        callback_query.message
    )


@Client.on_callback_query(data_filter('bulk_accounts_all'))
async def bulk_accounts_all(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    accounts = db.Account.get_by_owner(user_id)
    data = fms.get_data(user_id)
    page = data.get("bulk_accounts_page", 1)
    fms.update_data(user_id, {"bulk_target_account_ids": [account.id for account in accounts]})
    await send_msg(
        bulk_accounts_text(user_id),
        get_bulk_accounts_kb(user_id, page),
        callback_query.message
    )


@Client.on_callback_query(data_filter('bulk_accounts_active'))
async def bulk_accounts_active(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    accounts = db.Account.get_by_owner(user_id)
    data = fms.get_data(user_id)
    page = data.get("bulk_accounts_page", 1)
    fms.update_data(user_id, {"bulk_target_account_ids": [account.id for account in accounts if account.is_started]})
    await send_msg(
        bulk_accounts_text(user_id),
        get_bulk_accounts_kb(user_id, page),
        callback_query.message
    )


@Client.on_callback_query(data_filter('bulk_accounts_clear'))
async def bulk_accounts_clear(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    page = data.get("bulk_accounts_page", 1)
    fms.update_data(user_id, {"bulk_target_account_ids": []})
    await send_msg(
        bulk_accounts_text(user_id),
        get_bulk_accounts_kb(user_id, page),
        callback_query.message
    )


@Client.on_message(state_filter("awaiting_bulk_accounts"))
async def process_bulk_accounts(client: Client, message: Message):
    user_id = message.from_user.id
    accounts = db.Account.get_by_owner(user_id)
    text = message.text.strip().lower()

    if text in ("все", "all"):
        selected = accounts
    elif text in ("активные", "active"):
        selected = [account for account in accounts if account.is_started]
    else:
        requested = {item.lower().lstrip('@') for item in split_list(message.text)}
        selected = []
        for account in accounts:
            values = {str(account.id).lower()}
            if account.username:
                values.add(account.username.lower().lstrip('@'))
            if account.name:
                values.add(account.name.lower())
            if values & requested:
                selected.append(account)

    fms.update_data(user_id, {"bulk_target_account_ids": [account.id for account in selected]})
    fms.reset_state(user_id)
    data = fms.get_data(user_id)
    await send_msg(bulk_text(data), get_bulk_story_cloner_kb(data), message)


@Client.on_callback_query(data_filter('bulk_toggle_copying'))
async def bulk_toggle_copying(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_story_data(user_id)
    fms.update_data(user_id, {"bulk_is_copying_enabled": not data.get("bulk_is_copying_enabled", True)})
    data = fms.get_data(user_id)
    await send_msg(bulk_text(data), get_bulk_story_cloner_kb(data), callback_query.message)


@Client.on_callback_query(data_filter('bulk_toggle_copy_to_channel'))
async def bulk_toggle_copy_to_channel(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_story_data(user_id)
    if not data.get("bulk_copy_channel_id"):
        await callback_query.answer("Сначала укажите канал", show_alert=True)
        return
    fms.update_data(user_id, {"bulk_copy_to_channel_enabled": not data.get("bulk_copy_to_channel_enabled", False)})
    data = fms.get_data(user_id)
    await send_msg(bulk_text(data), get_bulk_story_cloner_kb(data), callback_query.message)


@Client.on_callback_query(data_filter('bulk_toggle_prohibition'))
async def bulk_toggle_prohibition(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_story_data(user_id)
    fms.update_data(user_id, {"bulk_is_copy_prohibited": not data.get("bulk_is_copy_prohibited", False)})
    data = fms.get_data(user_id)
    await send_msg(bulk_text(data), get_bulk_story_cloner_kb(data), callback_query.message)


@Client.on_callback_query(data_filter('bulk_toggle_delete_original'))
async def bulk_toggle_delete_original(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_story_data(user_id)
    fms.update_data(user_id, {"bulk_delete_if_original_deleted": not data.get("bulk_delete_if_original_deleted", False)})
    data = fms.get_data(user_id)
    await send_msg(bulk_text(data), get_bulk_story_cloner_kb(data), callback_query.message)


@Client.on_callback_query(data_filter('bulk_toggle_skip_at'))
async def bulk_toggle_skip_at(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_story_data(user_id)
    fms.update_data(user_id, {"bulk_skip_stories_with_at": not data.get("bulk_skip_stories_with_at", False)})
    data = fms.get_data(user_id)
    await send_msg(bulk_text(data), get_bulk_story_cloner_kb(data), callback_query.message)


@Client.on_callback_query(data_filter('bulk_set_publish_duration'))
async def bulk_set_publish_duration(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_story_data(user_id)
    durations = [6, 12, 24, 48]
    current_duration = data.get("bulk_publish_duration", 24)
    try:
        current_index = durations.index(current_duration)
    except ValueError:
        current_index = 2
    fms.update_data(user_id, {"bulk_publish_duration": durations[(current_index + 1) % len(durations)]})
    data = fms.get_data(user_id)
    await send_msg(bulk_text(data), get_bulk_story_cloner_kb(data), callback_query.message)


@Client.on_callback_query(data_filter('bulk_apply_story_cloner'))
async def bulk_apply_story_cloner(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_story_data(user_id)
    target_account_ids = data.get("bulk_target_account_ids", [])
    copy_from_accounts = data.get("bulk_copy_from_accounts", [])

    if not target_account_ids:
        await callback_query.answer("Выберите аккаунты", show_alert=True)
        return
    if data.get("bulk_is_copying_enabled", True) and not copy_from_accounts:
        await callback_query.answer("Укажите источники", show_alert=True)
        return

    changed = 0
    for account_id in target_account_ids:
        account = db.Account.get_by_id(account_id)
        if not account or account.owner != user_id:
            continue
        config = account.config or {}
        config.update({
            "is_copying_enabled": data.get("bulk_is_copying_enabled", True),
            "copy_from_accounts": copy_from_accounts,
            "is_copy_prohibited": data.get("bulk_is_copy_prohibited", False),
            "delete_if_original_deleted": data.get("bulk_delete_if_original_deleted", False),
            "publish_duration": data.get("bulk_publish_duration", 24),
            "skip_stories_with_at": data.get("bulk_skip_stories_with_at", False),
            "copy_to_channel_enabled": data.get("bulk_copy_to_channel_enabled", False),
            "copy_channel_id": data.get("bulk_copy_channel_id", ""),
        })
        db.Account.update_by_id(account_id, config=config)
        changed += 1

    await callback_query.answer(f"Настройки применены: {changed}", show_alert=True)
    await send_msg(f"✅ Массовая настройка применена к аккаунтам: {changed}", get_back_kb('К аккаунтам', 'accounts_'), callback_query.message)


async def story_cloner_work(app: Client):
    cursor = app.storage.conn.cursor()

    async def reserve_story(user_id, story_id):
        cursor.execute("""
            INSERT OR IGNORE INTO stories (user_id, story_id, my_story_id) VALUES (?, ?, 0);
        """, (user_id, story_id))
        await app.storage.save()
        return cursor.rowcount > 0

    async def mark_story_sent(user_id, story_id, my_story_id):
        cursor.execute("""
            UPDATE stories SET my_story_id = ? WHERE user_id = ? AND story_id = ?;
        """, (my_story_id, user_id, story_id))
        await app.storage.save()

    async def forget_reserved_story(user_id, story_id):
        cursor.execute("""
            DELETE FROM stories WHERE user_id = ? AND story_id = ? AND my_story_id = 0;
        """, (user_id, story_id))
        await app.storage.save()

    async def create_table():
        """Создает таблицу для хранения скопированных историй, если она не существует."""
        cursor.execute("""
            SELECT name 
            FROM sqlite_master 
            WHERE type='table' AND name='stories';
        """)
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE stories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    story_id INTEGER NOT NULL,
                    my_story_id INTEGER NOT NULL
                );
            """)
            await app.storage.save()
        cursor.execute("""
            DELETE FROM stories
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM stories
                GROUP BY user_id, story_id
            );
        """)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_stories_user_story
            ON stories (user_id, story_id);
        """)
        await app.storage.save()

    def get_posted_by_user(user_id):
        """Получает список уже опубликованных историй конкретного пользователя."""
        cursor.execute("""
            SELECT story_id, my_story_id 
            FROM stories 
            WHERE user_id = ?
        """, (user_id,))
        return {row[0]: row[1] for row in cursor.fetchall()}

    def get_original_story_ids_by_user_and_my_story(user_id, my_story_id):
        """Получает список уже опубликованных историй конкретного пользователя."""
        cursor.execute("""
            SELECT story_id
            FROM stories 
            WHERE user_id = ? AND my_story_id = ?
        """, (user_id,my_story_id))
        result = [row[0] for row in cursor.fetchall()]
        if result:
            return result[0]
        else:
            return None

    def get_file_id(story):
        """Получает ID файла из истории (фото или видео)."""
        return getattr(story.photo, 'file_id', None) or getattr(story.video, 'file_id', None)

    await create_table()

    while True:
        try:
            account = db.Account.get_by_id(app.me.id)
            config = account.config or {}

            if not config.get('copy_from_accounts') or not config.get('is_copying_enabled'):
                await asyncio.sleep(60)
                continue

            for user in config.get('copy_from_accounts'):
                try:
                    user_obj = await app.get_users(user)
                    if user_obj.id == app.me.id:
                        print(f"[story_cloner/{app.me.id}] Пропускаю источник {user}: аккаунт не копирует сам себя")
                        continue

                    posted_stories = get_posted_by_user(user_obj.id)
                    user_stories_id = []

                    async for story in app.get_chat_stories(user_obj.id):
                        user_stories_id.append(story.id)
                        if config.get("skip_stories_with_at", False) and story.caption and '@' in story.caption:
                            continue

                        if story.id in posted_stories:
                            continue

                        story_file_id = get_file_id(story)
                        if not story_file_id:
                            continue

                        if not await reserve_story(user_obj.id, story.id):
                            continue

                        publish_period = config.get("publish_duration", 24) * 3600  # В секундах
                        try:
                            new_story = await app.send_story(
                                'me',
                                media=story_file_id,
                                caption=story.caption,
                                period=publish_period,
                                pinned=True,
                                protect_content=config.get("is_copy_prohibited", False)
                            )
                        except Exception:
                            await forget_reserved_story(user_obj.id, story.id)
                            raise

                        channel_id = config.get("copy_channel_id")
                        if config.get("copy_to_channel_enabled", False) and channel_id:
                            try:
                                await send_story_to_channel(
                                    app,
                                    channel_id,
                                    story,
                                    story_file_id,
                                    story.caption,
                                    publish_period,
                                    config.get("is_copy_prohibited", False)
                                )
                                db.Analytics.create_record(
                                    app.me.id,
                                    'Скопировал историю в канал',
                                    details=f"Источник: {user}\nКанал: {channel_id}"
                                )
                            except Exception as e:
                                print(f"[story_cloner/{app.me.id}] Ошибка репоста в канал {channel_id}: {e}")

                        db.Analytics.create_record(
                            app.me.id,
                            'Скопировал историю',
                            details=f"Источник: {user}"
                        )

                        await mark_story_sent(user_obj.id, story.id, new_story.id)
                        await asyncio.sleep(60)

                    if config.get('delete_if_original_deleted', False):

                        async for story in app.get_chat_stories('me'):
                            original_story_id = get_original_story_ids_by_user_and_my_story(user_obj.id, story.id)
                            if not original_story_id:
                                continue

                            if original_story_id in user_stories_id:
                                continue

                            if story.expire_date - datetime.now() < timedelta(hours=1):
                                continue

                            await story.delete()
                            await asyncio.sleep(60)

                except FloodWait as e:
                    print(f"FloodWait error: Sleeping for {e.value} seconds.")
                    await asyncio.sleep(e.value)
                except RPCError as e:
                    print(f"RPCError: {e}")
                    await asyncio.sleep(60)
                except (AuthKeyUnregistered, SessionRevoked, UserDeactivated) as e:
                    print('Слетела авторизация')
                    await modules.accounts_storage.de_launch_account(app.me.id)
                    return
                except Exception as e:
                    print(f"Unexpected error: {e}")
                    await asyncio.sleep(60)

        except Exception as e:
            print(f"Critical error in story_cloner: {e}")
            await asyncio.sleep(60)

        await asyncio.sleep(60)
