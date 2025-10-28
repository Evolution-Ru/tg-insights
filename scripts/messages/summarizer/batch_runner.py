from typing import Any, Dict, List, Optional, Tuple, Callable
import os

from . import logging as slog
from . import batch as sbatch
from . import db as sdb


def run_batch_for_dialogs(
    conn,
    overview: List[Dict[str, Any]],
    *,
    max_dialogs: int,
    max_chunk: int,
    batch_max_requests: int,
    batch_iterations: int,
    log_io: bool,
    prepare_dialog_request: Callable[
        [Any, int, int, str, bool], Optional[Tuple[Dict[str, Any], Dict[str, Any]]]
    ],
    submit_and_collect: Callable[
        [Any, List[Dict[str, Any]], Dict[str, Dict[str, Any]], Any], None
    ],
    args,
) -> None:
    """Run batch iterations across multiple dialogs.
    
    Creates multiple batches if needed to process all max_dialogs.
    Each batch contains up to batch_max_requests.
    """
    model_name = os.getenv("OPENAI_MODEL", "gpt-5")
    
    # Загружаем pending custom_ids один раз
    try:
        pending = sdb.get_blocked_custom_ids(conn)
    except Exception:
        pending = set()
    
    # Собираем ВСЕ запросы для max_dialogs (не ограничиваясь batch_max_requests)
    all_requests: List[Dict[str, Any]] = []
    all_meta_map: Dict[str, Dict[str, Any]] = {}
    used_dialogs: set = set()
    
    for o in overview:
        did = int(o["chat_id"])
        # Если уже набрали нужное число разных диалогов — выходим
        if len(used_dialogs) >= int(max_dialogs):
            break
        try:
            prep = prepare_dialog_request(
                conn, did, int(max_chunk), model_name, bool(log_io)
            )
        except Exception as e:
            slog.log(f"Skip dialog {did} due to error preparing request: {e}")
            continue
        if not prep:
            continue
        req, meta = prep
        cid = req.get("custom_id")
        if cid and cid in pending:
            # Эта порция уже отправлена и ожидает — не считаем диалог использованным
            continue
        all_requests.append(req)
        all_meta_map[cid] = meta  # type: ignore
        used_dialogs.add(did)
    
    if not all_requests:
        slog.log("Нет задач для batch (все пустые, завершены или уже в ожидании)")
        return
    
    # Разбиваем на батчи по batch_max_requests
    total_batches = (len(all_requests) + batch_max_requests - 1) // batch_max_requests
    slog.log(f"Подготовлено {len(all_requests)} запросов для {len(used_dialogs)} диалогов → {total_batches} батч(а/ей)")
    
    for batch_num in range(total_batches):
        start_idx = batch_num * batch_max_requests
        end_idx = min(start_idx + batch_max_requests, len(all_requests))
        batch_requests = all_requests[start_idx:end_idx]
        
        # Извлекаем соответствующие meta
        batch_meta_map = {req["custom_id"]: all_meta_map[req["custom_id"]] for req in batch_requests}
        
        slog.log(f"Отправка батча {batch_num + 1}/{total_batches} ({len(batch_requests)} запросов)")
        submit_and_collect(conn, batch_requests, batch_meta_map, args=args)


def run_batch_for_single_dialog(
    conn,
    chat_id: int,
    *,
    max_chunk: int,
    batch_iterations: int,
    log_io: bool,
    prepare_dialog_request: Callable[
        [Any, int, int, str, bool], Optional[Tuple[Dict[str, Any], Dict[str, Any]]]
    ],
    submit_and_collect: Callable[
        [Any, List[Dict[str, Any]], Dict[str, Dict[str, Any]], Any], None
    ],
    args,
) -> None:
    """Run batch iterations for a single dialog (one chunk per iteration)."""
    model_name = os.getenv("OPENAI_MODEL", "gpt-5")
    iterations = max(1, int(batch_iterations))
    for _ in range(iterations):
        prep = prepare_dialog_request(
            conn, chat_id, int(max_chunk), model_name, bool(log_io)
        )
        if not prep:
            slog.log("Нет задач для batch по этому диалогу (возможно, всё обработано)")
            return
        req, meta = prep
        try:
            pending = sdb.get_blocked_custom_ids(conn)
        except Exception:
            pending = set()
        cid = req.get("custom_id")
        if cid and cid in pending:
            slog.log(
                "Эта порция для диалога уже ожидает в batch — новая отправка пропущена"
            )
            return
        submit_and_collect(conn, [req], {cid: meta}, args=args)
