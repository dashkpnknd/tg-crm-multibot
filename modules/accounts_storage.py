import asyncio

from pyrogram import Client, raw

from plugins.chat_sender import chat_sender_work
from plugins.finishers import finishers_work
from plugins.full_story_cloner import full_story_cloner_work
from plugins.sender import sender_work
from plugins.story_cloner import story_cloner_work
from modules import db
from plugins.story_reactions import story_reactions_work



active_clients = {}
active_tasks = {}


async def launch_account(account_id: int):
    """
    Запускает аккаунт по его ID.
    """
    existing_tasks = active_tasks.get(account_id, [])
    if account_id in active_clients and any(not task.done() for task in existing_tasks):
        return True, ''

    account = db.Account.get_by_id(account_id)
    config = account.config or {}
    proxy = config.get("proxy")
    PROXY_CONFIG = {
        "scheme": "http",       # Для порта 8000 обычно используется http
        "hostname": "196.18.9.158",
        "port": 8000,
        "username": "XApV9A",
        "password": "0Kgd3x"
    }
    try:
        app = Client(
            name=f'accounts/{account_id}',
            api_hash="<REDACTED>"
            api_id="<REDACTED>"
            device_model='Desktop',
            system_version="Windows 11",
            app_version='5.7.2 x64',
            lang_code='ru',
            lang_pack='tdesktop',
            system_lang_code='ru-RU',
            proxy=PROXY_CONFIG,
            no_updates=True
        )

        # Запускаем клиент
        await app.start()

        app.de_launch_account = de_launch_account
        active_clients[account_id] = app

        # Создаем задачи
        tasks = [
            asyncio.create_task(story_cloner_work(app)),
            asyncio.create_task(full_story_cloner_work(app)),
            asyncio.create_task(sender_work(app)),
            asyncio.create_task(finishers_work(app)),
            asyncio.create_task(story_reactions_work(app)),
            asyncio.create_task(chat_sender_work(app)),
        ]
        active_tasks[account_id] = tasks

        return True, ''

    except Exception as e:
        print(f"Ошибка при запуске аккаунта {account_id}: {e}")
        return False, str(e)

async def de_launch_account(account_id: int):
    account = db.Account.get_by_id(account_id)
    db.Account.update_by_id(account.id, is_started=False)

    tasks = active_tasks.pop(account_id, [])
    for task in tasks:
        if not task.done():
            task.cancel()

    app = active_clients.get(account_id)
    if app:
        del active_clients[account_id]
    else:
        return

    try:
        await app.stop()
    except Exception as e:
        print(f"Ошибка при выключении аккаунта {account_id}: {e}")


async def initialize_active_accounts():
    """
    Инициализирует все активные аккаунты после перезагрузки скрипта.
    """
    active_accounts = db.Account.get_all_started()
    for account in active_accounts:
        success = await launch_account(account.id)
        if not success:
            account.update_by_id(account.id, is_started=False)
            print(f"Не удалось запустить аккаунт {account.id} после перезагрузки")
