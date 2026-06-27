from pyrogram import Client

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
        in_memory=True
    )

app.run()