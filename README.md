# Telegram Transcript Pipeline

Платформа для автоматической обработки, транскрибации и анализа переписок из Telegram.

## ✨ Возможности

- 📥 **Экспорт сообщений** из Telegram в SQLite базу данных
- 🎙️ **Транскрибация аудио/видео** через T-bank Speech-to-Text API
- 📝 **Суммаризация диалогов** через OpenAI API (batch processing)
- 📊 **Анализ переписок** с автоматической генерацией инсайтов
- 💾 **Скачивание медиа** с поддержкой параллельной обработки
- ⚡ **Асинхронная обработка** для высокой производительности

## 📜 Лицензия

MIT License - используйте как хотите, в любых целях, без ограничений.

## 📖 Содержание

1. [Быстрый старт](#-быстрый-старт)
2. [Структура проекта](#-структура-проекта)
3. [Транскрибация (STT)](#-транскрибация-stt)
4. [Обработка сообщений](#-обработка-сообщений)
5. [Скачивание медиа](#-скачивание-медиа)
6. [Автозапуск](#-автозапуск)
7. [База данных](#-база-данных)
8. [Troubleshooting](#-troubleshooting)

---

## 🚀 Быстрый старт

### 1. Установка зависимостей

```bash
# Клонирование репозитория
git clone https://github.com/your-username/tg-transcript.git
cd tg-transcript

# Настройка виртуального окружения
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# или
.venv\Scripts\activate  # Windows

# Установка зависимостей
pip install -r requirements.txt
```

### 2. Настройка конфигурации

```bash
# Создать .env файл из примера
cp .env.example .env

# Отредактировать .env и добавить свои API ключи
nano .env  # или используйте любой редактор
```

**Необходимые API ключи:**
- **Telegram API**: Получить на https://my.telegram.org/apps
- **T-bank STT API**: Получить на https://www.tbank.ru/openapi/
- **OpenAI API**: Получить на https://platform.openai.com/api-keys

### 3. Создание аккаунта для экспорта

```bash
# Создать директорию для вашего аккаунта
mkdir -p data/accounts/your_account

# Скопировать .env в директорию аккаунта
cp .env data/accounts/your_account/.env
```

### 4. Запуск обработки сообщений

```bash
# Экспорт и обработка сообщений
python scripts/messages/process_all.py --account your_account --use-batch

# Транскрибация аудио/видео
python scripts/stt/stt.tbank.py --account your_account --limit 100

# Скачивание медиа за последние 6 месяцев
python scripts/media/download.py
```

---

## 📦 Структура проекта

```
tg-insights/
├── data/                     # 💾 Данные
│   └── accounts/            # Аккаунты, БД, медиа
│       └── your_account/
│           ├── messages.sqlite
│           ├── media/
│           └── .env
├── scripts/                  # 🔧 Скрипты
│   ├── messages/            # Экспорт и обработка сообщений
│   │   ├── export_all.py   # Экспорт из Telegram
│   │   ├── process_all.py  # Обработка и суммаризация
│   │   ├── send.py         # Отправка сообщений
│   │   └── summarizer/     # Batch суммаризация
│   ├── media/              # Скачивание медиа
│   │   └── download.py     # Скачивание аудио/видео
│   └── stt/                # Транскрибация
│       ├── stt.tbank.py    # T-bank STT
│       └── TbankClient.py  # T-bank API клиент
├── logs/                     # 📝 Все логи
│   ├── process_loop.log
│   ├── launchd.log
│   └── launchd.error.log
├── .venv/                    # Virtual environment (скрытая)
├── requirements.txt          # Зависимости
└── README.md                 # Этот файл
```

---

## 🎤 Транскрибация (STT)

### T-банк STT (рекомендуется)

**Стоимость:** 0.3 коп/сек = 108 руб/час  
**Качество:** хорошее для русского языка  
**Скорость:** 10 потоков параллельно

```bash
# С автоматическим логированием (рекомендуется)
bash scripts/stt/run_tbank.sh --account your_account --limit 100

# Или напрямую (флаг -u обязателен для логов!)
python -u scripts/stt/stt.tbank.py --account your_account --limit 100

# Проверить статус отложенных транскрипций
python scripts/stt/stt.tbank.py --account your_account --check-only

# Указать пути вручную (вместо --account)
python scripts/stt/stt.tbank.py \
  --db data/accounts/your_account/messages.sqlite \
  --media-dir data/accounts/your_account/media \
  --limit 100
```

**Что происходит:**
1. **Фильтрация:** Пропускает заблокированные чаты (dialog_denied)
2. **Конвертация:** Преобразует аудио/видео в WAV 16kHz mono (требование T-банк)
3. **Параллельная отправка:** 10 файлов одновременно в T-банк API
4. **Асинхронность:** Сохраняет `operation_id` в БД и не ждёт результатов
5. **Проверка:** При следующем запуске проверяет статус и забирает готовые транскрипции

**Особенности:**
- Автоматически пропускает видео без звука
- Пропускает файлы >5 минут
- Логи: `logs/stt_tbank_YYYYMMDD_HHMMSS.log`

### OpenAI Whisper (дороже, но надёжнее)

**Стоимость:** 3.6 коп/сек = 1,296 руб/час  
**Качество:** отличное, работает всегда

```bash
python scripts/stt/stt.whisper.py \
  --db data/accounts/your_account/messages.sqlite \
  --limit 100
```

### Сравнение

| Сервис | Цена | 1 час | Скорость | Качество |
|--------|------|-------|----------|----------|
| T-банк | 0.3 коп/с | 108₽ | Средняя | Хорошее |
| Whisper | 3.6 коп/с | 1,296₽ | Быстрая | Отличное |

**Экономия:** T-банк в **12 раз дешевле**!

### Настройка API ключей

В `data/accounts/your_account/.env`:
```bash
# T-банк STT
TBANK_API_KEY=your_key
TBANK_SECRET_KEY=your_secret

# OpenAI Whisper
OPENAI_API_KEY=sk-...

# Telegram
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION_STRING=your_session
```

---

## 📬 Обработка сообщений

### Разовый запуск

```bash
python scripts/messages/process_all.py \
  --account your_account \
  --use-batch \
  --max-dialogs 10000
```

**Параметры:**
- `--account` - имя аккаунта (папка в data/accounts/)
- `--use-batch` - использовать batch API OpenAI (дешевле)
- `--max-dialogs` - макс. диалогов для обработки
- `--limit` - лимит сообщений

### Первичный экспорт

```bash
# Выгрузить все сообщения из Telegram в БД
python scripts/messages/export_all.py \
  --account your_account \
  --all-dialogs
```

### Суммаризация

Система автоматически суммаризует диалоги через OpenAI batch API:

1. Формирует запросы на суммаризацию
2. Отправляет batch в OpenAI (дешевле на 50%)
3. Ждёт результаты (до 24 часов)
4. Сохраняет в БД

---

## 📥 Скачивание медиа

```bash
# Скачать аудио/видео за последние 6 месяцев
# Фильтр: только < 5 минут, без картинок
# Параллельная загрузка: 20 потоков одновременно
python scripts/media/download.py
```

**Что происходит:**
1. Выбирает медиа за последние 6 месяцев из БД
2. Фильтрует: только аудио/видео (пропускает картинки)
3. Проверяет длительность через Telegram API **БЕЗ скачивания**
4. Пропускает файлы >5 минут
5. **Скачивает 20 файлов параллельно** с обработкой FloodWait
6. Сохраняет в `data/accounts/{account}/media/`
7. Обновляет `media_path` в БД

**Особенности:**
- Параллельная загрузка: 20 потоков одновременно
- Автоматическая обработка Telegram rate limits (FloodWaitError)
- Показывает размер файла и время скачивания
- Безопасно для долгой работы (часы)

**Скачанные файлы:**
```
data/accounts/your_account/media/
├── {chat_id}_{message_id}.oga  # Аудио
├── {chat_id}_{message_id}.mp4  # Видео
└── {chat_id}_{message_id}.wav  # Конвертированные для STT
```

---

## ⚙️ Автозапуск

Для автоматической обработки сообщений можно настроить периодический запуск:

**macOS:** launchd
```bash
# Создайте plist файл ~/Library/LaunchAgents/com.tginsights.process.plist
# со запуском scripts/messages/process_all.py
```

**Linux:** cron или systemd
```bash
# Добавьте задачу в crontab (каждые 6 часов)
0 */6 * * * cd /path/to/tg-insights && .venv/bin/python scripts/messages/process_all.py --account your_account
```

**Windows:** Task Scheduler
- Создайте задачу для запуска Python скрипта

### Логи

```bash
# Основной лог обработки
tail -f logs/process.log

# Логи launchd
tail -f logs/launchd.log
tail -f logs/launchd.error.log
```

**Как работает автозапуск:**
1. launchd запускает `run_process_loop.sh` при загрузке системы
2. Скрипт в цикле запускает `process_all.py` каждые 5 минут
3. Обрабатывает новые сообщения, транскрибирует медиа, суммаризирует

---

## 📊 База данных

SQLite база находится в `data/accounts/{account}/messages.sqlite`

### Основные таблицы

```sql
-- Сообщения
messages (
  chat_id,          -- ID чата
  message_id,       -- ID сообщения
  date,             -- Дата сообщения
  message,          -- Текст сообщения
  media_path,       -- Путь к скачанному медиа
  transcript,       -- Текст транскрибации
  transcript_model, -- Модель STT (tbank/whisper)
  duration_seconds, -- Длительность медиа
  tbank_operation_id -- ID операции T-банк
)

-- Пользователи
users (
  user_id,
  first_name,
  username,
  phone
)
```

### Полезные запросы

```bash
# Статистика по сообщениям
sqlite3 data/accounts/your_account/messages.sqlite \
  "SELECT COUNT(*) FROM messages"

# Непротранскрибированные медиа
sqlite3 data/accounts/your_account/messages.sqlite \
  "SELECT COUNT(*) FROM messages 
   WHERE media_path IS NOT NULL 
   AND transcript IS NULL"

# Размер БД
du -h data/accounts/your_account/messages.sqlite
```

---

## 🔧 Troubleshooting

### Ошибка: "No module named 'telethon'"

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Ошибка: "Could not find .env"

```bash
# Проверить что .env существует
ls -la data/accounts/your_account/.env

# Создать из примера
cp data/accounts/your_account/.env.example data/accounts/your_account/.env
```

### Ошибка: "OPENAI_API_KEY not set"

Добавить в `data/accounts/your_account/.env`:
```bash
OPENAI_API_KEY=sk-...
```

### Скрипт зависает на скачивании медиа

**Проблема:** пытается скачать файл, который уже есть

**Решение:**
```bash
# Остановить (Ctrl+C)
# Проверить количество файлов
ls data/accounts/your_account/media/ | wc -l

# Проверить записи в БД
sqlite3 data/accounts/your_account/messages.sqlite \
  "SELECT COUNT(*) FROM messages WHERE media_path IS NOT NULL"
```

### T-банк возвращает пустой результат

**Проблема:** неправильный формат аудио (OPUS вместо LINEAR16)

**Решение:** скрипт автоматически конвертирует через FFmpeg
```bash
# Проверить FFmpeg
ffmpeg -version

# Установить если нет (macOS)
brew install ffmpeg
```

### launchd не запускается

```bash
# Проверить синтаксис plist
plutil -lint ~/Library/LaunchAgents/com.tginsights.process_all.plist

# Проверить логи
cat logs/launchd.error.log

# Права на выполнение
chmod +x scripts/messages/run_process_loop.sh
```

### База данных заблокирована

**Проблема:** несколько процессов работают с БД одновременно

**Решение:**
```bash
# Найти процессы
ps aux | grep process_all

# Убить лишние
pkill -f process_all.py

# Перезапустить
launchctl kickstart -k gui/$(id -u)/com.tginsights.process_all
```

### Очистка старых логов

```bash
# Очистить логи
> logs/process_loop.log
> logs/launchd.log
> logs/launchd.error.log
```

---

## 📝 Полезные команды

```bash
# Активация окружения
source .venv/bin/activate

# Проверка кода
flake8 scripts/

# Тест обработки (10 сообщений)
python scripts/messages/process_all.py \
  --account your_account \
  --use-batch \
  --limit 10

# Тест STT (5 файлов)
python scripts/stt/stt.tbank.py \
  --db data/accounts/your_account/messages.sqlite \
  --limit 5
```

---

## 🔐 API ключи

Все ключи хранятся в `data/accounts/{account}/.env`:

```bash
# Telegram
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION_STRING=your_session

# OpenAI Whisper
OPENAI_API_KEY=sk-...

# T-банк STT
TBANK_API_KEY=your_tbank_key
TBANK_SECRET_KEY=your_tbank_secret
```

---

## 📚 Ссылки

- [T-банк STT API](https://www.tbank.ru/kassa/dev/speech-to-text/)
- [OpenAI Whisper API](https://platform.openai.com/docs/guides/speech-to-text)
- [Telethon Documentation](https://docs.telethon.dev/)

---

## 📜 Лицензия

Open-source проект для работы с Telegram данными.
