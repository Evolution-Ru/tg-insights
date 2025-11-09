#!/usr/bin/env python3
"""
Скрипт запуска экспорта Telegram
"""
import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from sources.telegram.exporter import main

if __name__ == "__main__":
    main(sys.argv[1:])

