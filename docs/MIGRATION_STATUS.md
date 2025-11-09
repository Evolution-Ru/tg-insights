# Статус миграции: tg-analyz → ai-pmtool

## ✅ Выполнено

### 1. Создана новая структура проекта

Создана полная структура директорий согласно плану рефакторинга:
- `sources/` - источники данных
- `pipeline/` - пайплайн обработки
- `sync/` - синхронизация
- `shared/` - общие компоненты
- `scripts/` - скрипты запуска
- `docs/` - документация

### 2. Мигрированы shared модули

**shared/ai/**
- ✅ `gpt5_client.py` - клиент GPT-5 с поддержкой `responses.create()` API
- ✅ `response_parser.py` - парсинг ответов GPT-5

**shared/utils/**
- ✅ `db.py` - работа с БД (get_db_connection, get_all_messages_from_chats, и др.)
- ✅ `formatting.py` - форматирование сообщений

**shared/cache/**
- ✅ `manager.py` - менеджер кешей

### 3. Начата миграция sources/telegram

- ✅ `exporter.py` - экспорт сообщений из Telegram (скопирован из `scripts/messages/export_all.py`, обновлены пути)
- ✅ `models.py` - модели данных Telegram
- ✅ `db.py` - работа с БД Telegram

### 4. Созданы скрипты запуска

- ✅ `scripts/telegram/export.py` - скрипт запуска экспорта Telegram

### 5. Создана документация

- ✅ `README.md` - основная документация проекта
- ✅ `docs/MIGRATION.md` - руководство по миграции

## 🔄 В процессе

- Миграция `sources/asana/`
- Миграция `pipeline/telegram/` (summarization, vectorization, extraction, matching)
- Миграция `pipeline/asana/` (summarization, vectorization, extraction, matching)
- Миграция `sync/` модуля

## 📋 Следующие шаги

### Приоритет 1: Завершить sources/

1. **sources/asana/**
   - Скопировать `scripts/analysis/sync/api/asana_mcp_helpers.py` → `sources/asana/api_client.py`
   - Создать `sources/asana/exporter.py` и `sources/asana/models.py`
   - Обновить импорты

### Приоритет 2: Мигрировать pipeline/telegram/

1. **summarization/**
   - `scripts/analysis/compression/compression.py` → `pipeline/telegram/summarization/compressor.py`
   - `scripts/analysis/compression/chunking.py` → `pipeline/telegram/summarization/chunking.py`
   - `scripts/analysis/compression/batch_processing.py` → `pipeline/telegram/summarization/batch_processor.py`

2. **vectorization/**
   - `scripts/analysis/embeddings/embeddings.py` → `pipeline/telegram/vectorization/embeddings.py`

3. **extraction/**
   - `scripts/analysis/extraction/tasks.py` → `pipeline/telegram/extraction/tasks.py`
   - `scripts/analysis/extraction/projects.py` → `pipeline/telegram/extraction/projects.py`
   - `scripts/analysis/extraction/grouping.py` → `pipeline/telegram/extraction/grouping.py`

4. **matching/**
   - `scripts/analysis/sync/utils/matchers/time_window.py` → `pipeline/telegram/matching/time_windows.py`
   - `scripts/analysis/sync/utils/matchers/similarity_calculator.py` → `pipeline/telegram/matching/similarity.py`

### Приоритет 3: Мигрировать pipeline/asana/

Аналогично pipeline/telegram, но для Asana данных.

### Приоритет 4: Мигрировать sync/

Разбить большой файл `scripts/analysis/sync/core/asana_sync.py` на:
- `sync/matcher.py` - логика сопоставления
- `sync/orchestrator.py` - оркестрация синхронизации
- `sync/transformer.py` - преобразование данных
- `sync/reporter.py` - генерация отчетов

### Приоритет 5: Обновить scripts/

Создать скрипты запуска с правильными импортами:
- `scripts/telegram/analyze.py`
- `scripts/telegram/extract.py`
- `scripts/asana/export.py`
- `scripts/asana/summarize.py`
- `scripts/sync/sync.py`

## 📝 Важные замечания

1. **Импорты** - все импорты должны быть обновлены на новую структуру:
   - `from scripts.analysis.*` → `from pipeline.telegram.*` или `from shared.*`
   - `from scripts.analysis.sync.*` → `from sync.*` или `from sources.asana.*`

2. **Пути** - все пути к файлам должны быть обновлены относительно новой структуры

3. **Тестирование** - после миграции каждого модуля проверять работу импортов и функциональность

4. **Кеши** - пути к кешам должны быть обновлены или сохранены совместимость

## 🚀 Как продолжить миграцию

1. Изучить `REFACTORING_PLAN.md` для понимания маппинга файлов
2. Следовать шаблону миграции из `docs/MIGRATION.md`
3. Мигрировать модули поэтапно, проверяя работу после каждого этапа
4. Обновлять TODO список по мере выполнения

