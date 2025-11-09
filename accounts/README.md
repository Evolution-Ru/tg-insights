# Accounts Directory Structure

Директория `accounts/` содержит конфигурацию и данные для каждого аккаунта.

## Структура

```
accounts/
├── example.env          # Пример файла с переменными окружения
└── {account_name}/     # Директория аккаунта (например: ychukaev)
    ├── .env            # Переменные окружения (не коммитится)
    ├── messages.sqlite  # База данных сообщений (не коммитится)
    ├── session_*.session # Сессии Telegram (не коммитится)
    ├── media/          # Медиа файлы (не коммитится)
    └── .batches/       # Кеш батчей OpenAI (не коммитится)
```

## Настройка нового аккаунта

1. Создайте директорию для аккаунта:
   ```bash
   mkdir -p accounts/my_account
   ```

2. Скопируйте пример файла окружения:
   ```bash
   cp accounts/example.env accounts/my_account/.env
   ```

3. Отредактируйте `.env` файл и добавьте свои ключи:
   ```bash
   nano accounts/my_account/.env
   ```

4. Запустите экспорт сообщений:
   ```bash
   python scripts/telegram/export.py --account my_account
   ```

## Переменные окружения

См. `accounts/example.env` для примера всех необходимых переменных.

## Безопасность

Все чувствительные файлы (`.env`, `messages.sqlite`, `session_*.session`, `media/`) автоматически исключены из git через `.gitignore`.

