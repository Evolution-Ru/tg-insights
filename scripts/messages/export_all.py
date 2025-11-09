#!/usr/bin/env python3
"""
Экспорт всех Telegram-диалогов в SQLite базу данных.

Автоматически обходит все доступные диалоги и сохраняет сообщения.
Большие группы (> max-group-size участников) пропускаются.

Environment (из accounts/{account}/.env):
- TELEGRAM_API_ID
- TELEGRAM_API_HASH  
- TELEGRAM_SESSION_STRING or TELEGRAM_SESSION_NAME

Usage:
  python export_all.py --account ychukaev
  python export_all.py --account ychukaev --max-group-size 50
  python export_all.py --account ychukaev --from 2025-01-01
"""

import asyncio
import os
from dotenv import load_dotenv
import sys
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from telethon import TelegramClient, utils
from telethon.tl.types import PeerChannel, PeerChat, User, Chat, Channel
from telethon.sessions import StringSession
from telethon.tl import functions


# -------------------------
# Account Management
# -------------------------


def load_account_env(account_name: str) -> None:
    """Load environment variables from account-specific .env file"""
    current_dir = Path(__file__).resolve().parent  # scripts/messages/
    env_path = current_dir.parent.parent / "accounts" / account_name / ".env"  # ../../accounts/{account}/.env
    
    if not env_path.exists():
        raise SystemExit(f"Environment file not found: {env_path}")
    
    print(f"Loading environment from: {env_path}")
    load_dotenv(env_path)


# -------------------------
# Date parsing
# -------------------------


def parse_flexible_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD, DD.MM.YYYY, or DD MM YYYY"""
    date_str = date_str.strip()
    
    # YYYY-MM-DD
    for fmt in ["%Y-%m-%d", "%d.%m.%Y", "%d %m %Y"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    raise ValueError(f"Cannot parse date: {date_str}. Use YYYY-MM-DD, DD.MM.YYYY, or DD MM YYYY")


# -------------------------
# Database setup
# -------------------------


def ensure_db(conn: sqlite3.Connection) -> None:
    """Create messages and users tables if they don't exist"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            date TEXT,
            direction TEXT,
            text TEXT,
            from_id INTEGER,
            json TEXT,
            PRIMARY KEY (chat_id, message_id)
        )
        """
    )
    
    # Create users table with extended schema (compatible with update_users_via_telethon)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            type TEXT,
            name TEXT,
            username TEXT,
            phone TEXT,
            first_name TEXT,
            last_name TEXT,
            about TEXT,
            is_bot INTEGER,
            verified INTEGER,
            last_updated_at TEXT
        )
        """
    )
    
    # Migrate old columns if they exist
    cur = conn.execute("PRAGMA table_info(users);")
    existing_cols = {row[1] for row in cur.fetchall()}
    
    # Add missing columns
    required_columns = [
        ("type", "TEXT"),
        ("name", "TEXT"),
        ("about", "TEXT"),
        ("is_bot", "INTEGER"),
        ("verified", "INTEGER"),
        ("last_updated_at", "TEXT"),
    ]
    for col, col_type in required_columns:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
    
    # Rename user_id to id if needed (backward compatibility)
    if "user_id" in existing_cols and "id" not in existing_cols:
        # SQLite doesn't support column rename, so we need to recreate
        conn.execute("ALTER TABLE users RENAME TO users_old")
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                type TEXT,
                name TEXT,
                username TEXT,
                phone TEXT,
                first_name TEXT,
                last_name TEXT,
                about TEXT,
                is_bot INTEGER,
                verified INTEGER,
                last_updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO users (id, type, username, first_name, last_name, phone)
            SELECT user_id, user_type, username, first_name, last_name, phone
            FROM users_old
            """
        )
        conn.execute("DROP TABLE users_old")
    
    conn.commit()


def upsert_message(
    conn: sqlite3.Connection,
    chat_id: int,
    message_id: int,
    date_iso: Optional[str],
    direction: str,
    text: str,
    from_id: Optional[int],
    message_json: str,
) -> None:
    """Insert or ignore message into DB"""
    conn.execute(
        """
        INSERT OR IGNORE INTO messages 
        (chat_id, message_id, date, direction, text, from_id, json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (chat_id, message_id, date_iso, direction, text, from_id, message_json),
    )


async def update_user_from_telegram(
    conn: sqlite3.Connection,
    client: TelegramClient,
    user_id: int,
) -> None:
    """Fetch user info from Telegram and update in DB (makes API calls - use only for new users!)"""
    try:
        entity = await client.get_entity(user_id)
    except Exception as e:
        print(f"[WARN] Failed to get entity {user_id}: {e}")
        return
    
    # Default values
    utype: Optional[str] = None
    name: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    about: Optional[str] = None
    is_bot: Optional[int] = None
    verified: Optional[int] = None
    
    if isinstance(entity, User):
        utype = "user"
        first_name = (entity.first_name or "") or None
        last_name = entity.last_name or None
        name = (f"{entity.first_name or ''} {entity.last_name or ''}".strip()) or None
        username = f"@{entity.username}" if entity.username else None
        phone = entity.phone or None
        is_bot = 1 if getattr(entity, "bot", False) else 0
        verified = 1 if getattr(entity, "verified", False) else 0
        
        # Fetch about
        try:
            full = await client(functions.users.GetFullUserRequest(id=entity))
            if hasattr(full, "full_user") and hasattr(full.full_user, "about"):
                about = full.full_user.about or None
        except Exception:
            pass
            
    elif isinstance(entity, Channel):
        utype = "channel" if getattr(entity, "broadcast", False) else "group"
        name = entity.title or None
        username = f"@{entity.username}" if entity.username else None
        is_bot = 0
        verified = 1 if getattr(entity, "verified", False) else 0
    elif isinstance(entity, Chat):
        utype = "group"
        name = entity.title or None
        is_bot = 0
        verified = 0
    else:
        utype = "unknown"
    
    # Upsert into DB
    conn.execute(
        """
        INSERT OR REPLACE INTO users 
        (id, type, name, username, phone, first_name, last_name, about, is_bot, verified, last_updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (user_id, utype, name, username, phone, first_name, last_name, about, is_bot, verified),
    )


async def sync_chat_names_from_users(conn: sqlite3.Connection) -> int:
    """Update chat_name, from_name and from_username in messages from users table.
    Only updates records where the field is NULL or empty."""
    # Update chat_name (only if NULL or empty)
    result1 = conn.execute("""
        UPDATE messages 
        SET chat_name = (
          SELECT COALESCE(
            NULLIF(TRIM(u.first_name || ' ' || COALESCE(u.last_name, '')), ''),
            u.name
          )
          FROM users u
          WHERE u.id = messages.chat_id
        )
        WHERE chat_id IN (SELECT id FROM users)
          AND (chat_name IS NULL OR chat_name = '')
    """)
    
    # Update from_name (only if NULL or empty)
    result2 = conn.execute("""
        UPDATE messages 
        SET from_name = (
          SELECT COALESCE(
            NULLIF(TRIM(u.first_name || ' ' || COALESCE(u.last_name, '')), ''),
            u.name
          )
          FROM users u
          WHERE u.id = messages.from_id
        )
        WHERE from_id IS NOT NULL 
          AND from_id IN (SELECT id FROM users)
          AND (from_name IS NULL OR from_name = '')
    """)
    
    # Update from_username (only if NULL or empty)
    result3 = conn.execute("""
        UPDATE messages 
        SET from_username = (
          SELECT u.username
          FROM users u
          WHERE u.id = messages.from_id
        )
        WHERE from_id IS NOT NULL 
          AND from_id IN (SELECT id FROM users)
          AND (from_username IS NULL OR from_username = '')
    """)
    
    conn.commit()
    return (result1.rowcount or 0) + (result2.rowcount or 0) + (result3.rowcount or 0)


# -------------------------
# Export logic
# -------------------------


async def export_all_dialogs(
    *,
    db_path: Path,
    date_from: Optional[datetime] = None,
    max_group_size: int = 20,
) -> None:
    """Export all available Telegram dialogs to SQLite"""
    
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_string = os.getenv("TELEGRAM_SESSION_STRING")
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "anon")

    if not api_id or not api_hash or (not session_string and not session_name):
        raise SystemExit(
            "Missing TELEGRAM_API_ID/TELEGRAM_API_HASH and session vars. Check .env"
        )

    # DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_db(conn)
    except Exception:
        conn.close()
        raise

    # Telethon client
    if session_string:
        client = TelegramClient(StringSession(session_string), int(api_id), api_hash)
    else:
        client = TelegramClient(session_name, int(api_id), api_hash)

    async with client:
        # Get all dialogs
        print("📊 Загружаю список диалогов...")
        dialogs = [d async for d in client.iter_dialogs()]
        print(f"✓ Найдено {len(dialogs)} диалогов")
        
        # Load denied/blocked chats
        denied_ids = set()
        try:
            cur = conn.execute("SELECT dialog_id FROM dialog_denied")
            for (did,) in cur.fetchall():
                try:
                    denied_ids.add(int(did))
                except Exception:
                    continue
        except Exception:
            pass  # Table may not exist in old databases
        
        if denied_ids:
            print(f"🚫 Заблокировано чатов: {len(denied_ids)}")
        
        # Process each dialog
        total_new_messages = 0  # Renamed to avoid conflict with message_iterator.total
        processed_dialogs = 0
        skipped_large_groups = 0
        skipped_no_new = 0  # Chats with no new messages
        updated_users = set()  # Cache for already updated users (to avoid repeated API calls)
        
        for dialog in dialogs:
            entity = dialog.entity
            chat_id = utils.get_peer_id(entity)
            
            # Determine chat type and name
            if hasattr(entity, "title"):
                chat_type = "group"
                chat_name = getattr(entity, "title", "")
                
                # If Telegram doesn't provide title, try to get from DB or first message (e.g., migrated supergroups)
                if not chat_name:
                    db_name = conn.execute(
                        "SELECT chat_name FROM messages WHERE chat_id = ? AND chat_name IS NOT NULL AND chat_name != '' LIMIT 1",
                        (chat_id,)
                    ).fetchone()
                    if db_name:
                        chat_name = db_name[0]
                    else:
                        # Try to get from first message (MessageActionChannelMigrateFrom)
                        try:
                            first_msg = await client.get_messages(entity, limit=1, reverse=True)
                            if first_msg and len(first_msg) > 0:
                                msg_dict = first_msg[0].to_dict()
                                if 'action' in msg_dict and 'title' in msg_dict['action']:
                                    chat_name = msg_dict['action']['title']
                        except Exception:
                            pass
                    
                    # Last resort: use chat_id
                    if not chat_name:
                        chat_name = str(chat_id)
                
                username = getattr(entity, "username", None)
            else:
                chat_type = "user"
                first = getattr(entity, "first_name", "") or ""
                last = getattr(entity, "last_name", "") or ""
                full = f"{first} {last}".strip()
                chat_name = full or getattr(entity, "username", "") or str(chat_id)
                username = getattr(entity, "username", None)

            # Filter: skip large groups
            if chat_type == "group":
                try:
                    participants_count = getattr(entity, "participants_count", None)
                    if participants_count is None:
                        try:
                            full_chat = await client.get_entity(entity)
                            participants_count = getattr(full_chat, "participants_count", 0)
                        except:
                            participants_count = 0
                    
                    if participants_count > max_group_size:
                        # print(f"  ⏭️  SKIP: {chat_name} ({participants_count} участников > {max_group_size})")
                        skipped_large_groups += 1
                        continue
                    else:
                        # print(f"  ✓ Группа {chat_name} ({participants_count} участников)")
                        pass
                except Exception as e:
                    print(f"[WARN] Не удалось проверить размер группы {chat_name}: {e}")
            
            # Get existing message count, max message_id and last message date from DB
            row = conn.execute(
                "SELECT COUNT(*), MAX(message_id), MAX(date) FROM messages WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            existing_count = row[0] or 0
            max_message_id = row[1] or 0
            last_db_date_str = row[2]  # ISO format string or None
            
            # Update chat_name in DB (even if we skip this chat for export)
            if existing_count > 0:
                conn.execute(
                    "UPDATE messages SET chat_name = ? WHERE chat_id = ? AND (chat_name IS NULL OR chat_name = '')",
                    (chat_name, chat_id)
                )
            
            # ⚡ OPTIMIZATION: Skip chat if no new messages in Telegram
            if dialog.message and last_db_date_str:
                try:
                    # Compare last message date in Telegram vs DB (both naive - no timezone)
                    telegram_last_date = dialog.message.date.replace(tzinfo=None)  # naive datetime
                    db_last_date = datetime.fromisoformat(last_db_date_str).replace(tzinfo=None)  # also naive
                    
                    # If Telegram's last message is older or equal to DB -> skip
                    if telegram_last_date <= db_last_date:
                        # print(f"  ⏩ SKIP: {chat_name} (нет новых сообщений, последнее {telegram_last_date.strftime('%Y-%m-%d %H:%M')})")
                        skipped_no_new += 1
                        continue
                except Exception as e:
                    # If date comparison fails, proceed with export (better safe than sorry)
                    print(f"[WARN] Не удалось сравнить даты для {chat_name}: {e}")
            
            # If dialog has no messages at all, skip it
            if dialog.message is None and existing_count == 0:
                # print(f"  ⏩ SKIP: {chat_name} (нет сообщений)")
                continue

            count_inserted = 0
            count_processed = 0  # Total messages seen (including duplicates)
            iterate_kwargs = {"limit": None}
            
            # Start from last loaded message (skip already loaded)
            if max_message_id > 0 and date_from is None:
                # Load only messages with ID > max_message_id (newer messages)
                iterate_kwargs["min_id"] = max_message_id
            elif date_from is not None:
                # If user specified --from date, get messages after that date
                iterate_kwargs["offset_date"] = date_from
                iterate_kwargs["reverse"] = True  # Forward direction from date_from

            # Create iterator
            message_iterator = client.iter_messages(entity, **iterate_kwargs)
            total_messages = 0  # Will be updated after first message

            try:
                async for msg in message_iterator:
                    # Get total after first iteration (when it becomes available)
                    if count_processed == 0:
                        total_messages = getattr(message_iterator, 'total', 0) or 0
                    try:
                        # Basic fields
                        direction = "out" if getattr(msg, "out", False) else "in"
                        text = getattr(msg, "message", None) or ""
                        dt = getattr(msg, "date", None)
                        if dt and dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        date_iso = dt.isoformat() if dt else None

                        # Check date filter
                        if date_from and dt and dt < date_from:
                            break

                        # Sender info
                        raw_from_id = getattr(msg, "from_id", None)
                        resolved_from_id: Optional[int] = None
                        if raw_from_id is not None:
                            try:
                                resolved_from_id = utils.get_peer_id(raw_from_id)
                            except Exception:
                                resolved_from_id = None
                        
                        # Update user info if not in DB (only ONE API call per new user)
                        try:
                            snd = getattr(msg, "sender", None)
                            if snd is not None and hasattr(snd, "id"):
                                user_id = utils.get_peer_id(snd)
                                if user_id not in updated_users:
                                    # Check if user exists in DB
                                    existing = conn.execute(
                                        "SELECT id FROM users WHERE id = ?", (user_id,)
                                    ).fetchone()
                                    
                                    if existing is None:
                                        # New user - fetch full info from Telegram API
                                        await update_user_from_telegram(conn, client, user_id)
                                    
                                    updated_users.add(user_id)
                        except Exception:
                            pass

                        # FIX: For private chats (User), if from_id is NULL and message is incoming -> use chat_id
                        if resolved_from_id is None and direction == "in" and hasattr(entity, "id"):
                            try:
                                from telethon.tl.types import User
                                if isinstance(entity, User):
                                    resolved_from_id = chat_id
                            except Exception:
                                pass

                        # Save message
                        message_json = json.dumps(msg.to_dict(), ensure_ascii=False, default=str)
                        cursor = conn.execute(
                            """
                            INSERT OR IGNORE INTO messages 
                            (chat_id, message_id, date, direction, text, from_id, chat_name, json)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (chat_id, msg.id, date_iso, direction, text, resolved_from_id, chat_name, message_json)
                        )
                        
                        # If message has media and chat is denied/blocked, mark it immediately
                        if msg.media and chat_id in denied_ids:
                            conn.execute(
                                """
                                UPDATE messages 
                                SET transcript = '[ЗАБЛОКИРОВАН]',
                                    transcribed_at = datetime('now'),
                                    transcript_model = 'blocked:denied_chat'
                                WHERE chat_id = ? AND message_id = ?
                                """,
                                (chat_id, msg.id)
                            )
                        
                        if cursor.rowcount > 0:
                            count_inserted += 1
                        count_processed += 1

                        # Interactive progress update every 50 messages
                        if count_processed % 50 == 0:
                            current_total = existing_count + count_inserted
                            if total_messages > 0:
                                print(f"\r  [{processed_dialogs + 1}/{len(dialogs)}] {chat_name}: {count_processed}/{total_messages} → база: {current_total}", end="", flush=True)
                            else:
                                print(f"\r  [{processed_dialogs + 1}/{len(dialogs)}] {chat_name}: обработано {count_processed} → база: {current_total}", end="", flush=True)
                        
                        # Commit every 1000 messages
                        if count_processed % 1000 == 0:
                            conn.commit()

                    except Exception as e:
                        print(f"[ERROR] Failed to process message {msg.id}: {e}")
                        continue

            except Exception as e:
                print(f"\n[ERROR] Failed to iterate messages for {chat_name}: {e}")

            # Final commit and result
            conn.commit()
            final_total = existing_count + count_inserted
            
            # Show total from Telegram if available, otherwise show what we processed
            display_count = f"{count_processed}/{total_messages}" if total_messages > 0 else f"обработано {count_processed}"
            
            if count_inserted > 0:
                print(f"\r  [{processed_dialogs + 1}/{len(dialogs)}] {chat_name}: {display_count} → база: {final_total} (добавлено {count_inserted})          ")
            else:
                print(f"\r  [{processed_dialogs + 1}/{len(dialogs)}] {chat_name}: {display_count} → база: {final_total} (нет новых)          ")
            
            total_new_messages += count_inserted
            processed_dialogs += 1

        # Final sync of chat names from updated users table
        print("\n🔄 Синхронизирую имена чатов и отправителей из таблицы users...")
        updated_rows = await sync_chat_names_from_users(conn)
        if updated_rows > 0:
            print(f"✅ Обновлено имен в {updated_rows} сообщениях (синхронизация с таблицей users).")
        
    conn.close()
    print(f"\n🎉 Экспорт завершён!")
    print(f"  Обработано диалогов: {processed_dialogs}")
    if skipped_large_groups > 0:
        print(f"  Пропущено (большие группы): {skipped_large_groups}")
    if skipped_no_new > 0:
        print(f"  Пропущено (нет новых сообщений): {skipped_no_new}")
    print(f"  Добавлено новых сообщений: {total_new_messages}")


# -------------------------
# CLI
# -------------------------


def parse_args(argv):
    import argparse

    parser = argparse.ArgumentParser(
        description="Export all Telegram dialogs to SQLite (auto mode)"
    )
    
    parser.add_argument(
        "--account",
        required=True,
        help="Account name (loads accounts/{account}/.env and sets database path)",
    )
    parser.add_argument(
        "--max-group-size",
        type=int,
        default=20,
        help="Maximum number of participants in a group to export (default: 20)",
    )
    parser.add_argument(
        "--from",
        dest="date_from",
        default=None,
        help="Start date inclusive. Formats: YYYY-MM-DD, DD.MM.YYYY, DD MM YYYY",
    )

    args = parser.parse_args(argv)
    
    # Load account environment
    load_account_env(args.account)
    
    # Set database path
    current_dir = Path(__file__).resolve().parent  # scripts/messages/
    db_path = current_dir.parent.parent / "accounts" / args.account / "messages.sqlite"  # ../../accounts/{account}/messages.sqlite
    
    # Parse date_from
    date_from: Optional[datetime] = None
    if args.date_from:
        date_from = parse_flexible_date(args.date_from)
        if date_from.tzinfo is None:
            date_from = date_from.replace(tzinfo=timezone.utc)
    
    return db_path, date_from, args.max_group_size


def main(argv) -> None:
    db_path, date_from, max_group_size = parse_args(argv)
    
    print(f"🚀 Режим: экспорт всех диалогов")
    print(f"📁 База данных: {db_path}")
    print(f"🔢 Макс. размер группы: {max_group_size}")
    if date_from:
        print(f"📅 Начиная с: {date_from.strftime('%Y-%m-%d')}")
    print()
    
    asyncio.run(
        export_all_dialogs(
            db_path=db_path,
            date_from=date_from,
            max_group_size=max_group_size,
        )
    )


if __name__ == "__main__":
    main(sys.argv[1:])
