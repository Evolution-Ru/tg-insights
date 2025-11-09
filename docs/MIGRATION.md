# Руководство по миграции: tg-analyz → ai-pmtool

## Текущий статус миграции

### ✅ Выполнено

1. **Структура директорий** - создана новая структура проекта
2. **Shared модули** - мигрированы общие компоненты:
   - `shared/ai/gpt5_client.py` - клиент GPT-5
   - `shared/ai/response_parser.py` - парсинг ответов
   - `shared/utils/db.py` - работа с БД
   - `shared/utils/formatting.py` - форматирование
   - `shared/cache/manager.py` - менеджер кешей
3. **Sources/telegram** - начата миграция:
   - `sources/telegram/exporter.py` - экспорт сообщений (скопирован и обновлены пути)
   - `sources/telegram/models.py` - модели данных
   - `sources/telegram/db.py` - работа с БД

### 🔄 В процессе

- Миграция `sources/asana/`
- Миграция `pipeline/telegram/`
- Миграция `pipeline/asana/`
- Миграция `sync/`

### 📋 Следующие шаги

1. **Завершить миграцию sources/asana/**
   - Скопировать `scripts/analysis/sync/api/asana_mcp_helpers.py` → `sources/asana/api_client.py`
   - Создать `sources/asana/exporter.py` и `sources/asana/models.py`

2. **Мигрировать pipeline/telegram/**
   - `scripts/analysis/compression/` → `pipeline/telegram/summarization/`
   - `scripts/analysis/embeddings/` → `pipeline/telegram/vectorization/`
   - `scripts/analysis/extraction/` → `pipeline/telegram/extraction/`
   - Обновить импорты на `shared.*` и `sources.telegram.*`

3. **Мигрировать pipeline/asana/**
   - Аналогично pipeline/telegram, но для Asana

4. **Мигрировать sync/**
   - Разбить `scripts/analysis/sync/core/asana_sync.py` на модули
   - Обновить импорты

5. **Обновить scripts/**
   - Создать скрипты запуска с правильными импортами
   - Обновить пути к модулям

6. **Обновить документацию**
   - Создать `docs/ARCHITECTURE.md`
   - Создать `docs/PIPELINE.md`
   - Обновить README

## Инструкции по миграции модулей

### Шаблон миграции файла

1. Скопировать файл в новую структуру
2. Обновить импорты:
   - `from scripts.analysis.utils.*` → `from shared.utils.*` или `from shared.ai.*`
   - `from scripts.analysis.*` → `from pipeline.telegram.*` или `from pipeline.asana.*`
   - `from scripts.analysis.sync.*` → `from sync.*` или `from sources.asana.*`
3. Обновить пути к файлам (если используются Path)
4. Проверить работу импортов

### Пример обновления импортов

**Было:**
```python
from scripts.analysis.utils.gpt5_client import get_openai_client
from scripts.analysis.utils.db import get_db_connection
from scripts.analysis.compression import compress_thread_with_smart_model
```

**Стало:**
```python
from shared.ai.gpt5_client import get_openai_client
from shared.utils.db import get_db_connection
from pipeline.telegram.summarization import compress_thread_with_smart_model
```

## Проверка миграции

После миграции каждого модуля:

1. Проверить импорты: `python -c "import <module>"`
2. Запустить тесты (если есть)
3. Проверить работу скриптов запуска

## Важные замечания

- Все пути к файлам должны быть обновлены относительно новой структуры
- Импорты должны использовать новую структуру модулей
- Кеши и результаты должны оставаться в тех же местах (или обновлены пути)
- Сохранить всю функциональность при миграции

