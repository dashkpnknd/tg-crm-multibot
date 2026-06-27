import base64
import re
import shutil
import struct
import tempfile
from pathlib import Path

from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded
from pyrogram.storage import FileStorage, MemoryStorage
from pyrogram.types import CallbackQuery, InlineKeyboardButton, Message, InlineKeyboardMarkup

from modules import db
from modules.filters import *
from modules.message import send_msg
from opentele.td import TDesktop

apps_buffer = {}
code_input_buffer = {}

def get_code_kb(user_id) -> InlineKeyboardMarkup:
    current_code = code_input_buffer.get(user_id, "")

    # Создание верхней строки с текущим вводом
    top_row = []

    for i in range(5):  # Предполагаем, что код состоит из 5 цифр
        top_row.append(InlineKeyboardButton(text=current_code[i] if i < len(current_code) else "❌", callback_data='None'))

    # Создание числовой клавиатуры
    numeric_keyboard = [
        [InlineKeyboardButton("1", callback_data="code_number_1"),
         InlineKeyboardButton("2", callback_data="code_number_2"),
         InlineKeyboardButton("3", callback_data="code_number_3")],
        [InlineKeyboardButton("4", callback_data="code_number_4"),
         InlineKeyboardButton("5", callback_data="code_number_5"),
         InlineKeyboardButton("6", callback_data="code_number_6")],
        [InlineKeyboardButton("7", callback_data="code_number_7"),
         InlineKeyboardButton("8", callback_data="code_number_8"),
         InlineKeyboardButton("9", callback_data="code_number_9")],
        [InlineKeyboardButton("◀️", callback_data="code_del"),
         InlineKeyboardButton("0", callback_data="code_number_0"),
         InlineKeyboardButton("✅" if len(current_code) == 5 else '☑️', callback_data="code_confirm" if len(current_code) == 5 else 'None')],
    ]

    down_row = [InlineKeyboardButton("Отмена ❌", callback_data="accounts_")]

    keyboard = InlineKeyboardMarkup([top_row, *numeric_keyboard, down_row])
    return keyboard

def get_back_kb(text, data):
    kb = [[InlineKeyboardButton(text, callback_data=data)]]
    return InlineKeyboardMarkup(kb)


def get_add_account_kb():
    kb = [
        [InlineKeyboardButton('По номеру телефона', callback_data='add_account_phone'),
         InlineKeyboardButton('Через Tdata', callback_data='add_account_tdata')],
        [InlineKeyboardButton('Отмена ❌', callback_data='accounts_')]
    ]
    return InlineKeyboardMarkup(kb)


@Client.on_callback_query(data_filter('add_account'))
async def add_account(client: Client, callback_query: CallbackQuery):
    kb = [
        [InlineKeyboardButton('С прокси', callback_data='add_account_with_proxy')],
        [InlineKeyboardButton('Без прокси', callback_data='add_account_no_proxy')],
        [InlineKeyboardButton('Отмена ❌', callback_data='accounts_')]
    ]
    fms.update_data(callback_query.from_user.id, {'proxy': None})

    await send_msg('Хотите использовать прокси?', InlineKeyboardMarkup(kb), callback_query.message)



@Client.on_callback_query(data_filter('add_account_with_proxy'))
async def add_account_with_proxy(client: Client, callback_query: CallbackQuery):
    fms.set_state(callback_query.from_user.id, 'wait_proxy')
    text = ("Введите прокси в формате:\n"
            "protocol://username:password@ip:port\n\n"
            "Поддерживаемые протоколы: http, socks4, socks5")
    await send_msg(text, get_back_kb('Отмена ❌', 'accounts_'), callback_query.message)


@Client.on_message(state_filter("wait_proxy"))
async def wait_proxy(client: Client, message: Message):
    user_id = message.from_user.id
    proxy_string = message.text

    try:
        # Парсим прокси
        protocol, rest = proxy_string.split("://")
        auth, address = rest.split("@")
        username, password = auth.split(":")
        ip, port = address.split(":")
        port = int(port)

        if protocol not in ["http", "socks4", "socks5"]:
            raise ValueError("Неподдерживаемый протокол")

        proxy = {
            "scheme": protocol,
            "hostname": ip,
            "port": port,
            "username": username,
            "password": password
        }

        # Проверяем прокси
        test_client = Client(
            name="test_proxy",
            api_id="<REDACTED>"
            api_hash="<REDACTED>"
            proxy=proxy,
            in_memory=True
        )

        await test_client.connect()
        await test_client.disconnect()

        fms.update_data(user_id, {'proxy': proxy})

        await send_msg('Выберите тип добавления:', get_add_account_kb(), message)

    except Exception as e:
        await send_msg(f"⚠️ Неверный формат прокси или прокси не работает: {str(e)}",
                       get_back_kb('Попробовать снова', 'add_account_with_proxy'), message)



@Client.on_callback_query(data_filter('add_account_no_proxy'))
async def add_account_no_proxy(client: Client, callback_query: CallbackQuery):
    await send_msg('Выберите тип добавления:', get_add_account_kb(), callback_query.message)


@Client.on_callback_query(data_filter('add_account_tdata'))
async def add_account_tdata(client: Client, callback_query: CallbackQuery):
    fms.set_state(callback_query.from_user.id, 'wait_tdata')
    await send_msg('Пришлите zip архив с папкой tdata внутри:', get_back_kb('Отмена ❌', 'accounts_') , callback_query.message)


tdata_media_group_ban = []


@Client.on_message(state_filter('wait_tdata'))
async def wait_tdata(client: Client, message: Message):

    data = fms.get_data(user_id=message.from_user.id)

    await message.delete()

    if not message.document or not message.document.file_name.endswith('.zip'):
        return

    await send_msg(f"Файл обрабатывается ...", None, message)

    with tempfile.TemporaryDirectory() as temp_dir:

        file_name = f'{message.id}_{message.chat.id}_{message.document.file_name}'

        file_path = await message.download(file_name=temp_dir + file_name)

        try:
            shutil.unpack_archive(file_path, extract_dir=temp_dir)
        except Exception as e:
            await send_msg(f"⚠️ Ошибка при распаковке архива: {str(e)}", get_back_kb('Назад 🔙', 'accounts_'), message)
            return

        tdata_folder = None
        for folder in Path(temp_dir).iterdir():
            if folder.is_dir() and folder.name.lower() == "tdata":
                tdata_folder = folder
                break

        if not tdata_folder:
            await send_msg(f"⚠️ В архиве не найдена папка tdata.", get_back_kb('Назад 🔙', 'accounts_'), message)
            return

        try:
            client_tdata = TDesktop(basePath=tdata_folder)
            account = client_tdata.mainAccount
        except Exception as e:
            await message.reply_text(f"⚠️ Ошибка чтения tdata: {str(e)}")
            return

        # Формируем строку для Pyrogram
        packed = struct.pack(
            ">BI?256sQ?",
            account.MainDcId,
            0,
            False,
            account.authKey.key,
            account.UserId or 9999,
            False
        )

        pyrogram_string = base64.urlsafe_b64encode(packed).decode().rstrip("=")

    app = Client(
        name=f'app',
        api_hash="<REDACTED>"
        api_id="<REDACTED>"
        device_model='Desktop',
        system_version="Windows 11",
        app_version='5.7.2 x64',
        lang_code='ru',
        lang_pack='tdesktop',
        system_lang_code='ru-RU',
        no_updates=True,
        session_string=pyrogram_string,
        in_memory=True,
        proxy=data.get('proxy')
    )

    try:
        await app.start()
        me = await app.get_me()
        string_session = await app.export_session_string()
        await string_to_sqlite(f"accounts/{me.id}", string_session)
        await app.stop()

        name = me.first_name + (me.last_name if me.last_name else '')
        account = db.Account.get_by_id(me.id)
        if account:
            db.Account.update_by_id(account.id, username=me.username, name=name)
            await send_msg('Аккаунт успешно переавторизован ✅', get_back_kb('Назад', f'accounts_'), message)
        else:
            db.Account.create(id=me.id,
                              owner_id=message.from_user.id,
                              username=me.username,
                              phone="<REDACTED>"
                              name=name,
                              config={'proxy': data.get('proxy')}
                              )
            await send_msg('Аккаунт успешно добавлен ✅', get_back_kb('Назад 🔙', f'accounts_'), message)

    except Exception as e:
        print(e)
        await send_msg('⚠️ Ошибка', get_back_kb('Назад 🔙', 'accounts_'), message)
        fms.reset_state(message.from_user.id)


@Client.on_callback_query(data_filter('add_account_phone'))
async def add_account_phone(client: Client, callback_query: CallbackQuery):
    data = fms.get_data(user_id=callback_query.from_user.id)

    app = Client(
        name='app',
        api_hash="<REDACTED>"
        api_id="<REDACTED>"
        device_model='Desktop',
        system_version="Windows 11",
        app_version='5.7.2 x64',
        lang_code='ru',
        lang_pack='tdesktop',
        system_lang_code='ru-RU',
        in_memory=True,
        proxy=data.get('proxy')
    )

    apps_buffer[callback_query.from_user.id] = app
    fms.set_state(callback_query.from_user.id, 'phone_number')
    await send_msg('Введите номер телефона:', get_back_kb('Отмена ❌', 'accounts_'), callback_query.message)


@Client.on_message(state_filter("phone_number"))
async def phone_number(client: Client, message: Message):
    user_id = message.from_user.id
    app = apps_buffer.get(user_id)
    if not app:
        await send_msg('⚠️ Ошибка', get_back_kb('Назад 🔙', 'accounts_'), message)
        fms.reset_state(user_id)
        return

    await app.connect()
    try:
        phone = "<REDACTED>"
        code_info = await app.send_code(phone_number=phone)
        app.phone_number = phone
        app.code_info = code_info

        await send_msg('Введите код: ', get_code_kb(message.from_user.id), message)
        code_input_buffer[message.from_user.id] = ""
        apps_buffer[message.from_user.id] = app
        fms.set_state(user_id, 'code')
    except Exception as e:
        print(e)
        await send_msg('⚠️ Ошибка', get_back_kb('Назад 🔙', 'accounts_'), message)
        fms.reset_state(message.from_user.id)


@Client.on_callback_query(data_filter_startswith("code_number_") & state_filter('code'))
async def code_number(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    current_code = code_input_buffer.get(user_id, "")

    if len(current_code) == 5:
        await callback_query.answer()
        return

    number = callback_query.data.split("_")[-1]
    current_code += number
    code_input_buffer[user_id] = current_code

    await send_msg('Введите код: ', get_code_kb(callback_query.from_user.id), callback_query.message)


@Client.on_callback_query(data_filter("code_del") & state_filter('code'))
async def code_del(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    current_code = code_input_buffer.get(user_id, "")

    if len(current_code) == 0:
        await callback_query.answer()
        return

    code_input_buffer[user_id] = current_code[:-1]

    await send_msg('Введите код: ', get_code_kb(callback_query.from_user.id), callback_query.message)


@Client.on_callback_query(data_filter("code_confirm") & state_filter('code'))
async def code_confirm(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    current_code = code_input_buffer.get(user_id, "")
    code_input_buffer.pop(user_id)

    app = apps_buffer.get(user_id)
    if not app:
        await send_msg('⚠️ Ошибка', get_back_kb('Назад 🔙', 'accounts_'), callback_query.message)
        fms.reset_state(user_id)
        return

    try:
        await app.sign_in(
            phone_number=app.phone_number,
            phone_code=current_code,
            phone_code_hash=app.code_info.phone_code_hash,
        )
        await app.initialize()
        me = await app.get_me()
        string_session = await app.export_session_string()
        await string_to_sqlite(f"accounts/{me.id}", string_session)
        name = me.first_name + (me.last_name if me.last_name else '')

        account = db.Account.get_by_id(me.id)
        if account:
            db.Account.update_by_id(account.id, username=me.username, name=name)
            await send_msg('Аккаунт успешно переавторизован ✅', get_back_kb('Назад 🔙', f'accounts_'), callback_query.message)
        else:
            data = fms.get_data(user_id=user_id)
            db.Account.create(id=me.id,
                              owner_id=callback_query.from_user.id,
                              username=me.username,
                              phone="<REDACTED>"
                              name=name,
                              config={'proxy': data.get('proxy')}
                              )
            await send_msg('Аккаунт успешно добавлен ✅', get_back_kb('Назад 🔙', f'accounts_'), callback_query.message)

        fms.reset_state(user_id)
        await app.stop()

    except SessionPasswordNeeded:
        await send_msg(f'Введите пароль:\n\nПодсказка: {await app.get_password_hint()}', get_back_kb('Отмена ❌', 'accounts_'), callback_query.message)
        fms.set_state(user_id, 'password')
        return

    except Exception as e:
        print(e)
        await send_msg('⚠️ Ошибка', get_back_kb('Назад 🔙', 'accounts_'), callback_query.message)
        fms.reset_state(user_id)
        return


async def string_to_sqlite(session_name, string_session):
    out_sql = FileStorage(session_name, Path())
    in_string = MemoryStorage('temp', string_session)
    await out_sql.open(), await in_string.open()
    auth_data = in_string.conn.execute('SELECT * FROM sessions').fetchone()
    out_sql.conn.execute('DELETE FROM sessions')
    out_sql.conn.execute('INSERT or REPLACE INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)', auth_data)
    await out_sql.save(), await out_sql.close(), await in_string.close()
    print('Saved string in', out_sql.database)


@Client.on_message(state_filter("password"))
async def password(client: Client, message: Message):
    user_id = message.from_user.id
    app = apps_buffer.get(user_id)
    if not app:
        await send_msg('⚠️ Ошибка', get_back_kb('Назад 🔙', 'accounts_'), message)
        fms.reset_state(user_id)
        return

    try:
        await app.check_password(message.text)
        await app.initialize()
        me = await app.get_me()
        string_session = await app.export_session_string()
        await string_to_sqlite(f"accounts/{me.id}", string_session)
        name = me.first_name + (me.last_name if me.last_name else '')

        account = db.Account.get_by_id(me.id)
        if account:
            db.Account.update_by_id(account.id, username=me.username, name=name)
            await send_msg('Аккаунт успешно переавторизован ✅', get_back_kb('Назад', f'accounts_'), message)
        else:
            data = fms.get_data(user_id=user_id)
            db.Account.create(id=me.id,
                              owner_id=message.from_user.id,
                              username=me.username,
                              phone="<REDACTED>"
                              name=name,
                              config={'proxy': data.get('proxy')}
                              )
            await send_msg('Аккаунт успешно добавлен ✅', get_back_kb('Назад 🔙', f'accounts_'), message)

        fms.reset_state(user_id)
        await app.stop()
    except Exception as e:
        print(e)
        await send_msg('⚠️ Ошибка', get_back_kb('Назад 🔙', 'accounts_'), message)
        fms.reset_state(user_id)