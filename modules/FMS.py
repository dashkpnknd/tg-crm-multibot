import sqlite3
from typing import Any, Dict, Optional, List, Union
import json


class SQLiteStorage:
    def __init__(self, db_path: str = "fsm.sqlite"):
        self.db_path = db_path
        self._conn = None
        self._init_db()

    def _init_db(self):
        """Инициализация базы данных."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fsm_data (
                user_id INTEGER PRIMARY KEY,
                state TEXT,
                data TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _get_connection(self):
        """Получение соединения с базой данных."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
        return self._conn

    def close(self) -> None:
        """Закрытие соединения с базой данных."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def set_state(self, user_id: int, state: Optional[str] = None) -> None:
        """
        Установка состояния для пользователя.
        :param user_id: ID пользователя.
        :param state: Новое состояние (если None, состояние сбрасывается).
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO fsm_data (user_id, state, data)
            VALUES (?, ?, COALESCE((SELECT data FROM fsm_data WHERE user_id = ?), '{}'))
        """, (user_id, state, user_id))
        conn.commit()

    def get_state(self, user_id: int) -> Optional[str]:
        """
        Получение текущего состояния пользователя.
        :param user_id: ID пользователя.
        :return: Текущее состояние или None, если состояние не установлено.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT state FROM fsm_data WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result and result[0] else None

    def set_data(self, user_id: int, data: Optional[Dict] = None) -> None:
        """
        Установка данных для пользователя.
        :param user_id: ID пользователя.
        :param data: Новые данные (если None, данные сбрасываются).
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO fsm_data (user_id, state, data)
            VALUES (?, COALESCE((SELECT state FROM fsm_data WHERE user_id = ?), ''), ?)
        """, (user_id, user_id, json.dumps(data or {})))
        conn.commit()

    def get_data(self, user_id: int) -> Dict:
        """
        Получение данных пользователя.
        :param user_id: ID пользователя.
        :return: Словарь с данными пользователя или пустой словарь, если данных нет.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM fsm_data WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return json.loads(result[0]) if result and result[0] else {}

    def update_data(self, user_id: int, data: Optional[Dict] = None, **kwargs) -> None:
        """
        Обновление данных пользователя.
        :param user_id: ID пользователя.
        :param data: Словарь с новыми данными (объединяется с существующими).
        :param kwargs: Дополнительные данные для обновления.
        """
        existing_data = self.get_data(user_id=user_id)
        if data:
            existing_data.update(data)
        existing_data.update(kwargs)
        self.set_data(user_id=user_id, data=existing_data)

    def reset_state(self, user_id: int) -> None:
        """
        Сброс состояния пользователя.
        :param user_id: ID пользователя.
        """
        self.set_state(user_id=user_id, state=None)

    def reset_data(self, user_id: int) -> None:
        """
        Сброс данных пользователя.
        :param user_id: ID пользователя.
        """
        self.set_data(user_id=user_id, data={})

    def get_all_users(self) -> dict[Any, Any]:
        """
        Получение списка всех пользователей.
        :return: Список ID пользователей.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, state FROM fsm_data")
        results = cursor.fetchall()
        return {x[0]: x[1] for x in results}

    def reset_all(self) -> None:
        """
        Сброс всех данных и состояний в базе данных.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fsm_data")
        conn.commit()


fms = SQLiteStorage()