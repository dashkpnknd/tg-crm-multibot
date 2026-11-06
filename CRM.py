from runtime_config import BOT_TOKEN, BOT_API_HASH
import asyncio
import datetime
import logging

from pyrogram import Client, filters, enums, idle
from pyrogram.errors import UserIsBlocked
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

from modules.FMS import fms
from modules.accounts_storage import initialize_active_accounts, watch_external_accounts
from modules.filters import data_filter
from modules.message import send_msg
from modules import db, reporter
from plugins.accounts import get_accounts_kb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Client('bot',
             bot_token=BOT_TOKEN,
             api_hash=BOT_API_HASH,
             api_id=6,
             parse_mode=enums.ParseMode.HTML,
             # Load the known plugins explicitly.  The default recursive
             # scanner treats editor/backup files such as ``._foo.py`` or
             # ``foo.py.before-fix`` as importable plugins and can prevent
             # the whole CRM from starting.
             plugins=dict(root="plugins", include=[
                 "accounts", "add_account", "chat_sender", "chats",
                 "finishers", "full_story_cloner", "proxy",
                 "selected_story_cloner", "sender", "story_cloner",
                 "story_reactions",
             ]),
            )


def get_main_kb():
    keyboard = [
        [InlineKeyboardButton("Аккаунты", callback_data="accounts_")],
        [InlineKeyboardButton("Чаты", callback_data="chats_")],
    ]
    return InlineKeyboardMarkup(keyboard)


@bot.on_message(filters.command("start911"))
async def start_command(client: Client, message: Message):
    await send_msg("Главное меню:", get_main_kb(), message)
    fms.reset_state(message.from_user.id)


@bot.on_message(filters.command("set_report_channel"))
async def set_report_channel(client: Client, message: Message):
    owners = {account.owner for account in db.session.query(db.Account).all()}
    if owners and message.from_user.id not in owners:
        await message.reply("Нет доступа к настройке канала отчетов.")
        return

    if len(message.command) < 2:
        await message.reply("Отправьте команду так: /set_report_channel -1001234567890")
        return

    channel_id = message.command[1].strip()
    reporter.set_report_channel_id(channel_id)
    await message.reply("Канал отчетов сохранен. Проверьте, что бот добавлен в канал и может писать сообщения.")


@bot.on_callback_query(data_filter('main_menu'))
async def start_button(client: Client, callback_query: CallbackQuery):
    await send_msg("Главное меню:", get_main_kb(), callback_query.message)
    fms.reset_state(callback_query.from_user.id)

@bot.on_callback_query(data_filter('None'))
async def start_button(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()

async def update_messages():
    while True:
        now = datetime.datetime.now()
        if now.hour == 23 and now.minute == 59:
            all_users = fms.get_all_users()
            for user_id, state in all_users.items():
                if state == 'ban':
                    continue
                fms.reset_state(user_id)
                data = fms.get_data(user_id)
                try:
                    msg = await bot.send_message(
                        user_id,
                        'Добро пожаловать в CRM! \n\nВаши аккаунты:',
                        get_accounts_kb(user_id, 1),
                        disable_notification=True
                    )
                    fms.update_data(user_id=user_id, data={"msg_id": msg.id})
                    try:
                        await bot.delete_messages(chat_id=user_id, message_ids=data['msg_id'])
                    except Exception as e:
                        print(e)
                except UserIsBlocked:
                    fms.set_state(user_id, 'ban')
                except Exception as e:
                    print(e)

                await asyncio.sleep(1)

        await asyncio.sleep(60)


def start():
    loop = asyncio.get_event_loop()
    run = loop.run_until_complete

    while True:
        try:
            run(bot.start())
            reporter.set_report_client(bot, BOT_TOKEN)
            break
        except ConnectionError as e:
            logger.warning("Telegram connection failed while starting bot, retrying in 30 seconds: %s", e)
            run(asyncio.sleep(30))
    run(initialize_active_accounts())
    loop.create_task(watch_external_accounts())
    run(update_messages())
    run(idle())
    run(bot.stop())



if __name__ == "__main__":
    start()
