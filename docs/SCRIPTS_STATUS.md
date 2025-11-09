# Статус миграции scripts/

## ✅ Выполнено

### scripts/telegram/
- ✅ `export.py` - экспорт сообщений из Telegram в SQLite
- ✅ `analyze.py` - главный скрипт анализа Telegram переписок и извлечения задач

### scripts/sync/
- ✅ `sync.py` - скрипт синхронизации задач между Telegram и Asana
- ✅ `check_batches.py` - проверка статусов батчей OpenAI и обработка завершенных

### scripts/asana/
- ✅ Структура создана (пока пустая)

## 📝 Обновленные импорты

Все импорты обновлены на новую структуру:
- `from shared.utils.db import ...`
- `from shared.utils.formatting import ...`
- `from shared.ai.gpt5_client import ...`
- `from pipeline.telegram.summarization.compress import ...`
- `from pipeline.telegram.vectorization.embeddings import ...`
- `from pipeline.telegram.extraction.tasks import ...`
- `from pipeline.telegram.extraction.projects import ...`
- `from pipeline.telegram.extraction.grouping import ...`
- `from pipeline.asana.summarization.summarizer import ...`
- `from sync.orchestrator import ...`

## ⚠️ Требуется

1. Протестировать работу всех скриптов после установки зависимостей
2. Создать скрипты для Asana (если нужны)
3. Обновить пути к результатам в analyze.py (если нужно)

