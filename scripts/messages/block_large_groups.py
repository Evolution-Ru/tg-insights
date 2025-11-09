#!/usr/bin/env python3
"""
Блокирует все группы с количеством участников больше указанного порога.
"""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient, utils
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat


def load_account_env(account_name: str) -> None:
    """Load environment variables from account-specific .env file"""
    current_dir = Path(__file__).resolve().parent
    env_path = current_dir.parent.parent / "accounts" / account_name / ".env"
    
    if not env_path.exists():
        raise SystemExit(f"Environment file not found: {env_path}")
    
    print(f"Loading environment from: {env_path}")
    load_dotenv(env_path)


async def block_large_groups(db_path: Path, max_participants: int) -> None:
    """Block all groups with more than max_participants members"""
    
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_string = os.getenv("TELEGRAM_SESSION_STRING")
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "anon")

    if not api_id or not api_hash or (not session_string and not session_name):
        raise SystemExit("Missing TELEGRAM_API_ID/TELEGRAM_API_HASH and session vars")

    # Connect to database
    conn = sqlite3.connect(str(db_path))
    
    # Create dialog_denied table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dialog_denied (
            dialog_id TEXT PRIMARY KEY,
            denied_at TEXT DEFAULT (datetime('now')),
            reason TEXT
        )
    """)
    conn.commit()

    # Telethon client
    if session_string:
        client = TelegramClient(StringSession(session_string), int(api_id), api_hash)
    else:
        client = TelegramClient(session_name, int(api_id), api_hash)

    blocked_count = 0
    checked_count = 0
    
    async with client:
        print(f"📊 Загружаю список диалогов...")
        dialogs = [d async for d in client.iter_dialogs()]
        print(f"✓ Найдено {len(dialogs)} диалогов")
        
        for dialog in dialogs:
            entity = dialog.entity
            chat_id = utils.get_peer_id(entity)
            
            # Check only groups/channels
            if not isinstance(entity, (Channel, Chat)):
                continue
            
            chat_name = getattr(entity, "title", str(chat_id))
            
            # Check if already blocked
            existing = conn.execute(
                "SELECT dialog_id FROM dialog_denied WHERE dialog_id = ?",
                (str(chat_id),)
            ).fetchone()
            
            if existing:
                continue
            
            # Get participants count
            participants_count = getattr(entity, "participants_count", None)
            
            if participants_count is None:
                try:
                    full_chat = await client.get_entity(entity)
                    participants_count = getattr(full_chat, "participants_count", 0)
                except:
                    participants_count = 0
            
            checked_count += 1
            
            if participants_count > max_participants:
                # Block this group
                conn.execute(
                    """
                    INSERT OR REPLACE INTO dialog_denied (dialog_id, reason)
                    VALUES (?, ?)
                    """,
                    (str(chat_id), f"auto_block:large_group:{participants_count}_participants")
                )
                conn.commit()
                blocked_count += 1
                print(f"🚫 Заблокирована: {chat_name} ({participants_count} участников)")
            else:
                print(f"✓ Пропущена: {chat_name} ({participants_count} участников)")
    
    conn.close()
    print(f"\n✅ Готово!")
    print(f"   Проверено групп: {checked_count}")
    print(f"   Заблокировано: {blocked_count}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Block large groups")
    parser.add_argument("--account", required=True, help="Account name")
    parser.add_argument("--max-participants", type=int, default=20, 
                       help="Maximum number of participants (default: 20)")
    
    args = parser.parse_args()
    
    # Load account environment
    load_account_env(args.account)
    
    # Set database path
    current_dir = Path(__file__).resolve().parent
    db_path = current_dir.parent.parent / "accounts" / args.account / "messages.sqlite"
    
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    
    print(f"🚀 Блокировка больших групп")
    print(f"📁 База данных: {db_path}")
    print(f"👥 Макс. участников: {args.max_participants}\n")
    
    asyncio.run(block_large_groups(db_path, args.max_participants))


if __name__ == "__main__":
    main()

