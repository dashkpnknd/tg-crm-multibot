import base64
from asyncio.log import logger
from io import BytesIO
from typing import List, Union

from pyrogram import Client, enums
from pyrogram.types import InlineKeyboardMarkup, Message, InputMediaPhoto, InputMediaVideo, InputMediaAudio, \
    InputMediaDocument

from modules.FMS import fms


async def send_msg(text: str, keyboad: Union[InlineKeyboardMarkup, None], message: Message) -> Message:
    data = fms.get_data(message.chat.id)
    try:
        msg = await message._client.edit_message_text(chat_id=message.chat.id, message_id=data['msg_id'], text=text,
                                                      reply_markup=keyboad)
        if message.id != msg.id:
            try:
                await message.delete()
            except Exception as e:
                print(e)

    except Exception as e:
        print(e)

        msg = await message._client.send_message(message.chat.id, text,
                                                 reply_markup=keyboad)

        fms.update_data(user_id=message.chat.id, data={"msg_id": msg.id})
        try:
            await message.delete()
        except Exception as e:
            print(e)

    return msg

media_types = {
            'photo': 'file.jpg',
            'video': 'file.mp4',
            'audio': 'file.mp3',
            'document': 'file.docx',
            'voice': 'file.ogg',
            'video_note': 'file.mp4',
            'sticker': 'file.webp',
            'animation': 'file.tgs'
        }

async def messages_to_json(messages: List[Message]):
    result = {}

    for msg in messages:
        try:
            await msg.delete()
        except Exception as e:
            print(e)

        if msg.text:
            result['text'] = msg.text.html

        if msg.caption:
            result['text'] = msg.caption.html

        if msg.story:
            result['story'] = {"username": msg.story.chat.username, "id": msg.story.id}

        for media_type, key in media_types.items():
            if hasattr(msg, media_type) and getattr(msg, media_type):

                file = await msg.download(in_memory=True)
                file_data = base64.b64encode(file.getvalue()).decode('utf-8')

                media = getattr(msg, media_type)
                file_name = getattr(media, 'file_name', None)
                media_info = {'data': file_data, 'file_name': file_name if file_name else key}

                # Добавляем медиа в результат
                result.setdefault(media_type, []).append(media_info)

    return result



async def json_to_message(client: Client, chat: Union[int, str], message: dict):
    """
    Обрабатывает JSON-сообщение и отправляет его в указанный чат.
    """
    media_group_class = {
        'photo': InputMediaPhoto,
        'video': InputMediaVideo,
        'audio': InputMediaAudio,
        'document': InputMediaDocument,
    }
    msg = None

    single_media_types = ['voice', 'sticker', 'video_note', 'animation']

    text = message.get('text', '')

    async def decode_base64(data: str, extension: str):
        """Декодирует base64 и создает объект BytesIO."""
        try:
            file_bytes = BytesIO(base64.b64decode(data.encode('utf-8')))
            setattr(file_bytes, 'name', f'file.{extension}')
            return file_bytes
        except Exception as e:
            logger.error(f"Ошибка при декодировании base64: {e}")
            return None

    media = []
    for media_type, cl in media_group_class.items():
        for item in message.get(media_type, []):
            file_bytes = await decode_base64(item.get('data'), item.get('file_name'))
            if file_bytes:
                media.append(cl(media=file_bytes, caption=text if not media else ''))


    if media:
        try:
            msg = await client.send_media_group(chat, media=media)
            return
        except Exception as e:
            logger.error(f"Ошибка при отправке медиа-группы: {e}")

    for media_type in single_media_types:
        for item in message.get(media_type, []):
            file_bytes = await decode_base64(item.get('data'), item.get('file_name'))
            if file_bytes:
                try:
                    msg = await getattr(client, f'send_{media_type}')(chat, file_bytes)
                    return
                except Exception as e:
                    logger.error(f"Ошибка при отправке {media_type}: {e}")


    story = message.get('story')
    if story:
        try:
            story = await client.get_stories(story.get('username'), story.get('id'))
            await story.forward(chat)
            return
        except Exception as e:
            logger.error(f"Ошибка при отправке истории: {e}")

    if text:
        if text.startswith('https://t.me/') and len(text.split('/')) == 6:
            params = text.split('/')
            try:
                story = await client.get_stories(params[-3], int(params[-1]))
                await story.forward(chat)
            except Exception as e:
                logger.error(f"Ошибка при отправке истории: {e}")
        else:
            try:
                msg = await client.send_message(chat, text, parse_mode=enums.ParseMode.HTML)
            except Exception as e:
                logger.error(f"Ошибка при отправке текста: {e}")

    return msg