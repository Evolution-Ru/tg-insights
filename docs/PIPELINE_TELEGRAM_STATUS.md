# Статус миграции pipeline/telegram/

## ✅ Выполнено

### summarization/
- ✅ `chunking.py` - разбиение на части по датам
- ✅ `compressor.py` - сжатие чанков через GPT-5
- ✅ `batch_processor.py` - Batch API обработка
- ✅ `sliding_window.py` - скользящая выжимка
- ✅ `compress.py` - главная функция сжатия

### vectorization/
- ✅ `embeddings.py` - генерация эмбеддингов

### extraction/
- ✅ `tasks.py` - извлечение задач
- ✅ `projects.py` - извлечение проектов
- ✅ `grouping.py` - группировка и дедупликация

### matching/
- ✅ `semantic_search.py` - семантический поиск (drilldown)

## 📝 Обновленные импорты

Все импорты обновлены на новую структуру:
- `from shared.ai.gpt5_client import ...`
- `from shared.utils.db import ...`
- `from pipeline.telegram.vectorization.embeddings import ...`
- `from pipeline.telegram.matching.semantic_search import ...`

## ⚠️ Требуется

1. Мигрировать `time_windows.py` и `similarity.py` в `matching/`
2. Создать `vectorization/cache.py` для кеша эмбеддингов
3. Протестировать работу всех модулей после установки зависимостей

