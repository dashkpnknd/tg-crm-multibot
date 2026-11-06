import datetime
import html
from typing import Optional, Type

from sqlalchemy import Column, Integer, String, JSON, Boolean, ForeignKey, create_engine, func, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

from modules import reporter

Base = declarative_base()


class Account(Base):
    __tablename__ = 'account'

    id = Column(Integer, primary_key=True)
    owner = Column(Integer, nullable=False)
    phone = Column(String)
    username = Column(String)
    name = Column(String)
    is_started = Column(Boolean, default=False)
    config = Column(JSON, default={})

    senders = relationship("Sender", order_by="Sender.id", back_populates="account", cascade="all, delete-orphan")
    full_story_cloners = relationship("FullStoryCloner", order_by="FullStoryCloner.id", back_populates="account", cascade="all, delete-orphan")
    finisher_messages = relationship("Finisher", order_by="Finisher.id",  back_populates="account", cascade="all, delete-orphan")
    analytics = relationship("Analytics", back_populates="account", cascade="all, delete-orphan")

    @staticmethod
    def get_by_owner(owner_id: int) -> list[Type['Account']]:
        """
        Возвращает все аккаунты, принадлежащие указанному владельцу.
        :param owner_id: ID владельца
        :return: Список объектов аккаунтов
        """
        session.expire_all()
        return session.query(Account).filter_by(owner=owner_id).all()

    @staticmethod
    def get_by_id(account_id: int) -> Optional['Account']:
        """
        Возвращает аккаунт по его ID.
        :param account_id: ID аккаунта
        :return: Объект аккаунта или None, если аккаунт не найден
        """
        session.expire_all()
        return session.query(Account).filter_by(id=account_id).first()

    @staticmethod
    def get_by_username(username: str) -> Optional['Account']:
        """
        Получает аккаунт по его username, игнорируя регистр.
        :param username: Username аккаунта
        :return: Объект аккаунта или None, если не найден
        """
        session.expire_all()
        a =session.query(Account).filter_by(username=username).first()

        return session.query(Account).filter_by(username=username).first()

    @staticmethod
    def get_all_started() -> list[Type['Account']]:
        """
        Возвращает все запущенные аккаунты.
        :return: Список объектов аккаунтов
        """
        session.expire_all()
        return session.query(Account).filter_by(is_started=True).all()

    @staticmethod
    def update_by_id(account_id: int, **kwargs) -> Type['Account']:
        """
        Обновляет аккаунт по его ID.
        :param account_id: ID аккаунта
        :param kwargs: Поля для обновления (например, username="new_username", config={"key": "value"})
        :return: Обновленный объект аккаунта
        """
        session.expire_all()
        account = session.query(Account).filter_by(id=account_id).first()
        if not account:
            raise ValueError(f"Аккаунт с ID '{account_id}' не найден.")

        try:
            for key, value in kwargs.items():
                if hasattr(account, key) and value is not None:
                    setattr(account, key, value)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка обновления аккаунта: {e}")

        return account

    @staticmethod
    def create(id: int, owner_id: int, username: str, phone: str, name: str, config: dict) -> 'Account':
        """
        Создает новый аккаунт и сохраняет его в базе данных.
        :param config:
        :param id: ID аккаунта
        :param owner_id: ID владельца аккаунта
        :param username: Уникальное имя пользователя
        :param phone: Номер телефона
        :param name: Имя аккаунта
        :return: Созданный объект аккаунта
        """

        existing_account = session.query(Account).filter_by(id=id).first()
        if existing_account:
            raise ValueError(f"Аккаунт с id '{id}' уже существует.")

        new_account = Account(
            id=id,
            owner=owner_id,
            username=username,
            phone=phone,
            name=name,
            config=config
        )
        try:
            session.add(new_account)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка создания аккаунта: {e}")
        return new_account

    @staticmethod
    def delete_by_id(account_id: int) -> bool:
        """
        Удаляет аккаунт по его ID.
        :param account_id: ID аккаунта для удаления
        :return: True, если аккаунт успешно удален, иначе False
        """
        session.expire_all()
        account = session.query(Account).filter_by(id=account_id).first()
        if not account:
            raise ValueError(f"Аккаунт с ID '{account_id}' не найден.")

        try:
            session.delete(account)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка удаления аккаунта: {e}")

        return True


class Sender(Base):
    __tablename__ = 'sender'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('account.id', ondelete='CASCADE'), nullable=False)  # Связь с аккаунтом
    messages = Column(JSON, nullable=False)  # JSON-поле для хранения сообщений
    interval = Column(Integer, nullable=False)  # Интервал отправки
    min_days = Column(Integer, nullable=False)  # Минимальное количество дней
    max_days = Column(Integer, nullable=False)  # Максимальное количество дней
    sent = Column(JSON, default=[])  # JSON-поле для хранения отправленных сообщений
    black_list = Column(JSON, default=[])  # JSON-поле для хранения отправленных сообщений

    # Связь с таблицей Account (один-ко-многим)
    account = relationship("Account", back_populates="senders")

    @staticmethod
    def create(account_id: int, messages: list, interval: int, min_days: int, max_days: int, black_list: list) -> 'Sender':
        """
        Создает нового отправителя и привязывает его к аккаунту.
        :param account_id: ID аккаунта
        :param messages: Список сообщений (JSON)
        :param interval: Интервал отправки
        :param min_days: Минимальное количество дней
        :param max_days: Максимальное количество дней
        :return: Созданный объект отправителя
        """
        if not messages or not isinstance(messages, list):
            raise ValueError("Сообщения должны быть представлены в виде непустого списка.")

        if interval <= 0 or min_days < 0 or max_days < 0 or min_days > max_days:
            raise ValueError("Неверные значения интервала или диапазона дней.")

        new_sender = Sender(
            account_id=account_id,
            messages=messages,
            interval=interval,
            min_days=min_days,
            max_days=max_days,
            black_list=black_list
        )

        try:
            session.add(new_sender)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка создания отправителя: {e}")

        return new_sender

    @staticmethod
    def get_by_account_id(account_id: int) -> list[Type['Sender']]:
        """
        Возвращает всех отправителей, привязанных к указанному аккаунту.
        :param account_id: ID аккаунта
        :return: Список объектов отправителей
        """
        session.expire_all()
        return session.query(Sender).filter_by(account_id=account_id).all()

    @staticmethod
    def update_by_id(sender_id: int, **kwargs) -> Type['Sender']:
        """
        Обновляет отправителя по его ID.
        :param sender_id: ID отправителя
        :param kwargs: Поля для обновления (например, messages=["new_message"], interval=10)
        :return: Обновленный объект отправителя
        """
        session.expire_all()
        sender = session.query(Sender).filter_by(id=sender_id).first()
        if not sender:
            raise ValueError(f"Отправитель с ID '{sender_id}' не найден.")

        try:
            for key, value in kwargs.items():
                if hasattr(sender, key) and value is not None:
                    setattr(sender, key, value)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка обновления отправителя: {e}")

        return sender

    @staticmethod
    def delete_by_id(sender_id: int) -> bool:
        """
        Удаляет отправителя по его ID.
        :param sender_id: ID отправителя
        :return: True, если отправитель успешно удален, иначе False
        """
        session.expire_all()
        sender = session.query(Sender).filter_by(id=sender_id).first()
        if not sender:
            raise ValueError(f"Отправитель с ID '{sender_id}' не найден.")

        try:
            session.delete(sender)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка удаления отправителя: {e}")

        return True


class FullStoryCloner(Base):
    __tablename__ = 'full_story_cloner'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('account.id', ondelete='CASCADE'), nullable=False)  # Связь с аккаунтом
    username = Column(String, nullable=False)
    interval = Column(Integer, nullable=False)
    is_copy_prohibited = Column(Boolean, nullable=False)
    publish_duration = Column(Integer, nullable=False)
    skip_stories_with_at = Column(Boolean, nullable=False)
    copied = Column(JSON, default=[])  # JSON-like string

    # Связь с таблицей Account
    account = relationship("Account", back_populates="full_story_cloners")

    @staticmethod
    def create(account_id: int, username: str, interval: int, is_copy_prohibited: bool,
               publish_duration: int, skip_stories_with_at: bool) -> 'FullStoryCloner':
        """
        Создает новый объект FullStoryCloner и сохраняет его в базе данных.
        :param account_id: ID аккаунта
        :param username: Имя пользователя
        :param interval: Интервал
        :param is_copy_prohibited: Флаг запрета копирования
        :param publish_duration: Длительность публикации
        :param skip_stories_with_at: Флаг пропуска историй с упоминаниями
        :return: Созданный объект FullStoryCloner
        """
        if not username:
            raise ValueError("Имя пользователя не может быть пустым.")

        new_full_story_cloner = FullStoryCloner(
            account_id=account_id,
            username=username,
            interval=interval,
            is_copy_prohibited=is_copy_prohibited,
            publish_duration=publish_duration,
            skip_stories_with_at=skip_stories_with_at,
        )

        try:
            session.add(new_full_story_cloner)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка создания FullStoryCloner: {e}")

        return new_full_story_cloner

    @staticmethod
    def get_by_account_id(account_id: int) -> list[Type["FullStoryCloner"]]:
        """
        Возвращает все объекты FullStoryCloner, привязанные к указанному аккаунту.
        :param account_id: ID аккаунта
        :return: Список объектов FullStoryCloner
        """
        session.expire_all()
        return session.query(FullStoryCloner).filter_by(account_id=account_id).all()

    @staticmethod
    def update_by_id(full_story_cloner_id: int, **kwargs) -> Type['FullStoryCloner']:
        """
        Обновляет объект FullStoryCloner по его ID.
        :param full_story_cloner_id: ID объекта FullStoryCloner
        :param kwargs: Поля для обновления
        :return: Обновленный объект FullStoryCloner
        """
        session.expire_all()
        full_story_cloner = session.query(FullStoryCloner).filter_by(id=full_story_cloner_id).first()
        if not full_story_cloner:
            raise ValueError(f"Объект FullStoryCloner с ID '{full_story_cloner_id}' не найден.")

        try:
            for key, value in kwargs.items():
                if hasattr(full_story_cloner, key) and value is not None:
                    setattr(full_story_cloner, key, value)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка обновления FullStoryCloner: {e}")

        return full_story_cloner

    @staticmethod
    def delete_by_id(full_story_cloner_id: int) -> bool:
        """
        Удаляет объект FullStoryCloner по его ID.
        :param full_story_cloner_id: ID объекта FullStoryCloner
        :return: True, если объект успешно удален, иначе False
        """
        session.expire_all()
        full_story_cloner = session.query(FullStoryCloner).filter_by(id=full_story_cloner_id).first()
        if not full_story_cloner:
            raise ValueError(f"Объект FullStoryCloner с ID '{full_story_cloner_id}' не найден.")

        try:
            session.delete(full_story_cloner)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка удаления FullStoryCloner: {e}")

        return True


class Finisher(Base):
    __tablename__ = 'finisher'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('account.id', ondelete='CASCADE'), nullable=False)  # Каскадная связь
    message = Column(JSON, nullable=False)
    days_without_message = Column(Integer, nullable=False)
    sent = Column(JSON, default=[])

    # Связь с таблицей Account
    account = relationship("Account", back_populates="finisher_messages")

    @staticmethod
    def create(account_id: int, message: dict, days_without_message: int, sent: list = None) -> 'Finisher':
        """
        Создает новый объект FinisherMessage и сохраняет его в базе данных.
        :param account_id: ID аккаунта
        :param message: JSON-сообщение
        :param days_without_message: Количество дней после последнего сообщения
        :param sent: Список отправленных сообщений (по умолчанию пустой список)
        :return: Созданный объект FinisherMessage
        """
        if not message:
            raise ValueError("Сообщение не может быть пустым.")

        new_finisher_message = Finisher(
            account_id=account_id,
            message=message,
            days_without_message=days_without_message,
            sent=sent or [],
        )

        try:
            session.add(new_finisher_message)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка создания FinisherMessage: {e}")

        return new_finisher_message

    @staticmethod
    def delete_by_id(finisher_id: int) -> bool:
        """
        Удаляет объект FinisherMessage по его ID.
        :param finisher_id: ID объекта FinisherMessage
        :return: True, если объект успешно удален, иначе False
        """
        session.expire_all()
        finisher_message = session.query(Finisher).filter_by(id=finisher_id).first()
        if not finisher_message:
            raise ValueError(f"Объект FinisherMessage с ID '{finisher_id}' не найден.")

        try:
            session.delete(finisher_message)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка удаления FinisherMessage: {e}")

        return True

    @staticmethod
    def update_by_id(finisher_id: int, **kwargs) -> Type['Finisher']:
        """
        Обновляет объект Finisher по его ID.
        :param finisher_id: ID объекта FinisherMessage
        :param kwargs: Поля для обновления
        :return: Обновленный объект FinisherMessage
        """
        session.expire_all()
        finisher_message = session.query(Finisher).filter_by(id=finisher_id).first()
        if not finisher_message:
            raise ValueError(f"Объект FinisherMessage с ID '{finisher_id}' не найден.")

        try:
            for key, value in kwargs.items():
                if hasattr(finisher_message, key) and value is not None:
                    setattr(finisher_message, key, value)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка обновления FinisherMessage: {e}")

        return finisher_message

    @staticmethod
    def get_by_account_id(account_id: int) -> list[Type['Finisher']]:
        """
        Возвращает все объекты Finisher, привязанные к указанному аккаунту.
        :param account_id: ID аккаунта
        :return: Список объектов FinisherMessage
        """
        session.expire_all()
        return session.query(Finisher).filter_by(account_id=account_id).all()

    @staticmethod
    def get_by_id(finisher_id: int) -> Type['Finisher']:
        """
        Возвращает объект Finisher по его ID.
        :param finisher_id: ID объекта FinisherMessage
        :return: Объект FinisherMessage
        :raises ValueError: Если объект с указанным ID не найден
        """
        session.expire_all()  # Обновляем состояние сессии
        finisher_message = session.query(Finisher).filter_by(id=finisher_id).first()

        if not finisher_message:
            raise ValueError(f"Объект FinisherMessage с ID '{finisher_id}' не найден.")

        return finisher_message


class Chats(Base):
    __tablename__ = 'chats'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String)
    title = Column(String)

    @staticmethod
    def create(username: str, title: str) -> 'Chats':
        """
        Создает новую запись чата.
        :param username: Имя пользователя (или имя чата в Telegram)
        :param title: Название чата
        :return: Объект созданного чата
        """
        if not username or not title:
            raise ValueError("Поля username и title не могут быть пустыми.")

        new_chat = Chats(
            username=username,
            title=title
        )
        try:
            session.add(new_chat)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка создания чата: {e}")
        return new_chat

    @staticmethod
    def delete_by_id(chat_id: int) -> bool:
        """
        Удаляет чат по его ID.
        :param chat_id: ID чата
        :return: True, если удаление прошло успешно
        """
        chat = session.query(Chats).filter_by(id=chat_id).first()
        if not chat:
            raise ValueError(f"Чат с ID '{chat_id}' не найден.")
        try:
            session.delete(chat)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка удаления чата: {e}")
        return True

    @staticmethod
    def get_by_id(chat_id: int) -> Optional['Chats']:
        """
        Получает чат по его ID.
        :param chat_id: ID чата
        :return: Объект чата или None, если не найден
        """
        session.expire_all()
        return session.query(Chats).filter_by(id=chat_id).first()



    @staticmethod
    def get_all() -> list[Type['Chats']]:
        """
        Возвращает список всех чатов.
        :return: Список объектов чатов
        """
        session.expire_all()
        return session.query(Chats).all()

    @staticmethod
    def update_by_id(chat_id: int, **kwargs) -> Type['Chats']:
        """
        Обновляет данные чата по его ID.
        :param chat_id: ID чата
        :param kwargs: Поля для обновления (например, username="new_username", title="New Title")
        :return: Обновленный объект чата
        """
        chat = session.query(Chats).filter_by(id=chat_id).first()
        if not chat:
            raise ValueError(f"Чат с ID '{chat_id}' не найден.")
        try:
            for key, value in kwargs.items():
                if hasattr(chat, key) and value is not None:
                    setattr(chat, key, value)
            session.commit()
        except Exception as e:
            session.rollback()
            raise ValueError(f"Ошибка обновления чата: {e}")
        return chat


class Analytics(Base):
    __tablename__ = 'analytics'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('account.id', ondelete='CASCADE'), nullable=False)
    action = Column(String(50), nullable=False)  # Например: "login", "post_created", "chat_joined"
    time = Column(DateTime, nullable=False)  # Время в формате timestamp

    # Связь с моделью Accounts
    account = relationship("Account", back_populates="analytics")

    @staticmethod
    def create_record(account_id: int, action: str, details: str = None) -> 'Analytics':
        """
        Создает новую запись аналитики
        :param account_id: ID аккаунта
        :param action: Тип действия
        :return: Созданный объект аналитики
        """
        session.expire_all()
        record = Analytics(account_id=account_id, action=action, time=datetime.datetime.now())
        session.add(record)
        session.commit()
        account = session.query(Account).filter_by(id=account_id).first()
        report_text = (
            "<b>Действие бота</b>\n"
            f"Аккаунт: {reporter.format_account(account)}\n"
            f"Действие: {html.escape(action)}"
        )
        if details:
            report_text += f"\n{html.escape(details)}"
        reporter.queue_report(report_text)
        return record

    @staticmethod
    def get_by_account(account_id: int) -> list[Type["Analytics"]]:
        """
        Возвращает все записи аналитики для конкретного аккаунта
        :param account_id: ID аккаунта
        :return: Список записей аналитики
        """
        session.expire_all()
        return session.query(Analytics).filter_by(account_id=account_id).all()

    @staticmethod
    def get_all_records() -> list[Type["Analytics"]]:
        """Возвращает все записи аналитики"""
        session.expire_all()
        return session.query(Analytics).all()


# Настройка базы данных
engine = create_engine('sqlite:///database.db', connect_args={'timeout': 30})
with engine.connect() as connection:
    connection.exec_driver_sql('PRAGMA journal_mode=WAL')
    connection.exec_driver_sql('PRAGMA busy_timeout=30000')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()
