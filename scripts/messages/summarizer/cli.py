import argparse
from pathlib import Path


def build_parser(default_db: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Сформировать новый контекстный блок для одного диалога"
    )
    parser.add_argument(
        "--account",
        type=str,
        default=None,
        help="Имя аккаунта (загружает ../accounts/{account}/messages.sqlite и .env)",
    )
    parser.add_argument(
        "--db",
        default=default_db,
        help="Путь к SQLite базе (messages.sqlite). Используется если --account не указан.",
    )
    parser.add_argument(
        "--dialog",
        type=int,
        default=None,
        help=(
            "Обработать конкретный dialog_id (chat_id). По умолчанию выбирается диалог с"
            " наименьшим количеством сообщений."
        ),
    )
    parser.add_argument(
        "--max-chunk",
        type=int,
        default=30,
        help="Максимум сообщений в одном блоке обработки (по возрастанию даты).",
    )
    parser.add_argument(
        "--max-dialogs",
        type=int,
        default=1,
        help="Максимум диалогов, которые обработать за один запуск (по умолчанию 1).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Сколько диалогов обрабатывать параллельно (по умолчанию 1 — без параллелизма).",
    )
    parser.add_argument(
        "--log-prompt",
        action="store_true",
        help="Логировать в консоль, что отправляется в ИИ и что возвращается (system/user/raw).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Перед обработкой каждого диалога запрашивать подтверждение (y/N).",
    )
    parser.add_argument(
        "--deny",
        type=int,
        default=None,
        help="Пометить указанный dialog_id как отказанный в обработке и завершить.",
    )
    parser.add_argument(
        "--deny-reason",
        type=str,
        default="user_denied",
        help="Причина отказа (для --deny).",
    )
    parser.add_argument(
        "--make-plan",
        type=str,
        default=None,
        help=(
            "Сохранить план по всем диалогам с непройденными сообщениями в TSV-файл"
            " (для ручной разметки approve/deny)."
        ),
    )
    parser.add_argument(
        "--apply-plan",
        type=str,
        default=None,
        help="Применить TSV-план: пометить диалоги с решением deny в dialog_denied.",
    )
    parser.add_argument(
        "--plan-chunk-preview",
        type=int,
        default=30,
        help=(
            "Сколько первых непройденных сообщений учитывать при превью участников в плане"
            " (по умолчанию 30)."
        ),
    )
    # Batch API options
    parser.add_argument(
        "--use-batch",
        action="store_true",
        help=(
            "Использовать OpenAI Batch API (одна партия задач на submit + ожидание завершения)"
        ),
    )
    # Режимы batch теперь всегда асинхронные: отдельные флаги submit/collect не нужны
    parser.add_argument(
        "--batch-max-requests",
        type=int,
        default=100,
        help=(
            "Максимум задач (диалоговых порций) в одной batch-отправке (по умолчанию 100)."
        ),
    )
    parser.add_argument(
        "--batch-iterations",
        type=int,
        default=1,
        help="Сколько итераций batch-отправок выполнить (1 итерация = по 1 порции на диалог).",
    )
    parser.add_argument(
        "--batch-wait-seconds",
        type=int,
        default=10,
        help="Интервал ожидания при опросе статуса batch (секунды).",
    )
    parser.add_argument(
        "--batch-dir",
        type=str,
        default=None,
        help="Каталог для артефактов batch (JSONL и mapping). По умолчанию telegram-mcp/.batches",
    )
    parser.add_argument(
        "--batch-completion-window",
        type=str,
        default="24h",
        help="Окно завершения batch (обычно 24h).",
    )
    return parser
