from datetime import datetime


def log(message: str) -> None:
    """Print a log line with HH:MM:SS.mmm timestamp."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {message}")


def log_dialog_pick(chat_id: int, total_messages: int, last_dt: str | None) -> None:
    tail = last_dt or "—"
    log(
        f"Выбран диалог {chat_id} (всего сообщений: {total_messages}), last_context_date={tail}"
    )


def log_parallel_done(num_dialogs: int, total_msgs: int) -> None:
    log(
        f"Параллельная обработка завершена: диалогов={num_dialogs} сообщений суммарно={total_msgs}"
    )


def log_overview_header(
    total_dialogs: int, total_batches: int, batch_size: int
) -> None:
    log(
        f"Всего диалогов к обработке: {total_dialogs}, ориентировочно партий: {total_batches} (batch={batch_size})"
    )


def log_overview_entry(
    chat_id: int, title: str, total_count: int, unprocessed: int, batches: int
) -> None:
    log(
        f"Диалог {chat_id} / {title}: всего {total_count}, непройдено {unprocessed} (~{batches} партий)"
    )
