#!/bin/bash
# Wrapper для запуска stt.tbank.py с правильным логированием

# Переходим в корень проекта
cd "$(dirname "$0")/../.."

# Создаем директорию для логов
mkdir -p logs

# Определяем имя лог-файла с датой
LOG_FILE="logs/stt_tbank_$(date +%Y%m%d_%H%M%S).log"

# Запускаем с unbuffered режимом и логированием
.venv/bin/python -u scripts/stt/stt.tbank.py "$@" 2>&1 | tee "$LOG_FILE"

echo ""
echo "Лог сохранен: $LOG_FILE"

