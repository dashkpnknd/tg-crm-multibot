import asyncio
from datetime import datetime
from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.errors import FloodWait, RPCError, AuthKeyUnregistered, SessionRevoked, UserDeactivated
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
import modules
from modules import db
from modules.FMS import fms
from modules.filters import data_filter, state_filter
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