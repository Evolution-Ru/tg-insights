#!/usr/bin/env python3
"""
Транскрибация аудио/видео через T-банк STT API.

Преимущества по сравнению с OpenAI:
- Бесплатно/дешевле
- Поддержка каналов (разделение говорящих)
- Временные метки
- Асинхронная обработка

Использование:
  python transcribe_media_tbank.py \
    --db ../data/accounts/your_account/messages.sqlite \
    --media-dir ../data/accounts/your_account/media

Требуется в .env:
- TBANK_API_KEY
- TBANK_SECRET_KEY
- TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING
"""

import asyncio
import json
import shutil
import subprocess
import os
import sys
import base64
import time
import threading
from datetime import datetime
from dotenv import load_dotenv
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

from telethon import TelegramClient


class TeeLogger:
    """Дублирует вывод в файл и stdout с потокобезопасной записью."""
    def __init__(self, log_file: Path):
        self.terminal = sys.stdout
        self.log = open(log_file, 'w', buffering=1)  # Line buffering
        self._lock = threading.Lock()  # Защита от наслоения строк
    
    def write(self, message):
        with self._lock:
            self.terminal.write(message)
            self.log.write(message)
            self.terminal.flush()
            self.log.flush()
    
    def flush(self):
        with self._lock:
            self.terminal.flush()
            self.log.flush()
    
    def close(self):
        self.log.close()


from telethon.sessions import StringSession
from TbankClient import TbankClient


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Добавляет необходимые колонки в таблицу messages."""
    cur = conn.execute("PRAGMA table_info(messages);")
    existing = {row[1] for row in cur.fetchall()}
    
    columns_to_add = {
        "transcript": "TEXT",
        "media_path": "TEXT",
        "transcribed_at": "TEXT",
        "transcript_model": "TEXT",
        "duration_seconds": "INTEGER",
        "media_kind": "TEXT",
        "long_media": "INTEGER",
        "tbank_operation_id": "TEXT",  # Для отслеживания операций T-банка
    }
    
    for col_name, col_type in columns_to_add.items():
        if col_name not in existing:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
            conn.commit()


def load_denied_ids(conn: sqlite3.Connection) -> set:
    """Загружает список заблокированных chat_id из dialog_denied."""
    denied = set()
    try:
        cur = conn.execute("SELECT dialog_id FROM dialog_denied")
        for (did,) in cur.fetchall():
            try:
                denied.add(int(did))
            except Exception:
                continue
    except Exception:
        pass  # Таблица может не существовать в старых БД
    return denied


def select_pending_media(conn: sqlite3.Connection, limit: int = None, denied_ids: set = None) -> List[Tuple[int, int, str, str, str, str]]:
    """Выбирает медиа-сообщения без транскрипции с уже скачанными файлами, исключая заблокированные чаты."""
    query = """
        SELECT m.chat_id, m.message_id, m.json, m.media_path, 
               COALESCE(m.chat_name, u.name, 'Unknown') as chat_name,
               m.date
        FROM messages m
        LEFT JOIN users u ON m.chat_id = u.id
        WHERE (m.transcript IS NULL OR length(trim(m.transcript)) = 0)
          AND (m.long_media IS NULL OR m.long_media = 0)
          AND m.media_path IS NOT NULL 
          AND m.media_path != ''
          AND (m.tbank_operation_id IS NULL OR m.tbank_operation_id = '' OR m.tbank_operation_id = 'pending')
        """
    
    # Фильтруем заблокированные чаты
    if denied_ids:
        placeholders = ','.join('?' * len(denied_ids))
        query += f" AND m.chat_id NOT IN ({placeholders})"
    
    query += " ORDER BY m.chat_id, m.message_id"
    
    if limit:
        query += f" LIMIT {limit}"
    
    params = list(denied_ids) if denied_ids else []
    rows = conn.execute(query, params).fetchall()
    return [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]


def get_message_link(chat_id: int, message_id: int) -> str:
    """Генерирует ссылку на сообщение в Telegram."""
    # Для приватных чатов/каналов с chat_id вида -100XXXXXXXXXX
    if str(chat_id).startswith("-100"):
        # Убираем -100 префикс
        channel_id = str(chat_id)[4:]
        return f"https://t.me/c/{channel_id}/{message_id}"
    # Для обычных чатов (редко используется)
    return f"https://t.me/c/{abs(chat_id)}/{message_id}"


def get_chat_title(json_blob: str) -> str:
    """Извлекает название чата из JSON сообщения."""
    try:
        jb = json.loads(json_blob)
        peer_id = jb.get("peer_id") or {}
        
        # Пытаемся получить title из разных мест
        title = peer_id.get("title")
        if title:
            return title
        
        # Иногда title может быть в корне
        title = jb.get("title")
        if title:
            return title
            
        # Для личных чатов может быть first_name/last_name
        from_user = jb.get("from_id") or {}
        first_name = from_user.get("first_name", "")
        last_name = from_user.get("last_name", "")
        if first_name or last_name:
            return f"{first_name} {last_name}".strip()
        
        return "Unknown"
    except Exception:
        return "Unknown"


def is_audio_or_video(json_blob: str) -> tuple[bool, bool]:
    """Проверяет, является ли медиа аудио/видео и есть ли в нем звук.
    
    Returns:
        (is_media, has_sound): 
        - is_media: True если это аудио или видео
        - has_sound: False если Telegram пометил "nosound": true
    """
    try:
        jb = json.loads(json_blob)
        media = jb.get("media")
        if not media:
            return False, True
        
        media_type = media.get("_", "")
        if media_type == "MessageMediaDocument":
            document = media.get("document") or {}
            attr_mime = document.get("mime_type") or ""
            
            is_media = False
            has_sound = True  # По умолчанию считаем что звук есть
            
            if attr_mime.startswith("audio/") or attr_mime.startswith("video/"):
                is_media = True
            
            for attr in document.get("attributes", []) or []:
                kind = attr.get("_")
                if kind in ("DocumentAttributeAudio", "DocumentAttributeVideo"):
                    is_media = True
                    # Проверяем флаг nosound у видео
                    if kind == "DocumentAttributeVideo":
                        if attr.get("nosound", False):
                            has_sound = False
            
            return is_media, has_sound
    except Exception:
        pass
    return False, True


def media_kind_and_duration(json_blob: str) -> tuple[str | None, int | None]:
    """Определяет тип медиа (audio/video) и длительность."""
    try:
        jb = json.loads(json_blob)
        media = jb.get("media") or {}
        document = media.get("document") or {}
        
        kind: str | None = None
        mime = document.get("mime_type") or ""
        if mime.startswith("audio/"):
            kind = "audio"
        elif mime.startswith("video/"):
            kind = "video"
        else:
            for attr in document.get("attributes", []) or []:
                a_type = attr.get("_")
                if a_type == "DocumentAttributeAudio":
                    kind = "audio"
                if a_type == "DocumentAttributeVideo":
                    kind = "video"
        
        duration = None
        for attr in document.get("attributes", []) or []:
            if "duration" in attr:
                try:
                    duration = int(attr.get("duration"))
                    break
                except Exception:
                    pass
        return kind, duration
    except Exception:
        return None, None


def ffmpeg_available() -> bool:
    """Проверяет наличие ffmpeg."""
    return shutil.which("ffmpeg") is not None


def get_media_duration(input_path: Path) -> Optional[int]:
    """Получает длительность медиа-файла через ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return int(float(result.stdout.strip()))
    except Exception:
        pass
    return None


def has_audio_stream(input_path: Path) -> bool:
    """Проверяет наличие аудио дорожки в файле."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "json",
            str(input_path),
        ]
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if proc.returncode != 0:
            return False
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams", [])
        return bool(streams)
    except Exception:
        return False


def extract_audio_with_ffmpeg(input_path: Path, output_path: Path) -> bool:
    """Извлекает аудио из видео/аудио в формат WAV LINEAR16 для T-банка.
    
    T-банк STT работает с WAV (LINEAR16 PCM, 16kHz, mono).
    Telegram использует OPUS в .oga контейнерах, который нужно конвертировать.
    
    Примечание: видео без звука уже отфильтрованы на этапе выборки через флаг nosound.
    """
    import time
    start_time = time.time()
    
    try:
        # Получаем размер входного файла
        input_size_bytes = input_path.stat().st_size
        if input_size_bytes < 1024 * 1024:  # Меньше 1 MB
            input_size_kb = input_size_bytes / 1024
            print(f"   📁 Размер входного: {input_size_kb:.1f} KB")
        else:
            input_size_mb = input_size_bytes / (1024 * 1024)
            print(f"   📁 Размер входного: {input_size_mb:.1f} MB")
        
        cmd = [
            "ffmpeg",
            "-nostdin",  # Не читать из stdin (предотвращает зависание)
            "-y",
            "-loglevel", "error",  # Только ошибки (меньше вывода)
            "-i", str(input_path),
            "-vn",  # Без видео
            "-ar", "16000",  # 16kHz - стандарт для STT
            "-ac", "1",  # Моно
            "-c:a", "pcm_s16le",  # Linear PCM 16-bit
            str(output_path),
        ]
        
        # Таймаут 60 секунд с принудительным kill
        proc = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL  # Закрываем stdin
        )
        
        # Ждем завершения с таймаутом
        timeout_seconds = 60
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            elapsed = time.time() - start_time
            
            # Проверяем что файл создан и не пустой (минимум 1KB)
            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1024:
                output_size_mb = output_path.stat().st_size / (1024 * 1024)
                print(f"   ⏱ Конвертация: {elapsed:.1f}s → {output_size_mb:.1f} MB")
                return True
            
            if proc.returncode != 0:
                stderr_text = stderr.decode('utf-8', errors='ignore')[:200] if stderr else ""
                print(f"   ⚠️  FFmpeg код {proc.returncode}: {stderr_text}")
            
            return False
            
        except subprocess.TimeoutExpired:
            # Принудительно убиваем зависший процесс
            proc.kill()
            proc.wait()  # Ждем завершения после kill
            elapsed = time.time() - start_time
            print(f"   ⏰ ТАЙМАУТ конвертации ({elapsed:.0f}s) - файл поврежден или слишком сложный")
            return False
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"   ❌ Ошибка конвертации ({elapsed:.1f}s): {e}")
        return False


async def download_message_media(
    client: TelegramClient, chat_id: int, message_id: int, dest_dir: Path
) -> Optional[Path]:
    """Скачивает медиа из Telegram."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        # Проверяем, не скачан ли уже файл
        existing = list(dest_dir.glob(f"{chat_id}_{message_id}.*"))
        if existing:
            return existing[0]
        
        try:
            entity = await client.get_entity(chat_id)
        except Exception:
            await client.get_dialogs(limit=None)
            entity = await client.get_entity(chat_id)
        
        msg = await client.get_messages(entity, ids=message_id)
        if not msg or not msg.media:
            return None
        
        out = dest_dir / f"{chat_id}_{message_id}"
        file_path = await client.download_media(msg, file=str(out))
        if not file_path:
            return None
        return Path(file_path)
    except Exception as e:
        print(f"[WARN] Ошибка загрузки {chat_id}/{message_id}: {e}")
        return None


def transcribe_file_tbank(file_path: Path, tbank_client: TbankClient) -> Optional[str]:
    """Отправляет файл на транскрибацию в T-банк и возвращает operation_id.
    
    Файл должен быть в формате WAV LINEAR16 PCM, 16kHz, mono.
    """
    try:
        # Читаем аудио файл
        with open(file_path, "rb") as f:
            audio_content = f.read()
        
        # Отправляем на распознавание
        response = tbank_client.request(
            "POST",
            "/v1/stt:longrunningrecognize",
            {
                "config": {
                    "encoding": "LINEAR16",  # WAV PCM 16-bit
                    "sample_rate_hertz": 16000,  # 16kHz - стандарт для STT
                    "num_channels": 1,  # Моно
                    "language_code": "ru-RU",  # Русский язык
                },
                "audio": {"content": base64.b64encode(audio_content).decode("utf-8")},
            },
        )
        
        if not response or not response.text:
            print(f"[WARN] Не удалось отправить {file_path} в T-банк")
            return None
        
        data = json.loads(response.text)
        operation_id = data.get("id")
        print(f"[OK] Отправлено {file_path.name}, operation_id: {operation_id}")
        return operation_id
        
    except Exception as e:
        print(f"[WARN] Ошибка транскрибации {file_path}: {e}")
        return None


def check_operation_status(operation_id: str, tbank_client: TbankClient) -> Optional[tuple[str, str]]:
    """Проверяет статус операции транскрибации и возвращает (текст, статус) если готово."""
    try:
        response = tbank_client.request("GET", f"/v1/operations/{operation_id}")
        
        if not response or not response.text:
            return None
        
        data = json.loads(response.text)
        
        # Проверяем, завершена ли операция
        if "response" not in data:
            return None
        
        # Собираем текст транскрипции
        transcription_text = ""
        duration = 0
        
        for result in data["response"].get("results", []):
            for alternative in result.get("alternatives", []):
                transcript = alternative.get("transcript")
                if not transcript:
                    continue
                
                start_seconds = float(str(result.get("start_time", "0")).rstrip("s"))
                end_seconds = float(str(result.get("end_time", "0")).rstrip("s"))
                duration = max(duration, end_seconds)
                
                # Форматируем время
                minutes, seconds = divmod(start_seconds, 60)
                hours, minutes = divmod(minutes, 60)
                formatted_time = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
                
                # Добавляем строку транскрипции
                channel = result.get("channel", "0")
                confidence = float(alternative.get("confidence", 0))
                transcription_text += f"{formatted_time} c{channel}: {transcript} ({confidence:.1f})\n"
        
        # Проверяем что транскрипция не пустая и содержит хоть какой-то текст
        if transcription_text and len(transcription_text.strip()) > 10:
            return (transcription_text, "done")
        
        # Если пусто - возвращаем статус для логирования
        results_count = len(data["response"].get("results", []))
        return (None, f"empty:{results_count}")
        
    except Exception as e:
        return (None, f"error:{str(e)}")


async def process_one_file(
    idx: int,
    total: int,
    chat_id: int,
    message_id: int,
    json_str: str,
    media_path: str,
    chat_name: str,
    msg_date: str,
    media_dir: Path,
    tbank_client,
    conn: sqlite3.Connection,
    semaphore: asyncio.Semaphore,
    db_lock: asyncio.Lock
) -> dict:
    """Обрабатывает один файл: конвертация + отправка в T-bank."""
    async with semaphore:
        link = get_message_link(chat_id, message_id)
        
        # Форматируем дату для вывода (убираем секунды и таймзону)
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(msg_date.replace('Z', '+00:00'))
            date_str = dt.strftime('%Y-%m-%d %H:%M')
        except:
            date_str = msg_date[:16] if msg_date else "Unknown"
        
        print(f"[{idx}/{total}] 🔄 {link} | 📢 {chat_name} | 📅 {date_str}", flush=True)
        
        local = Path(media_path)
        if not local.exists():
            print(f"   ❌ Файл не найден: {media_path}")
            return {"status": "file_not_found"}
        
        # Определяем тип и длительность
        kind, duration = media_kind_and_duration(json_str)
        
        # Если длительность не определена из JSON, используем ffprobe
        if duration is None and local.exists():
            duration = await asyncio.to_thread(get_media_duration, local)
        
        async with db_lock:
            conn.execute(
                """
                UPDATE messages 
                SET media_kind = COALESCE(?, media_kind), 
                    duration_seconds = COALESCE(?, duration_seconds) 
                WHERE chat_id = ? AND message_id = ?
                """,
                (kind, duration, chat_id, message_id),
            )
            conn.commit()
        
        # Пропускаем длинные медиа (>5 минут)
        if duration is not None and duration > 300:
            async with db_lock:
                conn.execute(
                    "UPDATE messages SET long_media = 1 WHERE chat_id = ? AND message_id = ?",
                    (chat_id, message_id),
                )
                conn.commit()
            print(f"   ⏭ Длинное медиа ({duration}s)")
            return {"status": "too_long"}
        
        # Конвертируем в WAV для T-банка
        to_transcribe = local
        
        # Для видео проверяем наличие аудио (ffprobe блокирующий)
        if kind == "video":
            has_audio = await asyncio.to_thread(has_audio_stream, local)
            if not has_audio:
                async with db_lock:
                    conn.execute(
                        """
                        UPDATE messages 
                        SET transcript = ?, transcribed_at = datetime('now'), transcript_model = ? 
                        WHERE chat_id = ? AND message_id = ?
                        """,
                        ("[нет аудио дорожки]", "skip:no-audio", chat_id, message_id),
                    )
                    conn.commit()
                print(f"   ⏭ Видео без звука")
                return {"status": "no_audio"}
        
        # Конвертируем в WAV LINEAR16 для T-банка
        if ffmpeg_available():
            wav_out = media_dir / f"{chat_id}_{message_id}.wav"
            if not wav_out.exists():
                print(f"   🔄 Конвертация WAV...", flush=True)
                # FFmpeg блокирующий - запускаем в отдельном потоке
                ok = await asyncio.to_thread(extract_audio_with_ffmpeg, local, wav_out)
                if ok:
                    to_transcribe = wav_out
                    print(f"   ✓ WAV готов")
                else:
                    print(f"   ❌ Ошибка конвертации")
                    return {"status": "conversion_error"}
            else:
                to_transcribe = wav_out
        
        # Отправляем на транскрибацию (HTTP-запрос блокирующий - в отдельном потоке)
        print(f"   📤 Отправка в T-bank...", flush=True)
        operation_id = await asyncio.to_thread(transcribe_file_tbank, to_transcribe, tbank_client)
        if operation_id:
            async with db_lock:
                conn.execute(
                    "UPDATE messages SET tbank_operation_id = ? WHERE chat_id = ? AND message_id = ?",
                    (operation_id, chat_id, message_id),
                )
                conn.commit()
            print(f"   ✓ {operation_id[:8]}...")
            return {"status": "sent", "operation_id": operation_id}
        else:
            print(f"   ❌ Ошибка отправки")
            return {"status": "send_error"}


async def main(argv: List[str]) -> None:
    import argparse
    print("🚀 Запуск stt.tbank.py...")
    
    # Настраиваем автоматическое логирование
    project_root = Path(__file__).parent.parent.parent
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = logs_dir / f"stt_tbank_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    tee_logger = TeeLogger(log_file)
    sys.stdout = tee_logger
    sys.stderr = tee_logger
    
    print(f"📝 Лог: {log_file.name}")

    parser = argparse.ArgumentParser(
        description="Транскрибация медиа через T-банк STT"
    )
    parser.add_argument("--account", help="Имя аккаунта (например: ychukaev)")
    parser.add_argument("--db", help="Путь к messages.sqlite (альтернатива --account)")
    parser.add_argument("--media-dir", help="Директория для медиа (альтернатива --account)")
    parser.add_argument("--check-only", action="store_true", 
                       help="Только проверить статус существующих операций")
    parser.add_argument("--limit", type=int, default=None,
                       help="Ограничить количество файлов для обработки")
    args = parser.parse_args(argv)
    
    # Определяем пути на основе аккаунта или напрямую
    if args.account:
        project_root = Path(__file__).parent.parent.parent
        args.db = str(project_root / "data" / "accounts" / args.account / "messages.sqlite")
        args.media_dir = str(project_root / "data" / "accounts" / args.account / "media")
    elif not args.db or not args.media_dir:
        parser.error("Укажите либо --account, либо оба параметра --db и --media-dir")

    # Загружаем переменные окружения
    # Определяем имя аккаунта для поиска .env
    account_name = args.account if args.account else "ychukaev"
    
    env_paths = [
        Path(__file__).parent.parent.parent / "data" / "accounts" / account_name / ".env",
        Path.cwd() / ".env",
        Path(__file__).parent / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            print(f"✓ Загружаю .env из {env_path}")
            load_dotenv(env_path)
            break
    else:
        print("⚠️  .env не найден, пробую стандартный поиск")
        load_dotenv()  # Fallback к стандартному поиску

    # T-банк credentials
    tbank_api_key = os.getenv("TBANK_API_KEY")
    tbank_secret_key = os.getenv("TBANK_SECRET_KEY")
    
    if not tbank_api_key or not tbank_secret_key:
        print("[ERROR] Нужны TBANK_API_KEY и TBANK_SECRET_KEY в .env")
        sys.exit(1)
    
    tbank_client = TbankClient(tbank_api_key, tbank_secret_key)
    
    # Telegram credentials
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_string = os.getenv("TELEGRAM_SESSION_STRING")
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "anon")

    db_path = Path(args.db).expanduser().resolve()
    media_dir = Path(args.media_dir).expanduser().resolve()

    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn)
        
        # Сначала проверяем статус существующих операций (параллельно)
        pending_ops = conn.execute(
            """
            SELECT chat_id, message_id, tbank_operation_id
            FROM messages
            WHERE tbank_operation_id IS NOT NULL
              AND tbank_operation_id != 'pending'
              AND (transcript IS NULL OR length(trim(transcript)) = 0)
              AND (long_media IS NULL OR long_media = 0)
            """
        ).fetchall()
        
        print(f"Проверяю статус {len(pending_ops)} операций...")
        
        if pending_ops:
            # Создаем задачи для параллельной проверки (по 50 одновременно)
            semaphore_check = asyncio.Semaphore(50)
            db_lock_check = asyncio.Lock()
            
            async def check_one_operation(chat_id, message_id, operation_id):
                async with semaphore_check:
                    link = get_message_link(chat_id, message_id)
                    # HTTP-запрос в отдельном потоке
                    result = await asyncio.to_thread(check_operation_status, operation_id, tbank_client)
                    if result:
                        transcript, status = result
                        if transcript:
                            async with db_lock_check:
                                conn.execute(
                                    """
                                    UPDATE messages 
                                    SET transcript = ?, 
                                        transcribed_at = datetime('now'), 
                                        transcript_model = ?
                                    WHERE chat_id = ? AND message_id = ?
                                    """,
                                    (transcript, "tbank:stt", chat_id, message_id),
                                )
                                conn.commit()
                            print(f"✓ Транскрибировано: {link}")
                            return "done"
                        else:
                            # Статус содержит информацию об ошибке/пустоте
                            if status.startswith("empty:"):
                                # Помечаем в БД как пустую транскрипцию, чтобы не проверять снова
                                async with db_lock_check:
                                    conn.execute(
                                        """
                                        UPDATE messages 
                                        SET transcript = '[ПУСТО]', 
                                            transcribed_at = datetime('now'), 
                                            transcript_model = 'tbank:stt:empty'
                                        WHERE chat_id = ? AND message_id = ?
                                        """,
                                        (chat_id, message_id),
                                    )
                                    conn.commit()
                                print(f"⚠️  Пустая транскрипция {operation_id}: {status[6:]} results → [ПУСТО]")
                            elif status.startswith("error:"):
                                print(f"[WARN] Ошибка проверки {operation_id}: {status[6:]}")
                            return "empty"
                    else:
                        print(f"⏳ Ожидание: {link} (op: {operation_id})")
                        return "pending"
            
            # Запускаем все проверки параллельно
            check_tasks = [
                check_one_operation(chat_id, message_id, operation_id)
                for chat_id, message_id, operation_id in pending_ops
            ]
            results = await asyncio.gather(*check_tasks, return_exceptions=True)
            done_count = sum(1 for r in results if r == "done")
            pending_count = sum(1 for r in results if r == "pending")
            print(f"📊 Проверено: {done_count} готовы, {pending_count} ожидают")
        
        if args.check_only:
            print("Режим --check-only, новые файлы не отправляются")
            return
        
        # Загружаем список заблокированных чатов
        denied_ids = load_denied_ids(conn)
        if denied_ids:
            print(f"🚫 Заблокировано чатов: {len(denied_ids)}")
        
        # Теперь отправляем новые файлы
        all_media = select_pending_media(conn, limit=args.limit, denied_ids=denied_ids)
        print(f"📊 Выбрано {len(all_media)} медиа из БД (limit={args.limit})")
        
        pending = []
        skipped_nosound = 0
        skipped_not_media = 0
        
        for row in all_media:
            is_media, has_sound = is_audio_or_video(row[2])  # row[2] = json
            if is_media:
                if has_sound:
                    pending.append(row)  # row = (chat_id, message_id, json, media_path, chat_name, date)
                else:
                    skipped_nosound += 1
                    # Помечаем в БД что это файл без звука
                    conn.execute(
                        "UPDATE messages SET transcript = '[БЕЗ ЗВУКА]' WHERE chat_id = ? AND message_id = ?",
                        (row[0], row[1])
                    )
            else:
                skipped_not_media += 1
        
        conn.commit()
        
        print(f"📋 Фильтрация:")
        print(f"   Аудио/видео со звуком: {len(pending)}")
        print(f"   Видео без звука (nosound): {skipped_nosound}")
        print(f"   Не аудио/видео: {skipped_not_media}")
        
        if not pending:
            print("Нет новых медиа для транскрибации")
            return
        
        print(f"Найдено {len(pending)} новых медиа для транскрибации")
        print(f"🚀 Параллельная обработка: 10 потоков")
        print()
        
        # Создаем semaphore для ограничения параллелизма и lock для БД
        semaphore = asyncio.Semaphore(10)
        db_lock = asyncio.Lock()
        
        # Создаем задачи для всех файлов
        tasks = []
        for idx, (chat_id, message_id, json_str, media_path, chat_name, msg_date) in enumerate(pending, 1):
            task = process_one_file(
                idx=idx,
                total=len(pending),
                chat_id=chat_id,
                message_id=message_id,
                json_str=json_str,
                media_path=media_path,
                chat_name=chat_name,
                msg_date=msg_date,
                media_dir=media_dir,
                tbank_client=tbank_client,
                conn=conn,
                semaphore=semaphore,
                db_lock=db_lock
            )
            tasks.append(task)
        
        # Запускаем все задачи параллельно
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Подсчитываем результаты
        sent = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "sent")
        errors = sum(1 for r in results if isinstance(r, Exception))
        print()
        print(f"✅ Отправлено: {sent}/{len(pending)}")
        if errors:
            print(f"❌ Ошибок: {errors}")
    
    finally:
        conn.close()
        # Закрываем лог и восстанавливаем stdout
        if 'tee_logger' in locals():
            sys.stdout = tee_logger.terminal
            sys.stderr = tee_logger.terminal
            tee_logger.close()
            print(f"✅ Лог сохранен: {log_file}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))

