from math import ceil

from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from modules import db
from modules.filters import *
from modules.message import send_msg
from plugins.add_account import get_back_kb


def get_chats_kb(page, chats_per_page=10):
    # Получаем все чаты пользователя
    chats = db.Chats.get_all()

    # Вычисляем общее количество страниц
    total_pages = ceil(len(chats) / chats_per_page)

    # Ограничиваем номер страницы допустимыми значениями
    page = max(1, min(page, total_pages))

    # Разбиваем чаты на страницы
    start_index = (page - 1) * chats_per_page
    end_index = start_index + chats_per_page
    chats_on_page = chats[start_index:end_index]

    # Формируем клавиатуру для текущей страницы
    keyboard = []
    for chat in chats_on_page:
        keyboard.append(
            [
                InlineKeyboardButton(chat.title, callback_data=f"delete_chat_{chat.id}"),
                InlineKeyboardButton('🌐', url=f"https://t.me/{chat.username}"),
            ]
        )

    # Добавляем кнопки пагинации
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"chats_{page - 1}"))
    if page < total_pages:
        pagination_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"chats_{page + 1}"))

    if pagination_buttons:
        keyboard.append(pagination_buttons)

    # Добавляем кнопку "Добавить чат"
    keyboard.append([InlineKeyboardButton("Добавить чат ➕", callback_data="add_chat")])
    keyboard.append([InlineKeyboardButton("Главное меню 🔙", callback_data="main_menu")])

    return InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(data_filter_startswith('chats_'))
async def chats(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id

    try:
        chats_page = int(callback_query.data.split('_')[1])
    except (IndexError, ValueError):
        chats_page = 1

    fms.update_data(user_id, {"chats_page": chats_page})

    await send_msg(
        'Список ваших чатов:',
        get_chats_kb(chats_page),
        callback_query.message
    )


@Client.on_callback_query(data_filter('add_chat'))
async def add_chat(client: Client, callback_query: CallbackQuery):
    fms.set_state(callback_query.from_user.id, 'wait_chat_username')
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    chats_page = data.get('chats_page')

    await send_msg(
        'Введите username чата, который хотите добавить:',
        get_back_kb('Отмена ❌', f'chats_{chats_page}'),
        callback_query.message
    )


@Client.on_message(state_filter("wait_chat_username"))
async def wait_chat_username(client: Client, message: Message):
    user_id = message.from_user.id

    data = fms.get_data(user_id)
    chats_page = data.get('chats_page')
    
    text = message.text
    text.replace('@', '')
    usernames = message.text.strip().split('\n')

    for x in usernames:
        db.Chats.create(username=x, title=x)

    await send_msg(
        'Ваши чаты:',
        get_chats_kb(chats_page),
        message
    )

    fms.reset_state(user_id)




@Client.on_callback_query(data_filter_startswith('delete_chat_'))
async def delete_chat(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    chat_id = "<REDACTED>"
    chats_page = data.get('chats_page')

    if not chat_id:
        await callback_query.answer("⚠️ Не удалось определить чат для удаления", show_alert=True)
        return

    state = fms.get_state(user_id)

    if state == 'delete_chat':
        db.Chats.delete_by_id(chat_id)
        await send_msg(
            'Ваши чаты:',
            get_chats_kb(chats_page),
            callback_query.message
        )
        fms.reset_state(user_id)
    else:
        await callback_query.answer('⚠️ Чтобы подтвердить удаление нажми ещё раз', show_alert=True)
        fms.set_state(user_id, 'delete_chat')