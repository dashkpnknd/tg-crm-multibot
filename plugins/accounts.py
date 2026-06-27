from collections import defaultdict
from io import BytesIO
from math import ceil

from openpyxl.workbook import Workbook
from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from modules import db
from modules.accounts_storage import launch_account, de_launch_account
from modules.filters import *
from modules.message import send_msg


def format_account_button(account: db.Account):
    name = account.name or str(account.id)
    if account.username:
        return f"{name} (@{account.username})"
    return f"{name} ({account.id})"


def get_accounts_kb(user_id, page, accounts_per_page=10):
    # Получаем все аккаунты пользователя
    accounts = db.Account.get_by_owner(user_id)
    total_accounts = len(accounts)

    # Вычисляем общее количество страниц
    total_pages = ceil(total_accounts / accounts_per_page)

    # Ограничиваем номер страницы допустимыми значениями
    page = max(1, min(page, total_pages))

    # Разбиваем аккаунты на страницы
    start_index = (page - 1) * accounts_per_page
    end_index = start_index + accounts_per_page
    accounts_on_page = accounts[start_index:end_index]

    # Формируем клавиатуру для текущей страницы
    keyboard = []
    for account in accounts_on_page:
        keyboard.append(
            [
                InlineKeyboardButton(format_account_button(account), callback_data=f"account_{account.id}"),
                InlineKeyboardButton('🌐', url=f"https://t.me/{account.username}"),
            ]
        )

    # Добавляем кнопки пагинации
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"accounts_{page - 1}"))
    if page < total_pages:
        pagination_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"accounts_{page + 1}"))

    if pagination_buttons:
        keyboard.append(pagination_buttons)

    # Добавляем кнопку "Добавить аккаунт"
    keyboard.append([InlineKeyboardButton("Добавить аккаунт ➕", callback_data="add_account")])
    keyboard.append([InlineKeyboardButton("Массовая настройка ⚙️", callback_data="bulk_settings")])
    keyboard.append([InlineKeyboardButton("Главное меню 🔙", callback_data="main_menu")])

    return InlineKeyboardMarkup(keyboard)



@Client.on_callback_query(data_filter_startswith('accounts_'))
async def accounts(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)

    try:
        accounts_page = int(callback_query.data.split('_')[1])
    except (IndexError, ValueError):
        accounts_page = data.get('accounts_page', 1)

    fms.update_data(user_id, {'accounts_page': accounts_page, 'proxy': None})
    fms.reset_state(user_id)

    await send_msg(
        'Добро пожаловать в CRM! \n\nВаши аккаунты:',
        get_accounts_kb(user_id, accounts_page),
        callback_query.message
    )


def get_account_kb(account: db.Account):

    keyboard = [
        [InlineKeyboardButton("Включено ✅" if account.is_started else 'Выключено ❌', callback_data="stop_account" if account.is_started else 'start_account')],
        [InlineKeyboardButton("Клонирование историй 📱", callback_data="story_cloner")],
        [InlineKeyboardButton("Полное клонирование историй 📲", callback_data="full_story_cloner")],
        [InlineKeyboardButton("Рассылка по ЛС ✉️", callback_data="sender")],
        [InlineKeyboardButton("Рассылка по чатам ✉️", callback_data="chat_sender")],
        [InlineKeyboardButton("Добивающие сообщения 🔔", callback_data="finishers")],
        [InlineKeyboardButton("Реакции на истории ❤️", callback_data="story_reactions")],
        [InlineKeyboardButton("Прокси 🌐", callback_data="proxy")],
        [InlineKeyboardButton("Статистика 📊", callback_data="stats")],

        [InlineKeyboardButton("Переавторизовать 🔑", callback_data="add_account")],
        [InlineKeyboardButton("Удалить 🗑️", callback_data="delete_account")],
        [InlineKeyboardButton("Назад ◀️", callback_data="accounts_")]
    ]

    return InlineKeyboardMarkup(keyboard)

async def show_account(account_id, message):
    account = db.Account.get_by_id(account_id)

    text = f'''Статус: <b>{'Включён ✅' if account.is_started else 'Выключен ❌'}</b>
    
⚠️ Если аккаунт выключен, функции не будут работать!

Настройки аккаунта: <b>{account.name}</b>
        '''
    await send_msg(text, get_account_kb(account), message)


@Client.on_callback_query(data_filter_startswith('account_'))
async def open_account(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    fms.reset_state(user_id)
    try:
        account_id = int(callback_query.data.split('_')[1])
    except (IndexError, ValueError):
        account_id = data.get('open_account')

    fms.update_data(user_id, {'open_account': account_id})
    fms.reset_state(user_id)

    await show_account(account_id, callback_query.message)

@Client.on_callback_query(data_filter('stats'))
async def stats_account(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')

    analytics_records = db.Analytics.get_by_account(account_id)

    grouped_data = defaultdict(lambda: defaultdict(int))
    all_actions = set()

    for record in analytics_records:
        date = record.time.date()
        action = record.action
        grouped_data[date][action] += 1
        all_actions.add(action)

    workbook = Workbook()
    sheet = workbook.active
    account = db.Account.get_by_id(account_id)
    sheet.title = f"{account.username}" if account else f"Account {account_id}"

    # Записываем заголовки
    headers = ["Date"] + sorted(all_actions)
    sheet.append(headers)

    # Заполняем данные
    for date, actions in sorted(grouped_data.items()):
        row = [date]
        for action in sorted(all_actions):
            count = actions.get(action, 0)
            row.append(count)
        sheet.append(row)

    # Сохраняем в байтовый поток
    byte_io = BytesIO()
    workbook.save(byte_io)
    byte_io.seek(0)
    byte_io.name = 'Статистика.xlsx'

    await callback_query.message.reply_document(document=byte_io)


@Client.on_callback_query(data_filter('start_account'))
async def start_account(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)

    if account.is_started:
        await callback_query.answer('Аккаунт уже запущен ✅', show_alert=True)

    success, info = await launch_account(account_id)
    if success:
        db.Account.update_by_id(account_id, is_started=True)
        await callback_query.answer('Аккаунт запущен ✅', show_alert=True)
        await show_account(account_id, callback_query.message)
    else:

        if 'proxy' in info:
            info = 'Ошибка прокси 🌐'

        if '401' in info:
            info = "требуется переавторизация 🔑"

        await callback_query.answer(f'Ошибка запуска аккаунта: {info}', show_alert=True)


@Client.on_callback_query(data_filter('stop_account'))
async def stop_account(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    await de_launch_account(account_id)
    await callback_query.answer('Аккаунт выключен ❌', show_alert=True)
    await show_account(account_id, callback_query.message)


@Client.on_callback_query(data_filter('delete_account'))
async def delete_account(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    state = fms.get_state(user_id)
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    accounts_page = data.get('accounts_page')
    account = db.Account.get_by_id(account_id)
    if account.is_started:
        await callback_query.answer('⚠️ Для удаления выключите аккаунт!', show_alert=True)
        return

    if state == 'delete_account':
        db.Account.delete_by_id(account_id)
        await send_msg(
            'Ваши аккаунты:',
            get_accounts_kb(user_id, accounts_page),
            callback_query.message
        )
    else:
        await callback_query.answer('⚠️ Что бы подтвердить удаление нажми ещё раз', show_alert=True)
        fms.set_state(user_id, 'delete_account')


