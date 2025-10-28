#!/usr/bin/env python3
"""
Quick script to get user information directly from Telegram API
"""

import asyncio
import sys
from pathlib import Path
from telethon import TelegramClient
from telethon.tl.types import User
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os

async def get_user_info(user_ids: list[int]):
    """Get user info from Telegram"""
    
    # Load env
    script_dir = Path(__file__).resolve().parent  # messages-tools/
    account_dir = script_dir.parent / "data/accounts" / "ychukaev"
    env_path = account_dir / ".env"
    load_dotenv(env_path)
    
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_string = os.getenv("TELEGRAM_SESSION_STRING")
    session_name = os.getenv("TELEGRAM_SESSION_NAME")
    
    if not api_id or not api_hash:
        print("ERROR: TELEGRAM_API_ID or TELEGRAM_API_HASH not set")
        return
    
    # Use StringSession if available, otherwise use session_name
    if session_string:
        client = TelegramClient(StringSession(session_string), int(api_id), api_hash)
    elif session_name:
        session_file = account_dir / f"{session_name}.session"
        client = TelegramClient(str(session_file), int(api_id), api_hash)
    else:
        print("ERROR: Neither TELEGRAM_SESSION_STRING nor TELEGRAM_SESSION_NAME is set")
        return
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            print("ERROR: Not authorized. Run export_all.py first.")
            return
        
        print(f"\n🔍 Получаю информацию о {len(user_ids)} пользователях...\n")
        
        for user_id in user_ids:
            try:
                entity = await client.get_entity(user_id)
                
                if isinstance(entity, User):
                    first_name = entity.first_name or ""
                    last_name = entity.last_name or ""
                    full_name = f"{first_name} {last_name}".strip()
                    username = entity.username or ""
                    deleted = entity.deleted if hasattr(entity, 'deleted') else False
                    
                    status = "❌ DELETED" if deleted else "✅ Active"
                    
                    print(f"{status} | ID: {user_id}")
                    print(f"  Имя: {full_name or '(нет)'}")
                    print(f"  Username: @{username}" if username else "  Username: (нет)")
                    print()
                else:
                    print(f"⚠️  ID: {user_id} - не User (тип: {type(entity).__name__})")
                    print()
                    
            except Exception as e:
                print(f"❌ ID: {user_id} - Ошибка: {e}")
                print()
        
    finally:
        await client.disconnect()

if __name__ == "__main__":
    # Problem user IDs
    user_ids = [
        507043408,
        5474367556,
        690275145,
        1286308829,
        5165629567,
        1622637990,
        1407389576,
        6082533930
    ]
    
    asyncio.run(get_user_info(user_ids))

