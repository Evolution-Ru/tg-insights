# Использование GPT-5 в проекте

## ⚠️ КРИТИЧЕСКИ ВАЖНО

**GPT-5 - это ЕДИНСТВЕННАЯ модель для всех задач в проекте. GPT-4 больше НЕ используется.**

**Всегда используй `client.responses.create()` вместо `client.chat.completions.create()`**

## Основные отличия GPT-5 от GPT-4

### 1. API метод

**GPT-5 использует `responses.create()` вместо `chat.completions.create()`**

```python
# ❌ СТАРЫЙ способ (GPT-4) - НЕ ИСПОЛЬЗОВАТЬ
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."}
    ],
    temperature=0.3
)
text = response.choices[0].message.content

# ✅ НОВЫЙ способ (GPT-5) - ВСЕГДА ИСПОЛЬЗОВАТЬ
response = client.responses.create(
    model="gpt-5",
    input=[
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."}
    ],
    reasoning={"effort": "medium"}
)
# Извлекаем текст из ответа
text = ""
if getattr(response, "output", None):
    chunks = []
    for item in response.output:
        if getattr(item, "content", None):
            for c in item.content:
                if getattr(c, "text", None):
                    chunks.append(c.text)
    text = "\n".join(chunks).strip()
```

### 2. Параметры

**GPT-5 НЕ поддерживает:**
- ❌ `temperature` (удалить)
- ❌ `top_p` (удалить)
- ❌ `logprobs` (удалить)
- ❌ `response_format` (удалить, JSON указываем в промпте)

**GPT-5 использует:**
- ✅ `reasoning={"effort": "..."}` - уровень усилий рассуждения
  - `"minimal"` - минимальные рассуждения, быстрый ответ
  - `"low"` - низкий уровень рассуждений
  - `"medium"` - средний уровень (рекомендуется для большинства задач)
  - `"high"` - высокий уровень, глубокие рассуждения (медленнее, но качественнее)

- ✅ `verbosity` (опционально) - уровень детализации ответа
  - `"low"` - краткие ответы
  - `"medium"` - средняя детализация
  - `"high"` - подробные ответы

### 3. Структура ответа

Ответ GPT-5 имеет другую структуру:

```python
response = client.responses.create(...)

# Ответ находится в response.output (список)
# Каждый элемент имеет content (список)
# Каждый content имеет text (строка)

def extract_text_from_response(response) -> str:
    """Извлекает текст из ответа GPT-5"""
    if not getattr(response, "output", None):
        return ""
    
    chunks = []
    for item in response.output:
        if getattr(item, "content", None):
            for c in item.content:
                if getattr(c, "text", None):
                    chunks.append(c.text)
    return "\n".join(chunks).strip()
```

### 4. JSON ответы

Для получения JSON ответов, указываем формат в промпте (не через `response_format`):

```python
prompt = f"""...
Верни результат в формате JSON:
{{
  "field1": "value1",
  "field2": "value2"
}}"""

response = client.responses.create(
    model="gpt-5",
    input=[
        {"role": "system", "content": "Отвечай только валидным JSON."},
        {"role": "user", "content": prompt}
    ],
    reasoning={"effort": "medium"}
)

# Парсим JSON из текста (может быть обернут в markdown)
response_text = extract_text_from_response(response)
if response_text.startswith("```"):
    # Убираем markdown код блоки
    lines = response_text.split("\n")
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines[-1].strip() == "```":
        lines = lines[:-1]
    response_text = "\n".join(lines)

result = json.loads(response_text)
```

## Примеры использования

### Простое текстовое сжатие

```python
def compress_text(text: str) -> str:
    response = client.responses.create(
        model="gpt-5",
        input=[
            {"role": "system", "content": "Ты помогаешь сжимать тексты."},
            {"role": "user", "content": f"Сожми этот текст:\n\n{text}"}
        ],
        reasoning={"effort": "low"}  # Быстрое сжатие
    )
    
    return extract_text_from_response(response)

def extract_text_from_response(response) -> str:
    """Извлекает текст из ответа GPT-5"""
    if not getattr(response, "output", None):
        return ""
    
    chunks = []
    for item in response.output:
        if getattr(item, "content", None):
            for c in item.content:
                if getattr(c, "text", None):
                    chunks.append(c.text)
    return "\n".join(chunks).strip()
```

### Извлечение структурированных данных

```python
def extract_tasks(text: str) -> Dict:
    prompt = f"""Извлеки задачи из текста:
{text}

Верни JSON:
{{
  "tasks": [
    {{"title": "...", "assignee": "...", "deadline": "..."}}
  ]
}}"""
    
    response = client.responses.create(
        model="gpt-5",
        input=[
            {"role": "system", "content": "Отвечай только валидным JSON."},
            {"role": "user", "content": prompt}
        ],
        reasoning={"effort": "medium"}  # Средний уровень для качественного извлечения
    )
    
    response_text = extract_text_from_response(response)
    # Убираем markdown если есть
    response_text = clean_markdown_code_blocks(response_text)
    
    return json.loads(response_text)
```

## Рекомендации по выбору reasoning_effort

- **`"minimal"`** - простые задачи, быстрые ответы, низкая стоимость
- **`"low"`** - стандартные задачи, баланс скорости и качества
- **`"medium"`** - сложные задачи, извлечение структурированных данных, анализ (рекомендуется)
- **`"high"`** - очень сложные задачи, требующие глубокого анализа

## Миграция с GPT-4 на GPT-5

1. ✅ Заменить `client.chat.completions.create()` на `client.responses.create()`
2. ✅ Заменить `messages=` на `input=`
3. ✅ Удалить `temperature`, `top_p`, `response_format`
4. ✅ Добавить `reasoning={"effort": "medium"}`
5. ✅ Изменить извлечение текста из ответа (см. примеры выше)

## Дополнительная информация

- GPT-5 поддерживает до 272,000 входных токенов и 128,000 выходных
- Мультимодальность: обработка текста и изображений
- Автоматический выбор между "быстрыми" и "углубленными" режимами
- Тарифы: от $1.25 за миллион входных токенов

## Ссылки

- [Официальная документация OpenAI GPT-5](https://platform.openai.com/docs/models/gpt-5)
- Примеры использования в проекте: `scripts/messages/summarizer/summarize.py`
- Примеры использования в проекте: `scripts/analyze_farma_tasks.py`
