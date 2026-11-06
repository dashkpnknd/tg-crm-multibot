"""Durable exact-ID story publishing for accounts already owned by Multi CRM."""

from __future__ import annotations

import asyncio
import json
import random
import sqlite3
import time
from pathlib import Path

from pyrogram.errors import AuthKeyUnregistered, FloodWait, RPCError, SessionRevoked, UserDeactivated


DATABASE = Path(__file__).resolve().parent.parent / "database.db"
MAX_RETRIES = 5
MAX_NETWORK_BACKOFF_SECONDS = 60 * 60


def _requested_pins(job: sqlite3.Row) -> tuple[int, ...]:
    """Return every source story that the exact-ID job must retain on profile."""
    return tuple(dict.fromkeys(int(value) for value in json.loads(job["pinned_story_ids"] or "[]")))


def _connect() -> sqlite3.Connection:
    database = sqlite3.connect(DATABASE, timeout=30)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA busy_timeout=30000")
    return database


def _jobs(account_id: int) -> list[sqlite3.Row]:
    with _connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS selected_story_cloner (
                account_id INTEGER PRIMARY KEY, source_username TEXT NOT NULL,
                story_ids TEXT NOT NULL, pinned_story_ids TEXT NOT NULL DEFAULT '[]',
                interval_min_seconds INTEGER NOT NULL, interval_max_seconds INTEGER NOT NULL,
                publish_duration_hours INTEGER NOT NULL, completed_story_ids TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active', next_at INTEGER NOT NULL DEFAULT 0,
                retry_count INTEGER NOT NULL DEFAULT 0, last_error TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS selected_story_delivery (
                account_id INTEGER NOT NULL,
                source_username TEXT NOT NULL,
                source_story_id INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('reserved', 'published', 'uncertain', 'failed')),
                target_story_id INTEGER,
                detail TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(account_id, source_username, source_story_id)
            )
            """
        )
        return list(db.execute("SELECT * FROM selected_story_cloner WHERE account_id=? AND status='active'", (account_id,)))


def _update(account_id: int, **values: object) -> None:
    if not values:
        return
    columns = ", ".join(f"{key}=?" for key in values)
    with _connect() as db:
        db.execute(
            f"UPDATE selected_story_cloner SET {columns}, updated_at=CURRENT_TIMESTAMP WHERE account_id=?",
            (*values.values(), account_id),
        )


def _migrate_completed(job: sqlite3.Row) -> None:
    """Make historic successes immutable before the anti-duplicate worker runs."""
    completed = {int(value) for value in json.loads(job["completed_story_ids"] or "[]")}
    with _connect() as db:
        for story_id in completed:
            db.execute(
                """
                INSERT OR IGNORE INTO selected_story_delivery(
                    account_id, source_username, source_story_id, state, detail
                ) VALUES (?, ?, ?, 'published', 'migrated from completed_story_ids')
                """,
                (job["account_id"], job["source_username"], story_id),
            )


def _delivery_states(account_id: int, source_username: str) -> dict[int, str]:
    with _connect() as db:
        return {
            int(row["source_story_id"]): str(row["state"])
            for row in db.execute(
                "SELECT source_story_id, state FROM selected_story_delivery WHERE account_id=? AND source_username=?",
                (account_id, source_username),
            )
        }


def _delivery_records(account_id: int, source_username: str) -> dict[int, sqlite3.Row]:
    with _connect() as db:
        return {
            int(row["source_story_id"]): row
            for row in db.execute(
                "SELECT * FROM selected_story_delivery WHERE account_id=? AND source_username=?",
                (account_id, source_username),
            )
        }


def _reserve_delivery(account_id: int, source_username: str, story_id: int) -> bool:
    """Claim an ID before network I/O: never automatically send it twice."""
    with _connect() as db:
        result = db.execute(
            """
            INSERT OR IGNORE INTO selected_story_delivery(account_id, source_username, source_story_id, state)
            VALUES (?, ?, ?, 'reserved')
            """,
            (account_id, source_username, story_id),
        )
        return bool(result.rowcount)


def _finish_delivery(
    account_id: int, source_username: str, story_id: int, state: str, detail: str | None = None, target_story_id: int | None = None
) -> None:
    with _connect() as db:
        db.execute(
            """
            UPDATE selected_story_delivery
            SET state=?, detail=?, target_story_id=?, updated_at=CURRENT_TIMESTAMP
            WHERE account_id=? AND source_username=? AND source_story_id=?
            """,
            (state, detail, target_story_id, account_id, source_username, story_id),
        )


async def _ensure_pins(app, job: sqlite3.Row) -> tuple[bool, str | None]:
    """Explicitly pin and verify every selected story already sent by this job.

    ``send_story(pinned=True)`` alone was not dependable in the installed
    client build. Pinning an existing target ID is idempotent, so this can be
    retried after a transport failure without ever creating another story.
    """
    requested_pins = set(_requested_pins(job))
    if not requested_pins:
        return True, None
    records = _delivery_records(app.me.id, job["source_username"])
    targets = [
        int(records[story_id]["target_story_id"])
        for story_id in requested_pins
        if story_id in records
        and records[story_id]["state"] == "published"
        and records[story_id]["target_story_id"] is not None
    ]
    if not targets:
        return True, None
    async with app.story_api_lock:
        pinned_before = {story.id async for story in app.get_pinned_stories("me")}
        missing = [story_id for story_id in targets if story_id not in pinned_before]
        if not missing:
            return True, None
        await app.pin_chat_stories("me", missing)
        pinned_after = {story.id async for story in app.get_pinned_stories("me")}
    absent = [story_id for story_id in targets if story_id not in pinned_after]
    if absent:
        return False, "Telegram did not confirm pinning target stories " + ", ".join(map(str, absent))
    return True, None


async def selected_story_cloner_work(app) -> None:
    """Publish exactly one due selected story per pass, preserving its order."""
    while True:
        try:
            for job in _jobs(app.me.id):
                if int(job["next_at"] or 0) > int(time.time()):
                    continue
                _migrate_completed(job)
                pins_ready, pin_error = await _ensure_pins(app, job)
                if not pins_ready:
                    _update(
                        app.me.id, status="active", next_at=int(time.time()) + 300,
                        last_error=f"Pin verification retry: {pin_error}"[:500],
                    )
                    continue
                requested = [int(value) for value in json.loads(job["story_ids"])]
                deliveries = _delivery_states(app.me.id, job["source_username"])
                # All non-new states are deliberately excluded.  An ambiguous
                # timeout is safer as an operator-visible stop than a resend.
                remaining = [story_id for story_id in requested if story_id not in deliveries]
                if not remaining:
                    unresolved = [story_id for story_id, state in deliveries.items() if state != "published"]
                    _update(
                        app.me.id,
                        status="completed" if not unresolved else "paused",
                        last_error=None if not unresolved else "Есть неопределённые истории: " + ", ".join(map(str, unresolved)),
                        retry_count=0,
                    )
                    continue
                source = await app.get_users(job["source_username"])
                available = {story.id: story async for story in app.get_pinned_stories(source.id)}
                story_id = remaining[0]
                story = available.get(story_id)
                if not story:
                    _update(app.me.id, status="failed", last_error=f"Источник не отдаёт выбранную историю {story_id}")
                    continue
                file_id = getattr(getattr(story, "photo", None), "file_id", None) or getattr(
                    getattr(story, "video", None), "file_id", None
                )
                if not file_id:
                    _update(app.me.id, status="failed", last_error=f"У выбранной истории {story_id} нет поддерживаемого медиа")
                    continue
                if not _reserve_delivery(app.me.id, job["source_username"], story_id):
                    # Another worker/restart has already reserved this ID;
                    # continue on the next scheduler pass without publishing.
                    continue
                pins = set(_requested_pins(job))
                try:
                    async with app.story_api_lock:
                        sent = await app.send_story(
                            chat_id="me", media=file_id, caption=story.caption or "",
                            period=int(job["publish_duration_hours"]) * 3600,
                            pinned=story_id in pins, protect_content=False,
                        )
                except RPCError as error:
                    # Telegram explicitly rejected this upload before creating a
                    # story. File identifiers can expire between the source
                    # read and target publish, so retry with fresh bytes.
                    if "MEDIA_FILE_INVALID" not in str(error):
                        raise
                    suffix = ".mp4" if getattr(story, "video", None) else ".jpg"
                    fallback_path = Path("/tmp") / f"selected-story-{app.me.id}-{story_id}{suffix}"
                    try:
                        downloaded = await app.download_media(story, file_name=str(fallback_path))
                        if not downloaded:
                            raise RuntimeError("Telegram did not download source media")
                        async with app.story_api_lock:
                            sent = await app.send_story(
                                chat_id="me", media=str(downloaded), caption=story.caption or "",
                                period=int(job["publish_duration_hours"]) * 3600,
                                pinned=story_id in pins, protect_content=False,
                            )
                    finally:
                        fallback_path.unlink(missing_ok=True)
                except Exception as error:
                    _finish_delivery(app.me.id, job["source_username"], story_id, "uncertain", str(error)[:500])
                    _update(
                        app.me.id, status="paused",
                        last_error=f"История {story_id}: неопределённый результат; автоповтор выключен",
                    )
                    continue
                _finish_delivery(
                    app.me.id, job["source_username"], story_id, "published",
                    target_story_id=int(sent.id),
                )
                # Do not rely on the upload flag alone.  The next scheduler
                # pass verifies this again, and can safely retry pinning only.
                if story_id in pins:
                    pins_ready, pin_error = await _ensure_pins(app, job)
                    if not pins_ready:
                        _update(
                            app.me.id, status="active", next_at=int(time.time()) + 300,
                            last_error=f"Pin verification retry: {pin_error}"[:500],
                        )
                        continue
                published = [
                    story_id for story_id, state in _delivery_states(app.me.id, job["source_username"]).items()
                    if state == "published"
                ]
                next_at = 0
                if len(published) < len(requested):
                    next_at = int(time.time()) + random.randint(
                        int(job["interval_min_seconds"]), int(job["interval_max_seconds"])
                    )
                _update(
                    app.me.id, completed_story_ids=json.dumps(sorted(published)), next_at=next_at,
                    retry_count=0, last_error=None,
                )
        except FloodWait as error:
            _update(app.me.id, next_at=int(time.time()) + int(error.value), last_error=f"FloodWait: {error.value}s")
        except (AuthKeyUnregistered, SessionRevoked, UserDeactivated) as error:
            _update(app.me.id, status="failed", last_error=f"Авторизация аккаунта недействительна: {type(error).__name__}")
            return
        except (ConnectionError, OSError) as error:
            # These calls occur before a story is reserved/sent.  Retrying is
            # safe, but a temporary host or Telegram disconnect must not turn
            # a healthy queue into a permanently failed one.
            jobs = _jobs(app.me.id)
            for job in jobs:
                retries = min(int(job["retry_count"] or 0) + 1, MAX_RETRIES)
                delay = min(MAX_NETWORK_BACKOFF_SECONDS, 60 * (2 ** retries))
                _update(
                    app.me.id, status="active", retry_count=retries,
                    next_at=int(time.time()) + delay, last_error=f"Network retry in {delay}s: {error}"[:500],
                )
        except RPCError as error:
            # A Telegram RPC error while fetching the source is safe to retry
            # a few times.  Unlike a transport loss, leave it paused for
            # operator review once the bounded retry budget is exhausted.
            jobs = _jobs(app.me.id)
            for job in jobs:
                retries = int(job["retry_count"] or 0) + 1
                if retries >= MAX_RETRIES:
                    _update(app.me.id, status="paused", retry_count=retries, last_error=str(error)[:500])
                else:
                    _update(app.me.id, retry_count=retries, next_at=int(time.time()) + retries * 300, last_error=str(error)[:500])
        except Exception as error:
            # An unknown protocol/API failure must not become an endless
            # per-minute loop.  Keep diagnostic data and stop after the same
            # bounded retry budget as ordinary RPC failures.
            for job in _jobs(app.me.id):
                retries = int(job["retry_count"] or 0) + 1
                if retries >= MAX_RETRIES:
                    _update(app.me.id, status="failed", retry_count=retries, last_error=str(error)[:500])
                else:
                    _update(app.me.id, retry_count=retries, next_at=int(time.time()) + retries * 300, last_error=str(error)[:500])
        await asyncio.sleep(60)
