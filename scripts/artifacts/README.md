# Система извлечения артефактов коммуникаций

Модуль для интеллектуального извлечения структурированных артефактов (обязательства, запросы, решения, дедлайны) из Telegram-диалогов.

## 🎯 Цель проекта

Автоматически находить и отслеживать важные элементы коммуникаций:
- Обязательства ("сделаю до пятницы")
- Запросы ("нужна помощь с X")
- Договоренности ("встречаемся завтра в 15:00")
- Решения ("выбрали вариант А")
- Дедлайны и их статусы

## 📐 Архитектура

### Многоуровневая воронка обработки

```
┌─────────────────────────────────────────────────────────┐
│ Уровень 1: СКРИНИНГ КОНТЕКСТОВ (дешево, массово)       │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Вход: dialog_contexts (~1000 контекстов)            │ │
│ │ Модель: GPT-4o-mini (batch API)                     │ │
│ │ Промпт: "Есть ли артефакты? Да/Нет + типы"         │ │
│ │ Выход: 20% помечено как "есть артефакты"           │ │
│ │ Стоимость: ~$0.15 за 1000 контекстов               │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Уровень 2: ДЕТАЛЬНОЕ ИЗВЛЕЧЕНИЕ (точно, выборочно)     │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Вход: Исходные сообщения из "подозрительных"       │ │
│ │       контекстов (50-100 сообщений)                │ │
│ │ Модель: GPT-4o (batch API)                         │ │
│ │ Промпт: "Извлеки точные формулировки артефактов"   │ │
│ │ Выход: Структурированные артефакты с метаданными   │ │
│ │ Стоимость: ~$0.50 за 100 контекстов                │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Уровень 3: ПРОВЕРКА СТАТУСОВ (для артефактов с дедлайнами) │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Вход: Артефакт + сообщения после дедлайна          │ │
│ │ Модель: GPT-4o-mini                                 │ │
│ │ Промпт: "Было ли выполнено обязательство?"         │ │
│ │ Выход: Статус (выполнено/просрочено/в процессе)   │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## 🗄️ Структура данных

### Таблица: `artifact_screening` (Уровень 1)
```sql
CREATE TABLE artifact_screening (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id INTEGER NOT NULL,           -- FK to dialog_contexts.id
    
    -- Результаты скрининга
    has_artifacts INTEGER DEFAULT 0,       -- 0 = нет, 1 = да
    artifact_types TEXT,                   -- JSON: ["commitment", "request"]
    confidence REAL,                       -- 0.0 - 1.0
    
    -- Метаданные
    screened_at TEXT DEFAULT (datetime('now')),
    model_name TEXT DEFAULT 'gpt-4o-mini',
    
    FOREIGN KEY (context_id) REFERENCES dialog_contexts(id)
);
```

### Таблица: `artifacts` (Уровень 2)
```sql
CREATE TABLE artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Связь с источниками
    screening_id INTEGER,                  -- FK to artifact_screening.id
    chat_id INTEGER NOT NULL,
    message_date_from TEXT,                -- начало окна сообщений
    message_date_to TEXT,                  -- конец окна сообщений
    
    -- Тип артефакта
    artifact_type TEXT NOT NULL,           -- commitment, request, decision, deadline, agreement
    
    -- Содержание
    summary TEXT NOT NULL,                 -- краткое описание
    full_text TEXT,                        -- полная формулировка из сообщений
    
    -- Участники
    who TEXT,                              -- кто создал/обязался (имя или ID)
    whom TEXT,                             -- кому адресовано (может быть NULL)
    
    -- Временные метки
    mentioned_at TEXT,                     -- когда было упомянуто
    due_date TEXT,                         -- дедлайн (если есть)
    
    -- Статус
    status TEXT DEFAULT 'open',            -- open, fulfilled, pending, blocked, cancelled
    priority TEXT,                         -- high, medium, low
    
    -- Метаданные извлечения
    extracted_at TEXT DEFAULT (datetime('now')),
    confidence REAL,                       -- уверенность модели
    model_name TEXT DEFAULT 'gpt-4o',
    
    FOREIGN KEY (screening_id) REFERENCES artifact_screening(id),
    FOREIGN KEY (chat_id) REFERENCES messages(chat_id)
);
```

### Таблица: `artifact_status_checks` (Уровень 3)
```sql
CREATE TABLE artifact_status_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id INTEGER NOT NULL,
    
    -- Расширенное окно для проверки
    checked_from TEXT,                     -- начало окна проверки
    checked_to TEXT,                       -- конец окна проверки
    
    -- Результат проверки
    status TEXT NOT NULL,                  -- fulfilled, pending, blocked, cancelled
    status_reason TEXT,                    -- объяснение статуса
    evidence TEXT,                         -- цитаты из сообщений
    
    needs_manual_review INTEGER DEFAULT 0,
    
    -- Метаданные
    checked_at TEXT DEFAULT (datetime('now')),
    model_name TEXT DEFAULT 'gpt-4o-mini',
    
    FOREIGN KEY (artifact_id) REFERENCES artifacts(id)
);
```

## 📊 Типы артефактов

### 1. Commitment (Обязательство)
```json
{
    "artifact_type": "commitment",
    "summary": "Отправить отчет по проекту X",
    "who": "Юрий Чукаев",
    "whom": "Клиент ООО Ромашка",
    "due_date": "2024-11-01",
    "status": "open"
}
```

### 2. Request (Запрос)
```json
{
    "artifact_type": "request",
    "summary": "Запрос доступа к CRM",
    "who": "Менеджер Иван",
    "whom": "Юрий Чукаев",
    "status": "pending"
}
```

### 3. Decision (Решение)
```json
{
    "artifact_type": "decision",
    "summary": "Решили использовать PostgreSQL вместо MySQL",
    "who": "Команда разработки",
    "mentioned_at": "2024-10-25T14:30:00"
}
```

### 4. Agreement (Договоренность)
```json
{
    "artifact_type": "agreement",
    "summary": "Встреча каждый понедельник в 10:00",
    "who": "Юрий и Амина",
    "status": "active"
}
```

### 5. Deadline (Дедлайн)
```json
{
    "artifact_type": "deadline",
    "summary": "Запуск новой версии сайта",
    "due_date": "2024-11-15",
    "status": "pending"
}
```

## 🚀 Использование

### Шаг 1: Скрининг всех контекстов
```bash
python scripts/artifacts/screen.py --account ychukaev --batch
```

Результат:
```
✅ Обработано контекстов: 1000
🎯 Найдено артефактов: 234 (23.4%)
📊 По типам:
   - commitments: 89
   - requests: 67
   - decisions: 45
   - deadlines: 33
```

### Шаг 2: Извлечение деталей
```bash
python scripts/artifacts/extract.py --account ychukaev --top 100
```

Результат:
```
✅ Извлечено артефактов: 156
⚠️ Требуют внимания: 23 (с дедлайнами на этой неделе)
```

### Шаг 3: Проверка статусов
```bash
python scripts/artifacts/check_status.py --account ychukaev --overdue
```

Результат:
```
🔴 Просроченные обязательства: 5
🟡 Близкие дедлайны (3 дня): 8
🟢 Выполненные вовремя: 34
```

## 📈 Оценка стоимости

### Для 1000 контекстов (~1500 диалогов):

**Уровень 1 (Скрининг):**
- Токенов на вход: ~500 × 1000 = 500k tokens
- Токенов на выход: ~50 × 1000 = 50k tokens
- Стоимость (batch API): ~$0.075 + $0.015 = **$0.09**

**Уровень 2 (Детализация, 20% от скрининга):**
- 200 контекстов × 2000 токенов = 400k tokens in
- 200 × 200 токенов = 40k tokens out
- Стоимость (batch API): ~$1.00 + $1.20 = **$2.20**

**Уровень 3 (Статусы, ~50 артефактов с дедлайнами):**
- 50 × 1000 токенов = 50k tokens in
- 50 × 100 токенов = 5k tokens out
- Стоимость (batch API): ~$0.025 + $0.0015 = **$0.03**

**Итого: ~$2.32** за полный цикл обработки 1500 диалогов

## 🎛️ Конфигурация

### `config.yaml`
```yaml
screening:
  model: "gpt-4o-mini"
  batch_size: 1000
  confidence_threshold: 0.7
  
extraction:
  model: "gpt-4o"
  window_size: 100  # сообщений
  artifact_types:
    - commitment
    - request
    - decision
    - deadline
    - agreement
    
status_check:
  model: "gpt-4o-mini"
  check_window_days: 14  # дней после дедлайна
  auto_check_overdue: true
```

## 🔧 Компоненты системы

```
scripts/artifacts/
├── README.md              # этот файл
├── ARCHITECTURE.md        # детальная архитектура
├── config.yaml            # конфигурация
├── __init__.py
├── db.py                  # работа с БД
├── models.py              # датаклассы артефактов
├── prompts.py             # промпты для каждого уровня
├── screen.py              # Уровень 1: скрининг
├── extract.py             # Уровень 2: извлечение
├── check_status.py        # Уровень 3: проверка статусов
├── batch_utils.py         # работа с OpenAI Batch API
└── cli.py                 # CLI интерфейс
```

## 📝 Примеры

### Найти все просроченные обязательства
```python
from artifacts import db, models

artifacts = db.get_artifacts(
    artifact_type="commitment",
    status="pending",
    overdue=True
)

for a in artifacts:
    print(f"⚠️ {a.summary} (дедлайн: {a.due_date})")
    print(f"   От: {a.who}")
    print(f"   Чат: {a.chat_id}\n")
```

### Dashboard статистики
```python
stats = db.get_artifact_stats()
print(f"Всего артефактов: {stats['total']}")
print(f"Открытые обязательства: {stats['open_commitments']}")
print(f"Просроченные дедлайны: {stats['overdue_deadlines']}")
```

## 🎯 Roadmap

### Phase 1: MVP (текущая)
- [x] Проектирование архитектуры
- [ ] Создание схемы БД
- [ ] Скрининг контекстов (Уровень 1)
- [ ] Извлечение артефактов (Уровень 2)

### Phase 2: Статусы
- [ ] Проверка статусов (Уровень 3)
- [ ] Dashboard со статистикой
- [ ] CLI для быстрого доступа

### Phase 3: Интеграции
- [ ] Экспорт в Asana
- [ ] Напоминания в Telegram
- [ ] Web UI для управления

### Phase 4: ML улучшения
- [ ] Fine-tuning модели на собственных данных
- [ ] Автоматическая приоритизация
- [ ] Предсказание невыполнения обязательств

## 📚 Дополнительные документы

- [ARCHITECTURE.md](./ARCHITECTURE.md) - Детальная архитектура системы
- [PROMPTS.md](./PROMPTS.md) - Все промпты для моделей
- [API.md](./API.md) - API документация для разработчиков

