from runtime_config import ACCOUNT_API_HASH
from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from modules.FMS import fms
from modules.filters import data_filter, state_filter
from modules.message import send_msg
from modules import db
from plugins.add_account import get_back_kb


def get_proxy_kb(proxy):
    if proxy:
        action_buttons = [
            [InlineKeyboardButton("Изменить 🔧", callback_data="set_proxy")],
            [InlineKeyboardButton("Удалить ❌", callback_data="delete_proxy")]
        ]
    else:
        action_buttons = [
            [InlineKeyboardButton("Установить 🌐", callback_data="set_proxy")]
        ]
    keyboard = [
        *action_buttons,
        [InlineKeyboardButton("Назад ◀️", callback_data="account_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_text(proxy):
    if proxy:
        proxy_status = f"Установлен ✅\n\n<pre>{proxy['scheme']}://{proxy['username']}:{proxy['password']}@{proxy['hostname']}:{proxy['port']}</pre>"
    else:
        proxy_status = "Не установлен ❌"

    info = '\n\n⚠️ После любых изменений в прокси нужна перезагрузка аккаунта'
    return "Настройки прокси:\n\n"+proxy_status+info

@Client.on_callback_query(data_filter('proxy'))
async def proxy(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    proxy = config.get("proxy")


    await send_msg(get_text(proxy), get_proxy_kb(proxy), callback_query.message)


@Client.on_callback_query(data_filter('set_proxy'))
async def set_proxy(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    fms.set_state(user_id, 'wait_proxy_input')
    text = ("Введите прокси в формате:\n"
            "protocol://username:password@ip:port\n\n"
            "Поддерживаемые протоколы: http, socks4, socks5")
    await send_msg(text, get_back_kb('Отмена ❌', 'proxy'), callback_query.message)


@Client.on_message(state_filter("wait_proxy_input"))
async def wait_proxy_input(client: Client, message: Message):
    user_id = message.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)

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
            api_id=2040,
            api_hash=ACCOUNT_API_HASH,
            proxy=proxy,
            in_memory=True
        )

        await test_client.connect()
        await test_client.disconnect()

        # Если проверка прошла успешно, сохраняем прокси
        config = account.config or {}
        config["proxy"] = proxy
        db.Account.update_by_id(account_id, config=config)
        fms.reset_state(user_id)
        await send_msg(get_text(proxy), get_proxy_kb(proxy), message)

    except Exception as e:
        await send_msg(f"⚠️ Неверный формат прокси или прокси не работает: {str(e)}",
                       get_back_kb('Попробовать снова', 'set_proxy'), message)


@Client.on_callback_query(data_filter('delete_proxy'))
async def delete_proxy(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = fms.get_data(user_id)
    account_id = data.get('open_account')
    account = db.Account.get_by_id(account_id)

    config = account.config or {}
    if "proxy" in config:
        del config["proxy"]
        db.Account.update_by_id(account_id, config=config)
        await send_msg(get_text(None), get_proxy_kb(None), callback_query.message)
    else:
        await send_msg("Прокси не был установлен.", get_proxy_kb(None), callback_query.message)