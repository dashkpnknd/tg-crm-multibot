import asyncio
from datetime import datetime
from math import ceil
from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.errors import FloodWait, RPCError, AuthKeyUnregistered, SessionRevoked, UserDeactivated
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
import modules
from modules import db
from modules.FMS import fms
from modules.filters import data_filter, data_filter_startswith, state_filter
from modules.message import send_msg, messages_to_json, json_to_message
from plugins.add_account import get_back_kb

def get_sender_kb(data):
    messages = data.get("sender_messages", [])
    interval = data.get("sender_interval", 5)
    min_days = data.get("sender_min_days", 1)
    max_days = data.get("sender_max_days", 365)
    blacklist = data.get("sender_blacklist", [])
    keyboard = [
        [InlineKeyboardButton(f"Сообщения: {len(messages)} шт ✉️", callback_data="set_sender_messages" if len(messages) < 3 else 'first_clear')],
        [InlineKeyboardButton(f"Очистить сообщения 🗑️", callback_data="clear_sender_messages")],
        [InlineKeyboardButton(f"Чёрный список: {len(blacklist)} чел 🚫", callback_data="manage_sender_blacklist")],
        [InlineKeyboardButton(f"Интервал: {interval} мин ⏱️", callback_data="set_sender_interval")],
        [InlineKeyboardButton(f"Мин. дней без сообщений: {min_days} 📅", callback_data="set_sender_min_days")],
        [InlineKeyboardButton(f"Макс. дней без сообщений: {max_days} 📅", callback_data="set_sender_max_days")],
        [InlineKeyboardButton("Запустить рассылку ✅", callback_data="confirm_sender")],
        [InlineKeyboardButton("Назад ◀️", callback_data="account_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

sender_text = "Настройте рассылку:\n\n⚠️ Рассылка будет произведена по всем людям с которыми не было общение в заданный интервал дней"
bulk_sender_text = "Массовая настройка рассылки по ЛС:"


def account_label(account: db.Account):
    name = account.name or str(account.id)
    username = f"@{account.username}" if account.username else str(account.id)
    return f"{name} ({username})"


def init_bulk_sender_data(user_id):
    data = fms.get_data(user_id)
    defaults = {
        "bulk_sender_account_ids": data.get("bulk_sender_account_ids", []),
        "bulk_sender_messages": data.get("bulk_sender_messages", []),
        "bulk_sender_interval": data.get("bulk_sender_interval", 5),
        "bulk_sender_min_days": data.get("bulk_sender_min_days", 1),
        "bulk_sender_max_days": data.get("bulk_sender_max_days", 365),
        "bulk_sender_blacklist": data.get("bulk_sender_blacklist", []),
        "bulk_sender_page": data.get("bulk_sender_page", 1),
    }
    fms.update_data(user_id, defaults)
    return fms.get_data(user_id)


def get_bulk_sender_kb(data):
    selected_count = len(data.get("bulk_sender_account_ids", []))
    messages_count = len(data.get("bulk_sender_messages", []))
    interval = data.get("bulk_sender_interval", 5)
    min_days = data.get("bulk_sender_min_days", 1)
    max_days = data.get("bulk_sender_max_days", 365)
    blacklist = data.get("bulk_sender_blacklist", [])
    keyboard = [
        [InlineKeyboardButton(f"Аккаунты: {selected_count}", callback_data="bulk_sender_accounts")],
        [InlineKeyboardButton(f"Сообщения: {messages_count} шт ✉️", callback_data="bulk_sender_set_messages" if messages_count < 3 else "bulk_sender_first_clear")],
        [InlineKeyboardButton("Очистить сообщения 🗑️", callback_data="bulk_sender_clear_messages")],
        [InlineKeyboardButton(f"Чёрный список: {len(blacklist)} чел 🚫", callback_data="bulk_sender_blacklist")],
        [InlineKeyboardButton(f"Интервал: {interval} мин ⏱️", callback_data="bulk_sender_interval")],
        [InlineKeyboardButton(f"Мин. дней без сообщений: {min_days} 📅", callback_data="bulk_sender_min_days")],
        [InlineKeyboardButton(f"Макс. дней без сообщений: {max_days} 📅", callback_data="bulk_sender_max_days")],
        [InlineKeyboardButton("Запустить у выбранных ✅", callback_data="bulk_sender_apply")],
        [InlineKeyboardButton("Отключить у выбранных ❌", callback_data="bulk_sender_cancel_selected")],
        [InlineKeyboardButton("Назад ◀️", callback_data="accounts_")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_bulk_sender_accounts_kb(user_id, page=1, accounts_per_page=8):
    data = fms.get_data(user_id)
    selected_ids = set(data.get("bulk_sender_account_ids", []))
    accounts = db.Account.get_by_owner(user_id)
    total_pages = max(1, ceil(len(accounts) / accounts_per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * accounts_per_page
    page_accounts = accounts[start:start + accounts_per_page]
    keyboard = []
    for account in page_accounts:
        mark = "✅" if account.id in selected_ids else "☑️"
        active_sender = db.Sender.get_by_account_id(account.id)
        status = "ЛС активна" if active_sender else "ЛС выкл."
        keyboard.append([
            InlineKeyboardButton(f"{mark} {account_label(account)} · {status}", callback_data=f"bulk_sender_toggle_{account.id}")
        ])

    pagination = []
    if page > 1:
        pagination.append(InlineKeyboardButton("⬅️", callback_data=f"bulk_sender_page_{page - 1}"))
    pagination.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="bulk_sender_noop"))
    if page < total_pages:
        pagination.append(InlineKeyboardButton("➡️", callback_data=f"bulk_sender_page_{page + 1}"))
    keyboard.append(pagination)
    keyboard.append([
        InlineKeyboardButton("Все", callback_data="bulk_sender_all"),
        InlineKeyboardButton("Активные", callback_data="bulk_sender_active"),
        InlineKeyboardButton("Локальные", callback_data="bulk_sender_local"),
        InlineKeyboardButton("Очистить", callback_data="bulk_sender_clear_accounts"),
    ])
    keyboard.append([InlineKeyboardButton("Готово ✅", callback_data="bulk_sender")])
    return InlineKeyboardMarkup(keyboard)


def bulk_sender_summary(data):
    return (
        f"{bulk_sender_text}\n\n"
        f"Аккаунтов выбрано: <b>{len(data.get('bulk_sender_account_ids', []))}</b>\n"
        f"Сообщений: <b>{len(data.get('bulk_sender_messages', []))}</b>\n"
        f"Интервал: <b>{data.get('bulk_sender_interval', 5)} мин</b>\n"
        f"Дней без сообщений: <b>{data.get('bulk_sender_min_days', 1)}-{data.get('bulk_sender_max_days', 365)}</b>"
    )


def bulk_sender_accounts_text(user_id):
    data = fms.get_data(user_id)
    return f"Выберите аккаунты для рассылки по ЛС:\n\nВыбрано: <b>{len(data.get('bulk_sender_account_ids', []))}</b>"


def normalize_sender_numbers(data):
    interval = int(data.get("bulk_sender_interval", 5))
    min_days = int(data.get("bulk_sender_min_days", 1))
    max_days = int(data.get("bulk_sender_max_days", 365))
    return interval, min_days, max_days

@Client.on_callback_query(data_filter('sender'))
@Client.on_callback_query(data_filter('sender_back'))
async def seder_menu(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)

    if not account:
        await callback_query.answer('Необходимо войти в аккаунт!', show_alert=True)
        return

    active_sender = db.Sender.get_by_account_id(account_id)
    if active_sender:
        active_sender = active_sender[0]
        text = f'''Активная рассылка:
С интервалом: {active_sender.interval} мин ⏱️
Уже отправлено: {len(active_sender.sent)} ✅
    '''
        keyboard = [
            [InlineKeyboardButton(f"Отменить ❌", callback_data="cansel_sender")],
            [InlineKeyboardButton(f"Назад ◀️", callback_data="account_")],
        ]
        await send_msg(text, InlineKeyboardMarkup(keyboard), callback_query.message)
    else:
        if callback_query.data == 'sender':
            fms.update_data(user_id, {
                "sender_messages": [],
                "sender_interval": 5,
                "sender_min_days": 1,
                "sender_max_days": 365,
                "sender_blacklist": [],
            })
        await send_msg(sender_text, get_sender_kb(fms.get_data(user_id)), callback_query.message)

@Client.on_callback_query(data_filter('cansel_sender'))
async def cansel_sender(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    state = fms.get_state(user_id)
    if state == 'cansel_sender':
        account_id = data.get('open_account')
        active_sender = db.Sender.get_by_account_id(account_id)
        if active_sender:
            db.Sender.delete_by_id(active_sender[0].id)
        await send_msg("Рассылка сообщений отменена! ❌", get_back_kb('Назад ◀️', 'account_'), callback_query.message)
    else:
        fms.set_state(user_id, 'cansel_sender')
        await callback_query.answer(
            '⚠️ Чтобы подтвердить отмену, нажмите ещё раз',
            show_alert=True
        )

@Client.on_callback_query(data_filter('first_clear'))
async def first_clear(client: Client, callback_query: CallbackQuery):
    await callback_query.answer('Для начала очистите сообщения, чтобы добавить новые ⚠️')

@Client.on_callback_query(data_filter('clear_sender_messages'))
async def clear_sender_message(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.update_data(user_id, {"sender_messages": []})
    await send_msg(sender_text, get_sender_kb(fms.get_data(user_id)), callback_query.message)

@Client.on_callback_query(data_filter('set_sender_messages'))
async def set_sender_message(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    messages = data.get('sender_messages')
    fms.set_state(user_id, 'awaiting_sender_message')
    await send_msg(f"Введите сообщение для рассылки ({len(messages)} из 3): ✉️", get_back_kb('Отмена ❌', 'sender_back'), callback_query.message)

media_group_ban = []

@Client.on_message(state_filter("awaiting_sender_message"))
async def process_sender_message(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    sender_messages = data.get('sender_messages', [])
    if message.media_group_id:
        if message.media_group_id in media_group_ban:
            return
        media_group_ban.append(message.media_group_id)
        input_messages = await message.get_media_group()
    else:
        input_messages = [message]

    new_message = await messages_to_json(input_messages)
    sender_messages.append(new_message)
    fms.update_data(user_id, {"sender_messages": sender_messages})
    fms.reset_state(user_id)
    await send_msg(sender_text, get_sender_kb(fms.get_data(user_id)), message)

@Client.on_callback_query(data_filter('set_sender_interval'))
async def set_sender_interval(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_sender_interval')
    await send_msg("Введите интервал (не менее 5 минут): ⏱️", get_back_kb('Отмена ❌', 'sender_back'),
                   callback_query.message)

@Client.on_message(state_filter("awaiting_sender_interval"))
async def process_sender_interval(client: Client, message: Message):
    user_id = message.from_user.id
    if not message.text.isdigit() or int(message.text) < 5 or int(message.text) > 10000:
        await message.delete()
        return
    interval = int(message.text)
    fms.update_data(user_id, {"sender_interval": interval})
    fms.reset_state(user_id)
    await send_msg(sender_text, get_sender_kb(fms.get_data(user_id)), message)

@Client.on_callback_query(data_filter('set_sender_min_days'))
async def set_sender_min_days(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_sender_min_days')
    await send_msg("Введите минимальное количество дней: 📅", get_back_kb('Отмена ❌', 'sender_back'),
                   callback_query.message)

@Client.on_message(state_filter("awaiting_sender_min_days"))
async def process_sender_min_days(client: Client, message: Message):
    user_id = message.from_user.id
    if not message.text.isdigit() or int(message.text) < 0:
        await message.delete()
        return
    min_days = int(message.text)
    fms.update_data(user_id, {"sender_min_days": min_days})
    fms.reset_state(user_id)
    await send_msg(sender_text, get_sender_kb(fms.get_data(user_id)), message)

@Client.on_callback_query(data_filter('set_sender_max_days'))
async def set_sender_max_days(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_sender_max_days')
    await send_msg("Введите максимальное количество дней: 📅", get_back_kb('Отмена ❌', 'sender_back'),
                   callback_query.message)

@Client.on_message(state_filter("awaiting_sender_max_days"))
async def process_sender_max_days(client: Client, message: Message):
    user_id = message.from_user.id
    if not message.text.isdigit() or int(message.text) < 1:
        await message.delete()
        return
    max_days = int(message.text)
    fms.update_data(user_id, {"sender_max_days": max_days})
    fms.reset_state(user_id)
    await send_msg(sender_text, get_sender_kb(fms.get_data(user_id)), message)

@Client.on_callback_query(data_filter('confirm_sender'))
async def confirm_sender(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    messages = data.get('sender_messages', [])
    if not messages:
        await callback_query.answer('⚠️ Установите сообщение!', show_alert=True)
        return
    db.Sender.create(account_id, messages, data.get('sender_interval'), data.get('sender_min_days'), data.get('sender_max_days'), data.get('sender_blacklist'))
    await send_msg("Рассылка успешно запущена! ✅", get_back_kb('Назад ◀️', 'account_'), callback_query.message)



@Client.on_callback_query(data_filter('manage_sender_blacklist'))
async def manage_sender_blacklist(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    blacklist = data.get("sender_blacklist", [])
    if not blacklist:
        example = "user1, user2, @user3"
    else:
        example = ", ".join(str(x) for x in blacklist)
    text = (
        "<b>Чёрный список рассылки</b>\n\n"
        "Введите список username'ов или ID пользователей через запятую.\n"
        "Пример: user1, @user2\n\n"
        f"<b>Текущий список:</b>\n<code>{example}</code>"
    )
    await send_msg(text, get_back_kb('Отмена ❌', 'sender_back'), callback_query.message)
    fms.set_state(user_id, 'awaiting_sender_blacklist')


@Client.on_message(state_filter("awaiting_sender_blacklist"))
async def process_sender_blacklist(client: Client, message: Message):
    user_id = message.from_user.id
    raw_input = message.text.strip()
    try:
        entries = [x.strip().replace('@', '') for x in raw_input.split(',') if x.strip()]
        fms.update_data(user_id, {"sender_blacklist": entries})
        await send_msg("✅ Чёрный список обновлён", get_sender_kb(fms.get_data(user_id)), message)
    except Exception as e:
        await send_msg(f"⚠️ Ошибка формата: {e}", get_back_kb('Попробовать снова', 'manage_sender_blacklist'), message)
    finally:
        fms.reset_state(user_id)


@Client.on_callback_query(data_filter('bulk_sender'))
async def bulk_sender(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.reset_state(user_id)
    data = init_bulk_sender_data(user_id)
    await send_msg(bulk_sender_summary(data), get_bulk_sender_kb(data), callback_query.message)


@Client.on_callback_query(data_filter('bulk_sender_accounts'))
async def bulk_sender_accounts(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.update_data(user_id, {"bulk_sender_page": 1})
    await send_msg(bulk_sender_accounts_text(user_id), get_bulk_sender_accounts_kb(user_id, 1), callback_query.message)


@Client.on_callback_query(data_filter('bulk_sender_noop'))
async def bulk_sender_noop(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()


@Client.on_callback_query(data_filter_startswith('bulk_sender_page_'))
async def bulk_sender_page(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    page = int(callback_query.data.split('_')[-1])
    fms.update_data(user_id, {"bulk_sender_page": page})
    await send_msg(bulk_sender_accounts_text(user_id), get_bulk_sender_accounts_kb(user_id, page), callback_query.message)


@Client.on_callback_query(data_filter_startswith('bulk_sender_toggle_'))
async def bulk_sender_toggle(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    account_id = int(callback_query.data.split('_')[-1])
    data = init_bulk_sender_data(user_id)
    selected_ids = set(data.get("bulk_sender_account_ids", []))
    if account_id in selected_ids:
        selected_ids.remove(account_id)
    else:
        selected_ids.add(account_id)
    page = data.get("bulk_sender_page", 1)
    fms.update_data(user_id, {"bulk_sender_account_ids": list(selected_ids)})
    await send_msg(bulk_sender_accounts_text(user_id), get_bulk_sender_accounts_kb(user_id, page), callback_query.message)


@Client.on_callback_query(data_filter('bulk_sender_all'))
async def bulk_sender_all(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    accounts = db.Account.get_by_owner(user_id)
    data = init_bulk_sender_data(user_id)
    fms.update_data(user_id, {"bulk_sender_account_ids": [account.id for account in accounts]})
    await send_msg(bulk_sender_accounts_text(user_id), get_bulk_sender_accounts_kb(user_id, data.get("bulk_sender_page", 1)), callback_query.message)


@Client.on_callback_query(data_filter('bulk_sender_active'))
async def bulk_sender_active(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    accounts = db.Account.get_by_owner(user_id)
    data = init_bulk_sender_data(user_id)
    fms.update_data(user_id, {"bulk_sender_account_ids": [account.id for account in accounts if account.is_started]})
    await send_msg(bulk_sender_accounts_text(user_id), get_bulk_sender_accounts_kb(user_id, data.get("bulk_sender_page", 1)), callback_query.message)


@Client.on_callback_query(data_filter('bulk_sender_local'))
async def bulk_sender_local(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    accounts = db.Account.get_by_owner(user_id)
    data = init_bulk_sender_data(user_id)
    local_accounts = [
        account.id for account in accounts
        if "local" in ((account.username or "") + " " + (account.name or "")).lower()
    ]
    fms.update_data(user_id, {"bulk_sender_account_ids": local_accounts})
    await send_msg(bulk_sender_accounts_text(user_id), get_bulk_sender_accounts_kb(user_id, data.get("bulk_sender_page", 1)), callback_query.message)


@Client.on_callback_query(data_filter('bulk_sender_clear_accounts'))
async def bulk_sender_clear_accounts(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_sender_data(user_id)
    fms.update_data(user_id, {"bulk_sender_account_ids": []})
    await send_msg(bulk_sender_accounts_text(user_id), get_bulk_sender_accounts_kb(user_id, data.get("bulk_sender_page", 1)), callback_query.message)


@Client.on_callback_query(data_filter('bulk_sender_first_clear'))
async def bulk_sender_first_clear(client: Client, callback_query: CallbackQuery):
    await callback_query.answer('Для начала очистите сообщения, чтобы добавить новые ⚠️')


@Client.on_callback_query(data_filter('bulk_sender_clear_messages'))
async def bulk_sender_clear_messages(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.update_data(user_id, {"bulk_sender_messages": []})
    data = init_bulk_sender_data(user_id)
    await send_msg(bulk_sender_summary(data), get_bulk_sender_kb(data), callback_query.message)


@Client.on_callback_query(data_filter('bulk_sender_set_messages'))
async def bulk_sender_set_messages(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_sender_data(user_id)
    messages = data.get("bulk_sender_messages", [])
    fms.set_state(user_id, 'awaiting_bulk_sender_message')
    await send_msg(f"Введите сообщение для массовой рассылки ({len(messages)} из 3): ✉️", get_back_kb('Отмена ❌', 'bulk_sender'), callback_query.message)


@Client.on_message(state_filter("awaiting_bulk_sender_message"))
async def process_bulk_sender_message(client: Client, message: Message):
    user_id = message.from_user.id
    data = init_bulk_sender_data(user_id)
    sender_messages = data.get("bulk_sender_messages", [])
    if message.media_group_id:
        if message.media_group_id in media_group_ban:
            return
        media_group_ban.append(message.media_group_id)
        input_messages = await message.get_media_group()
    else:
        input_messages = [message]

    new_message = await messages_to_json(input_messages)
    sender_messages.append(new_message)
    fms.update_data(user_id, {"bulk_sender_messages": sender_messages})
    fms.reset_state(user_id)
    data = init_bulk_sender_data(user_id)
    await send_msg(bulk_sender_summary(data), get_bulk_sender_kb(data), message)


@Client.on_callback_query(data_filter('bulk_sender_interval'))
async def bulk_sender_interval(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_bulk_sender_interval')
    await send_msg("Введите интервал (не менее 5 минут): ⏱️", get_back_kb('Отмена ❌', 'bulk_sender'), callback_query.message)


@Client.on_message(state_filter("awaiting_bulk_sender_interval"))
async def process_bulk_sender_interval(client: Client, message: Message):
    user_id = message.from_user.id
    if not message.text.isdigit() or int(message.text) < 5 or int(message.text) > 10000:
        await message.delete()
        return
    fms.update_data(user_id, {"bulk_sender_interval": int(message.text)})
    fms.reset_state(user_id)
    data = init_bulk_sender_data(user_id)
    await send_msg(bulk_sender_summary(data), get_bulk_sender_kb(data), message)


@Client.on_callback_query(data_filter('bulk_sender_min_days'))
async def bulk_sender_min_days(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_bulk_sender_min_days')
    await send_msg("Введите минимальное количество дней: 📅", get_back_kb('Отмена ❌', 'bulk_sender'), callback_query.message)


@Client.on_message(state_filter("awaiting_bulk_sender_min_days"))
async def process_bulk_sender_min_days(client: Client, message: Message):
    user_id = message.from_user.id
    if not message.text.isdigit() or int(message.text) < 0:
        await message.delete()
        return
    fms.update_data(user_id, {"bulk_sender_min_days": int(message.text)})
    fms.reset_state(user_id)
    data = init_bulk_sender_data(user_id)
    await send_msg(bulk_sender_summary(data), get_bulk_sender_kb(data), message)


@Client.on_callback_query(data_filter('bulk_sender_max_days'))
async def bulk_sender_max_days(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_bulk_sender_max_days')
    await send_msg("Введите максимальное количество дней: 📅", get_back_kb('Отмена ❌', 'bulk_sender'), callback_query.message)


@Client.on_message(state_filter("awaiting_bulk_sender_max_days"))
async def process_bulk_sender_max_days(client: Client, message: Message):
    user_id = message.from_user.id
    if not message.text.isdigit() or int(message.text) < 1:
        await message.delete()
        return
    fms.update_data(user_id, {"bulk_sender_max_days": int(message.text)})
    fms.reset_state(user_id)
    data = init_bulk_sender_data(user_id)
    await send_msg(bulk_sender_summary(data), get_bulk_sender_kb(data), message)


@Client.on_callback_query(data_filter('bulk_sender_blacklist'))
async def bulk_sender_blacklist(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_sender_data(user_id)
    blacklist = data.get("bulk_sender_blacklist", [])
    example = ", ".join(str(x) for x in blacklist) if blacklist else "user1, user2, @user3"
    text = (
        "<b>Чёрный список массовой ЛС-рассылки</b>\n\n"
        "Введите список username'ов или ID пользователей через запятую.\n\n"
        f"<b>Текущий список:</b>\n<code>{example}</code>"
    )
    fms.set_state(user_id, 'awaiting_bulk_sender_blacklist')
    await send_msg(text, get_back_kb('Отмена ❌', 'bulk_sender'), callback_query.message)


@Client.on_message(state_filter("awaiting_bulk_sender_blacklist"))
async def process_bulk_sender_blacklist(client: Client, message: Message):
    user_id = message.from_user.id
    entries = [x.strip().replace('@', '') for x in message.text.strip().split(',') if x.strip()]
    fms.update_data(user_id, {"bulk_sender_blacklist": entries})
    fms.reset_state(user_id)
    data = init_bulk_sender_data(user_id)
    await send_msg(bulk_sender_summary(data), get_bulk_sender_kb(data), message)


@Client.on_callback_query(data_filter('bulk_sender_apply'))
async def bulk_sender_apply(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_sender_data(user_id)
    account_ids = data.get("bulk_sender_account_ids", [])
    messages = data.get("bulk_sender_messages", [])
    if not account_ids:
        await callback_query.answer('⚠️ Выберите аккаунты!', show_alert=True)
        return
    if not messages:
        await callback_query.answer('⚠️ Установите сообщение!', show_alert=True)
        return

    interval, min_days, max_days = normalize_sender_numbers(data)
    if min_days > max_days:
        await callback_query.answer('⚠️ Минимум дней не может быть больше максимума', show_alert=True)
        return

    started = []
    replaced = []
    skipped = []
    for account_id in account_ids:
        account = db.Account.get_by_id(account_id)
        if not account:
            skipped.append(str(account_id))
            continue
        active_senders = db.Sender.get_by_account_id(account_id)
        for sender in active_senders:
            db.Sender.delete_by_id(sender.id)
        db.Sender.create(account_id, messages, interval, min_days, max_days, data.get("bulk_sender_blacklist", []))
        label = account.username or account.name or str(account_id)
        if active_senders:
            replaced.append(label)
        else:
            started.append(label)

    parts = []
    if started:
        parts.append(f"запущено: {', '.join(started)}")
    if replaced:
        parts.append(f"обновлено: {', '.join(replaced)}")
    if skipped:
        parts.append(f"пропущено: {', '.join(skipped)}")
    await send_msg("✅ Массовая ЛС-рассылка применена: " + "; ".join(parts), get_back_kb('К аккаунтам', 'accounts_'), callback_query.message)


@Client.on_callback_query(data_filter('bulk_sender_cancel_selected'))
async def bulk_sender_cancel_selected(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = init_bulk_sender_data(user_id)
    account_ids = data.get("bulk_sender_account_ids", [])
    if not account_ids:
        await callback_query.answer('⚠️ Выберите аккаунты!', show_alert=True)
        return

    cancelled = []
    not_active = []
    for account_id in account_ids:
        account = db.Account.get_by_id(account_id)
        label = (account.username or account.name or str(account_id)) if account else str(account_id)
        active_senders = db.Sender.get_by_account_id(account_id)
        if active_senders:
            for sender in active_senders:
                db.Sender.delete_by_id(sender.id)
            cancelled.append(label)
        else:
            not_active.append(label)

    text = "❌ Массовая ЛС-рассылка отключена у выбранных аккаунтов."
    if cancelled:
        text += "\n\nОтключено: " + ", ".join(cancelled)
    if not_active:
        text += "\n\nУже было выключено: " + ", ".join(not_active)
    await send_msg(text, get_back_kb('К аккаунтам', 'accounts_'), callback_query.message)


async def sender_work(app: Client):
    """
    Модуль для рассылки по личным сообщениям.
    """
    while True:
        try:
            senders = db.Sender.get_by_account_id(app.me.id)
            for sender in senders:
                black_list = set(sender.black_list or [])
                async for dialog in app.get_dialogs():
                    if dialog.chat.type != ChatType.PRIVATE:
                        continue
                    
                    if dialog.chat.username and dialog.chat.username in black_list:
                        continue                    
                    
                    top_message = dialog.top_message
                    if not top_message:
                        continue
                    days_since_last_message = (datetime.now() - top_message.date).days
                    if days_since_last_message < sender.min_days or days_since_last_message > sender.max_days:
                        continue
                    if dialog.chat.id in sender.sent:
                        continue
                    for message in sender.messages:
                        try:
                            await json_to_message(app, dialog.chat.id, message)
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                        except RPCError as e:
                            await asyncio.sleep(60)
                        except (AuthKeyUnregistered, SessionRevoked, UserDeactivated) as e:
                            await modules.accounts_storage.de_launch_account(app.me.id)
                            return
                        except Exception as e:
                            print(f"Unexpected error: {e}")
                            await asyncio.sleep(60)
                        await asyncio.sleep(10)
                        sender.sent.append(dialog.chat.id)
                        db.Sender.update_by_id(sender.id, sent=sender.sent)
                    for _ in range(sender.interval):
                        await asyncio.sleep(60)
                        active_sender = db.Sender.get_by_account_id(app.me.id)
                        if not active_sender or active_sender[0].id != sender.id:
                            break
                    active_sender = db.Sender.get_by_account_id(app.me.id)
                    if not active_sender or active_sender[0].id != sender.id:
                        break
                db.Sender.delete_by_id(sender.id)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except RPCError as e:
            await asyncio.sleep(60)
        except (AuthKeyUnregistered, SessionRevoked, UserDeactivated) as e:
            await modules.accounts_storage.de_launch_account(app.me.id)
            return
        except Exception as e:
            print(f"Sender Unexpected error: {e}")
            await asyncio.sleep(60)
        await asyncio.sleep(60)
