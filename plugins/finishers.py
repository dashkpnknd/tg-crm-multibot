import asyncio
from datetime import datetime

from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.errors import FloodWait, RPCError, AuthKeyUnregistered, SessionRevoked, UserDeactivated
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message

from modules import db
from modules.FMS import fms
from modules.filters import data_filter, state_filter, data_filter_startswith
from modules.message import send_msg, messages_to_json, json_to_message
from plugins.add_account import get_back_kb

import modules

def get_finishers_kb(account_id):
    messages = db.Finisher.get_by_account_id(account_id)
    keyboard = []

    for msg in messages:
        keyboard.append([InlineKeyboardButton(f'{msg.days_without_message} день без сообщений 📅', callback_data=f"finisher_{msg.id}")])

    keyboard.append([InlineKeyboardButton("Добавить сообщение ✉️", callback_data="add_finisher")])
    keyboard.append([InlineKeyboardButton("Копировать настройки 🔄", callback_data="copy_finisher_settings_from_username")])
    keyboard.append([InlineKeyboardButton("Назад ◀️", callback_data="account_menu")])
    return InlineKeyboardMarkup(keyboard)

sender_text = 'Настройте добивающие сообщения:\n\n⚠️ Добивающее сообщение приходит по прошествию определённого кол-ва дней без сообщений\n⚠️ Каждое сообщение присылается только один раз, далее отсчёт идёт заново и присылается следующее сообщение'


@Client.on_callback_query(data_filter('finishers'))
async def finishers_menu(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    await send_msg(sender_text, get_finishers_kb(account_id), callback_query.message)

@Client.on_callback_query(data_filter('add_finisher'))
async def add_finisher(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_days_without_message')
    await send_msg("Введите кол-во дней без сообщения 📅:", get_back_kb('Отмена ❌', 'finishers'), callback_query.message)


@Client.on_message(state_filter('awaiting_days_without_message'))
async def process_add_finisher_days(client: Client, message: Message):
    user_id = message.from_user.id

    days_input = message.text.strip()

    if not days_input.isdigit():
        await message.delete()
        return

    fms.update_data(user_id, {"days_without_message": int(days_input)})
    fms.set_state(user_id, 'awaiting_finisher_message')
    await send_msg("Пришлите добивающее сообщение ✉️:", get_back_kb('Отмена ❌', 'finishers'), message)


media_group_ban=[]

@Client.on_message(state_filter('awaiting_finisher_message'))
async def process_add_finisher_text(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')

    if message.media_group_id:
        if message.media_group_id in media_group_ban:
            return
        media_group_ban.append(message.media_group_id)
        input_messages = await message.get_media_group()
    else:
        input_messages = [message]

    new_message = await messages_to_json(input_messages)

    db.Finisher.create(account_id, new_message, data.get('days_without_message'))
    fms.reset_state(user_id)

    await send_msg(sender_text, get_finishers_kb(account_id), message)

def get_finisher_kb(finisher_id):
    finisher = db.Finisher.get_by_id(finisher_id)
    keyboard = [
        [InlineKeyboardButton(f"Изменить день 📅: {finisher.days_without_message}", callback_data=f"edit_days")],
        [InlineKeyboardButton("Изменить сообщение ✉️", callback_data=f"edit_message")],
        [InlineKeyboardButton("Удалить сообщение 🗑️", callback_data=f"delete_finisher")],
        [InlineKeyboardButton("Назад ◀️", callback_data="finishers")]
    ]
    return InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(data_filter_startswith('finisher_'))
async def finisher_menu(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)

    try:
        finisher_id = int(callback_query.data.split('_')[1])
    except (IndexError, ValueError):
        finisher_id = data.get('open_finisher')

    fms.update_data(user_id, {'open_finisher': finisher_id})
    await send_msg(f"Редактирование добивающего сообщения ✏️:", get_finisher_kb(finisher_id), callback_query.message,)


@Client.on_callback_query(data_filter('edit_days'))
async def edit_finisher_days(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_edit_days')
    await send_msg("Введите новое количество дней без сообщений 📅:", get_back_kb('Отмена ❌', 'finisher_'), callback_query.message)


@Client.on_message(state_filter('awaiting_edit_days'))
async def process_edit_finisher_days(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    finisher_id = data.get('open_finisher')

    days_input = message.text.strip()

    if not days_input.isdigit():
        await message.delete()
        return

    db.Finisher.update_by_id(finisher_id, days_without_message=int(days_input))

    fms.reset_state(user_id)
    await send_msg(f"Редактирование добивающего сообщения ✏️:", get_finisher_kb(finisher_id), message, )


@Client.on_callback_query(data_filter('edit_message'))
async def edit_finisher_message(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'awaiting_edit_message')
    await send_msg("Пришлите новое добивающее сообщение ✉️:",get_back_kb('Отмена ❌', 'finisher_'), callback_query.message)


@Client.on_message(state_filter('awaiting_edit_message'))
async def process_edit_finisher_message(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    finisher_id = data.get('open_finisher')

    if message.media_group_id:
        if message.media_group_id in media_group_ban:
            return
        media_group_ban.append(message.media_group_id)
        input_messages = await message.get_media_group()
    else:
        input_messages = [message]

    new_message = await messages_to_json(input_messages)

    db.Finisher.update_by_id(finisher_id, message=new_message)

    fms.reset_state(user_id)
    await send_msg(f"Редактирование добивающего сообщения ✏️:", get_finisher_kb(finisher_id), message, )



@Client.on_callback_query(data_filter('delete_finisher'))
async def delete_finisher_message(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    finisher_id = data.get('open_finisher')
    account_id = data.get('open_account')

    state = fms.get_state(user_id)

    if state == 'delete_finisher':
        db.Finisher.delete_by_id(finisher_id)
        fms.reset_state(user_id)
        await send_msg("Настройте добивающие сообщения 🛠️:", get_finishers_kb(account_id), callback_query.message)

    else:
        fms.set_state(user_id, 'delete_finisher')
        await callback_query.answer(
            '⚠️ Чтобы подтвердить удаление, нажмите ещё раз',
            show_alert=True
        )


def get_accounts_for_copy_kb(accounts):
    keyboard = []
    for account in accounts:
        keyboard.append(
            [InlineKeyboardButton(account.username, callback_data=f"copy_finisher_settings_from_{account.id}")])
    keyboard.append([InlineKeyboardButton("Отмена ❌", callback_data="finishers")])
    return InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(data_filter('copy_finisher_settings_from_username'))
async def copy_settings(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    accounts = db.Account.get_by_owner(user_id)
    if not accounts:
        await callback_query.answer("⚠️ У вас нет других аккаунтов для копирования настроек", show_alert=True)
        return
    fms.set_state(user_id, 'awaiting_finisher_copy_username')
    await send_msg(
        'Выберите аккаунт, с которого нужно скопировать настройки:',
        get_accounts_for_copy_kb(accounts),
        callback_query.message
    )


@Client.on_callback_query(data_filter_startswith('copy_finisher_settings_from_'))
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
    source_finishers = db.Finisher.get_by_account_id(source_account_id)
    target_finishers = db.Finisher.get_by_account_id(target_account_id)

    # Удаляем существующие добивающие сообщения у целевого аккаунта
    for finisher in target_finishers:
        db.Finisher.delete_by_id(finisher.id)

    # Создаем новые добивающие сообщения на основе источника
    for finisher in source_finishers:
        db.Finisher.create(
            target_account_id,
            finisher.message,
            finisher.days_without_message
        )

    fms.reset_state(user_id)
    await callback_query.answer("✅ Настройки успешно скопированы", show_alert=True)
    await send_msg(sender_text, get_finishers_kb(target_account_id), callback_query.message)


@Client.on_message(state_filter("awaiting_finisher_copy_username"))
async def process_finisher_copy_username(client: Client, message: Message):
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
                           get_back_kb("Попробовать снова", "copy_finisher_settings_from_username"), message)
            return

        # Копируем настройки
        source_finishers = db.Finisher.get_by_account_id(source_account.id)
        target_finishers = db.Finisher.get_by_account_id(target_account_id)

        # Удаляем существующие добивающие сообщения у целевого аккаунта
        for finisher in target_finishers:
            db.Finisher.delete_by_id(finisher.id)

        # Создаем новые добивающие сообщения на основе источника
        for finisher in source_finishers:
            db.Finisher.create(
                target_account_id,
                finisher.message,
                finisher.days_without_message
            )

        await send_msg("✅ Настройки успешно скопированы!", get_finishers_kb(target_account_id), message)

    except Exception as e:
        await send_msg(f"⚠️ Ошибка: {str(e)}", get_back_kb("Попробовать снова", "copy_finisher_settings_from_username"),
                       message)
    finally:
        fms.reset_state(user_id)


async def finishers_work(app: Client):
    """
    Модуль для отправки добивающих сообщений.
    """

    while True:
        try:
            finishers = db.Finisher.get_by_account_id(app.me.id)

            if not finishers:
                await asyncio.sleep(60)

            async for dialog in app.get_dialogs():
                if dialog.chat.type != ChatType.PRIVATE:
                    continue

                top_message = dialog.top_message
                if not top_message:
                    continue

                days_since_last_message = (datetime.now() - top_message.date).days

                for finisher in finishers:
                    if dialog.chat.id in finisher.sent:
                        continue

                    if days_since_last_message < finisher.days_without_message:
                        continue

                    msg = await json_to_message(app, dialog.chat.id, finisher.message)
                    if msg:
                        chat_name = dialog.chat.username or dialog.chat.first_name or dialog.chat.title or dialog.chat.id
                        db.Analytics.create_record(
                            app.me.id,
                            'Доставил добивающее сообщение',
                            details=f"Кому: {chat_name}"
                        )

                    finisher.sent.append(dialog.chat.id)

                    db.Finisher.update_by_id(finisher.id, sent=finisher.sent)
                    break

                await asyncio.sleep(300)

        except FloodWait as e:
            await asyncio.sleep(e.value)
        except RPCError as e:
            await asyncio.sleep(60)
        except (AuthKeyUnregistered, SessionRevoked, UserDeactivated) as e:
            await modules.accounts_storage.de_launch_account(app.me.id)
            return
        except Exception as e:
            print(f"Finisher Unexpected error: {e}")
            await asyncio.sleep(60)


        await asyncio.sleep(300)
