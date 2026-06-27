import asyncio
import html
import json
import logging
from pathlib import Path
from urllib import parse, request, error

from pyrogram.errors import FloodWait, RPCError

REPORT_CHANNEL_FILE = Path("report_channel.txt")

logger = logging.getLogger(__name__)
_report_client = None
_bot_token = None


def set_report_client(client, bot_token=None):
    global _report_client, _bot_token
    _report_client = client
    _bot_token = bot_token


def get_report_channel_id():
    try:
        value = REPORT_CHANNEL_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None

    return value or None


def set_report_channel_id(channel_id):
    REPORT_CHANNEL_FILE.write_text(str(channel_id).strip() + "\n", encoding="utf-8")


def format_account(account):
    if not account:
        return "unknown"

    username = f"@{account.username}" if account.username else None
    name = account.name or username or str(account.id)
    if username and username != name:
        return f"{html.escape(name)} ({html.escape(username)}, <code>{account.id}</code>)"
    return f"{html.escape(name)} (<code>{account.id}</code>)"


async def send_report(text):
    channel_id = get_report_channel_id()
    if not channel_id:
        return

    if _bot_token:
        ok, retry_after, message = await asyncio.to_thread(_send_via_bot_api, channel_id, text)
        if ok:
            return
        if retry_after:
            await asyncio.sleep(retry_after)
            await send_report(text)
            return
        logger.warning("Could not send report to %s via Bot API: %s", channel_id, message)
        return

    if not _report_client:
        return

    try:
        await _report_client.send_message(
            channel_id,
            text,
            disable_web_page_preview=True
        )
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await send_report(text)
    except RPCError as e:
        logger.warning("Could not send report to %s: %s", channel_id, e)
    except Exception as e:
        logger.warning("Unexpected report error: %s", e)


def queue_report(text):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Could not queue report without a running event loop")
        return

    loop.create_task(send_report(text))


def _send_via_bot_api(channel_id, text):
    url = f"https://api.telegram.org/bot{_bot_token}/sendMessage"
    payload = parse.urlencode({
        "chat_id": channel_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    try:
        with request.urlopen(url, data=payload, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(body)
        except json.JSONDecodeError:
            return False, None, body
    except Exception as exc:
        return False, None, str(exc)

    if result.get("ok"):
        return True, None, None

    retry_after = result.get("parameters", {}).get("retry_after")
    return False, retry_after, result.get("description", result)
