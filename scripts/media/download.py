#!/usr/bin/env python3
"""
Скачивание аудио и видео за последние 6 месяцев (<5 минут).
Параллельная загрузка с обработкой Telegram rate limits.
"""
import asyncio
import sqlite3
import json
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

# Загружаем .env
load_dotenv(Path("data/accounts/ychukaev/.env"))

api_id = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")
session_string = os.getenv("TELEGRAM_SESSION_STRING")

db_path = Path("data/accounts/ychukaev/messages.sqlite")
media_dir = Path("data/accounts/ychukaev/media")

media_dir.mkdir(parents=True, exist_ok=True)

# Количество параллельных загрузок (безопасное значение для Telegram)
PARALLEL_DOWNLOADS = 20


def is_audio_or_video(json_str: str) -> tuple[bool, str | None, bool]:
    """Проверяет является ли медиа аудио/видео и есть ли звук.
    
    Returns:
        (is_media, media_type, has_sound):
        - is_media: True если это аудио или видео
        - media_type: "audio" или "video"
        - has_sound: False если Telegram пометил "nosound": true
    """
    try:
        data = json.loads(json_str)
        media = data.get("media")
        if not media:
            return False, None, True
        
        if media.get("_") == "MessageMediaDocument":
            doc = media.get("document") or {}
            mime = doc.get("mime_type") or ""
            
            # Пропускаем картинки
            if mime.startswith("image/"):
                return False, None, True
            
            # Ищем атрибуты аудио/видео
            for attr in doc.get("attributes", []) or []:
                kind = attr.get("_")
                if kind == "DocumentAttributeAudio":
                    return True, "audio", True
                if kind == "DocumentAttributeVideo":
                    # Проверяем флаг nosound
                    has_sound = not attr.get("nosound", False)
                    return True, "video", has_sound
        
        return False, None, True
    except Exception:
        return False, None, True


def get_duration(json_str: str) -> int | None:
    """Получает длительность медиа в секундах."""
    try:
        data = json.loads(json_str)
        media = data.get("media") or {}
        doc = media.get("document") or {}
        
        for attr in doc.get("attributes", []) or []:
            duration = attr.get("duration")
            if duration is not None:
                return int(duration)
        
        return None
    except Exception:
        return None


async def download_one_file(client, semaphore, conn, idx, total, chat_id, message_id, json_str, media_type, duration):
    """Скачивает один файл с обработкой rate limits."""
    async with semaphore:  # Ограничиваем параллелизм
        try:
            # Проверяем не скачан ли уже
            existing = list(media_dir.glob(f"{chat_id}_{message_id}.*"))
            if existing:
                conn.execute(
                    "UPDATE messages SET media_path = ? WHERE chat_id = ? AND message_id = ?",
                    (str(existing[0].absolute()), chat_id, message_id)
                )
                conn.commit()
                return {"status": "exists", "file": existing[0].name}
            
            # Получаем entity
            try:
                entity = await client.get_entity(chat_id)
            except Exception:
                await asyncio.sleep(1)
                entity = await client.get_entity(chat_id)
            
            # Получаем сообщение
            message = await client.get_messages(entity, ids=message_id)
            
            if not message or not message.media:
                return {"status": "no_media"}
            
            # Проверяем длительность и размер из Telegram API
            actual_duration = None
            file_size = None
            if message.file:
                actual_duration = message.file.duration
                file_size = message.file.size
            
            # Пропускаем длинные файлы >5 минут
            if actual_duration and actual_duration > 300:
                conn.execute(
                    "UPDATE messages SET long_media = 1, duration_seconds = ? WHERE chat_id = ? AND message_id = ?",
                    (actual_duration, chat_id, message_id)
                )
                conn.commit()
                return {"status": "too_long", "duration": actual_duration}
            
            # Скачиваем
            duration_str = f"{actual_duration or duration or '?'}s"
            size_mb = f"{file_size / 1024 / 1024:.2f}MB" if file_size else "?"
            print(f"[{idx}/{total}] 📥 {media_type} {duration_str} {size_mb}: {chat_id}/{message_id}", flush=True)
            
            start_time = time.time()
            file_path = await client.download_media(
                message.media,
                file=str(media_dir)
            )
            download_time = time.time() - start_time
            
            if file_path:
                # Переименовываем в стандартный формат
                downloaded_path = Path(file_path)
                ext = downloaded_path.suffix
                new_path = media_dir / f"{chat_id}_{message_id}{ext}"
                
                if downloaded_path != new_path:
                    downloaded_path.rename(new_path)
                    file_path = str(new_path)
                
                # Сохраняем в БД
                conn.execute(
                    """UPDATE messages 
                       SET media_path = ?, 
                           media_kind = ?, 
                           duration_seconds = ?
                       WHERE chat_id = ? AND message_id = ?""",
                    (str(Path(file_path).absolute()), media_type, actual_duration or duration, chat_id, message_id)
                )
                conn.commit()
                print(f"   ✓ Скачано за {download_time:.1f}s", flush=True)
                return {"status": "downloaded", "time": download_time, "size": file_size}
            else:
                return {"status": "failed"}
        
        except FloodWaitError as e:
            # Telegram просит подождать
            print(f"   ⏱ FloodWait {e.seconds}s для {chat_id}/{message_id}", flush=True)
            await asyncio.sleep(e.seconds)
            # Повторяем попытку
            return await download_one_file(client, semaphore, conn, idx, total, chat_id, message_id, json_str, media_type, duration)
        
        except Exception as e:
            print(f"   ❌ Ошибка {chat_id}/{message_id}: {e}", flush=True)
            return {"status": "error", "error": str(e)}


async def main():
    print("🚀 Запуск скрипта (параллельная загрузка)...", flush=True)
    print("📥 Скачивание медиа за последние 6 месяцев", flush=True)
    print("=" * 60, flush=True)
    
    print(f"🔍 Подключение к БД: {db_path}", flush=True)
    conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
    print("✓ Подключено к БД", flush=True)
    
    # Выбираем медиа за последние 6 месяцев
    # Загружаем список заблокированных чатов
    denied_ids = set()
    try:
        cur = conn.execute("SELECT dialog_id FROM dialog_denied")
        for (did,) in cur.fetchall():
            try:
                denied_ids.add(int(did))
            except Exception:
                continue
    except Exception:
        pass  # Таблица может не существовать
    
    if denied_ids:
        print(f"🚫 Заблокировано чатов: {len(denied_ids)}", flush=True)
    
    print("📊 Подсчёт медиа...", flush=True)
    
    rows = conn.execute("""
        SELECT chat_id, message_id, json
        FROM messages
        WHERE json LIKE '%"media":%'
          AND date >= date('now', '-6 months')
          AND (media_path IS NULL OR media_path = '')
          AND (transcript IS NULL OR transcript = '')
    """).fetchall()
    
    print(f"✓ Найдено {len(rows)} медиа-сообщений", flush=True)
    
    # Фильтруем: только аудио/видео <5 минут со звуком
    print("🔍 Начинаем фильтрацию...", flush=True)
    to_download = []
    skipped_images = 0
    skipped_long = 0
    skipped_nosound = 0
    
    for idx, (chat_id, message_id, json_str) in enumerate(rows):
        if idx % 1000 == 0:
            print(f"   Обработано {idx}/{len(rows)}...", flush=True)
        
        is_media, media_type, has_sound = is_audio_or_video(json_str)
        
        if not is_media:
            skipped_images += 1
            continue
        
        # Пропускаем видео без звука
        if not has_sound:
            skipped_nosound += 1
            # Помечаем в БД что это видео без звука
            conn.execute(
                "UPDATE messages SET transcript = '[БЕЗ ЗВУКА]', media_kind = ? WHERE chat_id = ? AND message_id = ?",
                (media_type, chat_id, message_id)
            )
            continue
        
        duration = get_duration(json_str)
        
        # Пропускаем длинные видео >5 минут
        if duration is not None and duration > 300:
            skipped_long += 1
            # Помечаем в БД
            conn.execute(
                "UPDATE messages SET long_media = 1 WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id)
            )
            continue
        
        to_download.append((chat_id, message_id, json_str, media_type, duration))
    
    print("💾 Сохранение изменений в БД...", flush=True)
    conn.commit()
    print("✓ Сохранено", flush=True)
    
    print(f"\n📋 Статистика фильтрации:", flush=True)
    print(f"   Аудио/видео для скачивания: {len(to_download)}", flush=True)
    print(f"   Пропущено картинок: {skipped_images}", flush=True)
    print(f"   Пропущено длинных (>5 мин): {skipped_long}", flush=True)
    print(f"   Пропущено без звука (nosound): {skipped_nosound}", flush=True)
    
    if not to_download:
        print("\n✓ Нечего скачивания", flush=True)
        conn.close()
        return
    
    # Создаём Telegram клиент
    print(f"\n🔌 Подключение к Telegram...", flush=True)
    print(f"   API ID: {api_id[:5]}...", flush=True)
    print(f"   Session: {'StringSession' if session_string else 'anon'}", flush=True)
    
    if session_string:
        print("   Создание клиента с StringSession...", flush=True)
        client = TelegramClient(StringSession(session_string), int(api_id), api_hash)
    else:
        print("   Создание анонимного клиента...", flush=True)
        client = TelegramClient("anon", int(api_id), api_hash)
    
    # Настраиваем автоматическое ожидание при FloodWait
    client.flood_sleep_threshold = 60  # Автоматически ждать до 60 секунд
    
    print("   Открытие соединения...", flush=True)
    async with client:
        print("   Получение диалогов...", flush=True)
        await client.get_dialogs(limit=None)
        print("✓ Подключено к Telegram", flush=True)
        
        print(f"\n📥 Начинаем параллельное скачивание {len(to_download)} файлов...", flush=True)
        print(f"   Параллельность: {PARALLEL_DOWNLOADS} потоков", flush=True)
        
        # Создаем семафор для каждой сессии
        semaphore = asyncio.Semaphore(PARALLEL_DOWNLOADS)
        
        # Создаем задачи для всех файлов
        tasks = []
        for idx, (chat_id, message_id, json_str, media_type, duration) in enumerate(to_download, 1):
            task = download_one_file(
                client, semaphore, conn, 
                idx, len(to_download),
                chat_id, message_id, json_str, media_type, duration
            )
            tasks.append(task)
        
        # Запускаем все задачи параллельно
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.time() - start_time
        
        # Подсчитываем статистику
        downloaded = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "downloaded")
        exists = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "exists")
        failed = sum(1 for r in results if isinstance(r, dict) and r.get("status") in ["failed", "error", "no_media"])
        skipped_long = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "too_long")
    
    conn.close()
    
    print(f"\n{'='*60}")
    print(f"✅ Готово за {total_time/60:.1f} минут!")
    print(f"   Скачано: {downloaded}")
    print(f"   Уже было: {exists}")
    print(f"   Слишком длинные: {skipped_long}")
    print(f"   Ошибок: {failed}")
    print(f"   Всего обработано: {len(to_download)}")
    if downloaded > 0:
        print(f"   Средняя скорость: {downloaded/(total_time/60):.1f} файлов/мин")


if __name__ == "__main__":
    asyncio.run(main())

