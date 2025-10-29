#!/usr/bin/env python3
"""
Обрабатывает один диалог из SQLite БД, формируя новый контекстный блок по правилам:

- Берёт диалог с наименьшим количеством сообщений, в котором ещё остались необработанные сообщения
  (не вошедшие в предыдущие контекстные блоки).
- Обрабатывает максимум первые 30 ранее не обработанных сообщений (по дате, по возрастанию).
- В отправку в OpenAI добавляет прошлый контекст этого диалога (последний блок), чтобы новый блок
  фиксировал только новые факты.
- Сохраняет результат в таблицу dialog_contexts:
    id INTEGER PRIMARY KEY AUTOINCREMENT
    dialog_id TEXT
    message_date TEXT (ISO-8601 дата последнего сообщения в блоке)
    context_text TEXT (очищенный и связный контекст)

Требуемые переменные окружения:
- OPENAI_API_KEY
Опционально .env (telegram-mcp/.env) будет загружен автоматически.

Пример запуска:
  python telegram-mcp/telegram-storage/process_messages.py \
    --db /Users/ychukaev/Desktop/work/salesevolution/messages.sqlite \
    --max-chunk 30
"""

import argparse
import csv
import concurrent.futures
import os
import sqlite3
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from datetime import datetime, timedelta
import math

# Import modularized helpers (script-local package)
from summarizer import db as sdb
from summarizer import participants as spart
from summarizer import logging as slog
from summarizer import plan as splan
from summarizer.prompting import build_block_from_parsed
from summarizer import batch as sbatch
from summarizer import processing as sproc
from summarizer import cli as scli
from summarizer import summarize as ssum
from summarizer import batch_runner as sbrun

# OpenAI SDK v1.x
try:
    # Пробуем современный клиент
    from openai import OpenAI

    _OPENAI_AVAILABLE = True
except Exception:
    OpenAI = None  # type: ignore
    _OPENAI_AVAILABLE = False


def load_env_from_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    except Exception:
        pass


def pick_next_dialog(
    conn: sqlite3.Connection,
    only_dialog: Optional[int] = None,
    exclude_ids: Optional[Set[int]] = None,
) -> Optional[Tuple[int, int, Optional[str]]]:
    return sproc.pick_next_dialog(
        conn, only_dialog=only_dialog, exclude_ids=exclude_ids
    )


def render_messages_for_model(messages: List[Dict[str, Any]]) -> str:
    return sproc.render_messages_for_model(messages)


def openai_summarize(
    previous_context: Optional[str],
    rendered_messages: str,
    participants: List[str],
    *,
    chat_id: int,
    chat_title: Optional[str],
    last_message_date: Optional[str],
    lang: str = "ru",
    log_io: bool = False,
) -> Tuple[str, Optional[str]]:
    return ssum.summarize_block(
        previous_context,
        rendered_messages,
        participants,
        chat_id=chat_id,
        chat_title=chat_title,
        last_message_date=last_message_date,
        lang=lang,
        log_io=log_io,
    )


def process_one_dialog(
    conn: sqlite3.Connection,
    chat_id: int,
    last_context_date: Optional[str],
    max_chunk: int,
    log_io: bool = False,
) -> Optional[Tuple[int, int]]:
    chunk = sdb.fetch_next_chunk(conn, chat_id, last_context_date, max_chunk)
    if not chunk:
        return None

    rendered = render_messages_for_model(chunk)
    if not rendered.strip():
        # Нет содержательных сообщений — сдвинем указатель: ставим блок с пустым контентом
        last_date = chunk[-1]["date"]
        sdb.upsert_context_block(
            conn, chat_id, last_date, "[нет нового содержательного контента]"
        )
        return chat_id, len(chunk)

    participants = spart.build_participants(chunk)
    participants_header = spart.build_participants_header(chunk)
    # Берём только последний контекст для сжатости
    prev_ctx_row = conn.execute(
        """
		SELECT context_text
		FROM dialog_contexts
		WHERE dialog_id = ?
		ORDER BY message_date DESC, id DESC
		LIMIT 1
		""",
        (str(chat_id),),
    ).fetchone()
    prev_context = prev_ctx_row[0] if prev_ctx_row and prev_ctx_row[0] else None

    # Try to fetch chat title/type/username for better metadata and fallback naming
    chat_row = conn.execute(
        "SELECT chat_name, chat_type, username FROM messages WHERE chat_id = ? ORDER BY date DESC LIMIT 1",
        (chat_id,),
    ).fetchone()
    chat_title = chat_row[0] if chat_row and chat_row[0] else None
    chat_type = chat_row[1] if chat_row and len(chat_row) > 1 else None
    chat_username = chat_row[2] if chat_row and len(chat_row) > 2 else None

    # Normalize labels for 1:1 chats
    participants, participants_header = spart.adjust_for_user_chat(
        chunk, chat_title, chat_type, chat_username, participants, participants_header
    )

    last_date = chunk[-1]["date"]
    new_context, context_json = openai_summarize(
        prev_context,
        rendered,
        participants,
        chat_id=chat_id,
        chat_title=chat_title,
        last_message_date=last_date,
        lang="ru",
        log_io=log_io,
    )
    # Автоматически добавляем «Участники: …» сверху, чтобы не тратить токены модели
    if participants_header:
        header_line = "- Участники: " + ", ".join(participants_header)
        final_block = header_line + "\n" + new_context
    else:
        final_block = new_context
    sdb.upsert_context_block(
        conn, chat_id, last_date, final_block, context_json=context_json
    )
    return chat_id, len(chunk)


def process_dialog_until_done(
    db_path: Path,
    chat_id: int,
    max_chunk: int,
    log_io: bool = False,
) -> Tuple[int, int]:
    return sproc.process_dialog_until_done(
        db_path, chat_id, max_chunk, bool(log_io), process_one_dialog
    )


def parse_args() -> argparse.Namespace:
    default_db = str((Path(__file__).resolve().parents[2] / "messages.sqlite"))
    parser = scli.build_parser(default_db)
    return parser.parse_args()


def _prepare_dialog_request(
    conn: sqlite3.Connection,
    chat_id: int,
    max_chunk: int,
    model_name: str,
    log_io: bool,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    req = sproc.prepare_dialog_request(conn, chat_id, max_chunk, model_name, log_io)
    if req and log_io:
        try:
            slog.log(f"Batch request prepared: {req[0]['custom_id']}")
        except Exception:
            pass
    return req


def _apply_result_text_and_upsert(
    conn: sqlite3.Connection, meta: Dict[str, Any], text: str
) -> None:
    parsed: Optional[Dict[str, Any]] = None
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    final_block: Optional[str] = None
    context_json: Optional[str] = None
    if parsed:
        built = build_block_from_parsed(parsed)
        if built:
            final_block, context_json = built

    if not final_block:
        # treat whole text as final block
        final_block = text.strip()
        context_json = None

    participants_header = meta.get("participants_header") or []
    if participants_header:
        header_line = "- Участники: " + ", ".join(participants_header)
        final_block = header_line + "\n" + final_block

    chat_id = int(meta["chat_id"])  # type: ignore
    last_date = str(meta["last_date"])  # type: ignore
    sdb.upsert_context_block(
        conn, chat_id, last_date, final_block, context_json=context_json
    )


def _run_batch_submit_and_collect(
    conn: sqlite3.Connection,
    requests: List[Dict[str, Any]],
    meta_map: Dict[str, Dict[str, Any]],
    *,
    args: argparse.Namespace,
) -> None:
    # Use shared batch submitter; wrap upsert in callable per item
    def _mk_applier(custom_id: str):
        def _apply(text: str) -> None:
            _apply_result_text_and_upsert(conn, meta_map[custom_id], text)

        return _apply

    meta_with_apply: Dict[str, Dict[str, Any]] = {}
    for cid, meta in meta_map.items():
        meta_with_apply[cid] = {**meta, "_apply": _mk_applier(cid)}
    # Filter out requests whose custom_id is blocked (pending or completed-not-applied)
    try:
        pending = sdb.get_blocked_custom_ids(conn)
    except Exception:
        pending = set()
    filtered_requests: List[Dict[str, Any]] = []
    filtered_meta: Dict[str, Dict[str, Any]] = {}
    for r in requests:
        cid = r.get("custom_id")
        if cid and cid in pending:
            continue
        filtered_requests.append(r)
        if cid:
            filtered_meta[cid] = meta_with_apply[cid]
    if not filtered_requests:
        slog.log(
            "Все подготовленные задачи уже ожидают в других батчах — отправлять нечего."
        )
        return
    # Always async: submit without waiting; collection handled separately this run
    sbatch.submit_only(conn, filtered_requests, filtered_meta, args=args)
    # Mark requested in DB
    try:
        sdb.mark_batch_requested(
            conn, [r.get("custom_id") for r in filtered_requests if r.get("custom_id")]
        )
    except Exception:
        pass


def _collect_and_apply_all_ready(
    conn: sqlite3.Connection, args: argparse.Namespace
) -> None:
    """Collect all ready batch outputs and apply them into DB."""
    downloaded = sbatch.collect_ready(args=args)
    if downloaded == 0:
        slog.log("Готовых батчей не найдено (или уже скачаны).")
    else:
        slog.log(f"Скачано готовых результатов: {downloaded}")
    # Apply results for all output-*.jsonl files
    batch_dir = sbatch.ensure_batch_dir(getattr(args, "batch_dir", None))
    applied = 0
    for out_path in sorted(batch_dir.glob("output-*.jsonl")):
        try:
            uid = out_path.stem.split("-", 1)[1]
            map_path = batch_dir / f"mapping-{uid}.json"
            if not map_path.exists():
                continue
            meta_map: Dict[str, Dict[str, Any]] = json.loads(
                map_path.read_text(encoding="utf-8")
            )
            ok_cnt = 0
            err_cnt = 0
            for line in out_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    err_cnt += 1
                    continue
                custom_id = obj.get("custom_id")
                if not custom_id or custom_id not in meta_map:
                    err_cnt += 1
                    continue
                if obj.get("error"):
                    err_cnt += 1
                    continue
                response_container = obj.get("response") or {}
                response_body = (
                    response_container.get("body")
                    if isinstance(response_container, dict)
                    else {}
                ) or {}
                text = sbatch.extract_text_from_responses_output(response_body)
                if not text:
                    err_cnt += 1
                    continue
                try:
                    # Idempotent upsert by (dialog_id, message_date); also mark applied in DB
                    _apply_result_text_and_upsert(conn, meta_map[custom_id], text)
                    sdb.mark_batch_applied(conn, custom_id)
                    ok_cnt += 1
                except Exception:
                    err_cnt += 1
            slog.log(
                f"Применены результаты из {out_path.name}: ok={ok_cnt}, errors={err_cnt}"
            )
            applied += ok_cnt
            # Mark descriptor as applied for this uid
            try:
                desc_path = batch_dir / f"batch-{uid}.json"
                if desc_path.exists():
                    import time as _time

                    desc = json.loads(desc_path.read_text(encoding="utf-8"))
                    desc["applied_ts"] = int(_time.time())
                    desc["ok_count"] = ok_cnt
                    desc["error_count"] = err_cnt
                    desc_path.write_text(
                        json.dumps(desc, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                
                # Cleanup strategy based on results
                req_path = batch_dir / f"requests-{uid}.jsonl"
                
                if ok_cnt > 0 and err_cnt == 0:
                    # ✅ All success - delete everything
                    try:
                        map_path.unlink(missing_ok=True)  # type: ignore
                        req_path.unlink(missing_ok=True)  # type: ignore
                        out_path.unlink(missing_ok=True)  # type: ignore
                        desc_path.unlink(missing_ok=True)  # type: ignore
                    except Exception:
                        pass
                elif ok_cnt > 0 and err_cnt > 0:
                    # ⚠️ Partial success - rename for debugging
                    try:
                        partial_out = batch_dir / f"output-{uid}.partial.jsonl"
                        out_path.rename(partial_out)
                        slog.log(f"Частично обработано → сохранено в {partial_out.name}")
                    except Exception:
                        pass
                elif ok_cnt == 0 and err_cnt > 0:
                    # ❌ Complete failure - rename for debugging
                    try:
                        error_out = batch_dir / f"output-{uid}.error.jsonl"
                        out_path.rename(error_out)
                        slog.log(f"Ошибка обработки → сохранено в {error_out.name}")
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception as e:
            slog.log(f"Не удалось применить {out_path.name}: {e}")
            continue
    if applied > 0:
        slog.log(f"Всего применено результатов: {applied}")


def _run_batch_mode_multi_dialogs(
    conn: sqlite3.Connection,
    db_path: Path,
    overview: List[Dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    sbrun.run_batch_for_dialogs(
        conn,
        overview,
        max_dialogs=int(args.max_dialogs),
        max_chunk=int(args.max_chunk),
        batch_max_requests=int(args.batch_max_requests),
        batch_iterations=int(args.batch_iterations),
        log_io=bool(args.log_prompt),
        prepare_dialog_request=_prepare_dialog_request,
        submit_and_collect=_run_batch_submit_and_collect,
        args=args,
    )


def _run_batch_mode_single_dialog(
    conn: sqlite3.Connection, db_path: Path, chat_id: int, args: argparse.Namespace
) -> None:
    sbrun.run_batch_for_single_dialog(
        conn,
        chat_id,
        max_chunk=int(args.max_chunk),
        batch_iterations=int(args.batch_iterations),
        log_io=bool(args.log_prompt),
        prepare_dialog_request=_prepare_dialog_request,
        submit_and_collect=_run_batch_submit_and_collect,
        args=args,
    )


def main() -> None:
    # Загрузка .env из корня priv-tg-workers/.env (если есть)
    repo_root = Path(__file__).resolve().parents[1]
    load_env_from_file(repo_root / ".env")
    # Загрузка .env рядом со скриптом messages-tools/.env (если есть)
    load_env_from_file(Path(__file__).resolve().parent / ".env")
    
    args = parse_args()
    
    # Определяем путь к БД: либо из --account, либо из --db
    if args.account:
        # Режим --account: формируем путь автоматически
        current_dir = Path(__file__).resolve().parent  # scripts/messages/
        account_dir = current_dir.parent.parent / "data/accounts" / args.account  # ../../data/accounts/{account}/
        db_path = account_dir / "messages.sqlite"
        
        # Устанавливаем batch_dir для аккаунта (если не указан явно)
        if not args.batch_dir:
            args.batch_dir = str(account_dir / ".batches")
        
        # Загружаем .env из аккаунта
        env_path = account_dir / ".env"
        if env_path.exists():
            load_env_from_file(env_path)
        else:
            print(f"Warning: {env_path} not found")
        
        if not db_path.exists():
            raise SystemExit(f"Database not found: {db_path}")
    else:
        # Режим --db: используем указанный путь
        db_path = Path(args.db).expanduser().resolve()
        
        # Пробуем загрузить .env из той же папки что и БД
        if "data/accounts" in db_path.parts:
            account_dir = db_path.parent
            env_in_account = account_dir / ".env"
            if env_in_account.exists():
                load_env_from_file(env_in_account)
            
            # Устанавливаем batch_dir для аккаунта (если не указан явно)
            if not args.batch_dir:
                args.batch_dir = str(account_dir / ".batches")

    conn = sqlite3.connect(str(db_path))
    try:
        sdb.ensure_schema(conn)

        # Одноразовая пометка об отказе, если задана
        if args.deny is not None:
            sdb.mark_denied(conn, int(args.deny), args.deny_reason)
            slog.log(
                f"Диалог {args.deny} помечен как отказанный (reason={args.deny_reason})."
            )
            return

        denied_ids = sdb.load_denied_ids(conn)

        # Генерация плана (TSV) для предварительной массовой разметки approve/deny
        if args.make_plan:
            plan_path = Path(args.make_plan)
            splan.make_plan(
                conn,
                plan_path,
                exclude_ids=denied_ids,
                preview_limit=int(args.plan_chunk_preview),
            )
            return

        # Применение плана: помечаем deny в dialog_denied
        if args.apply_plan:
            plan_path = Path(args.apply_plan)
            splan.apply_plan(conn, plan_path, default_reason=args.deny_reason)
            return

        # Если указан конкретный диалог — обрабатываем только его (как раньше)
        if args.dialog is not None:
            if int(args.dialog) in denied_ids:
                slog.log(f"Диалог {args.dialog} ранее отклонён — пропуск.")
                return
            cand = pick_next_dialog(
                conn, only_dialog=args.dialog, exclude_ids=denied_ids
            )
            if not cand:
                slog.log(
                    "Нет диалогов с необработанными сообщениями (или не найден указанный dialog_id)."
                )
                return
            chat_id, total_cnt, last_dt = cand
            slog.log(
                f"Выбран диалог {chat_id} (всего сообщений: {total_cnt}), last_context_date={last_dt or '—'}"
            )
            if args.use_batch:
                _run_batch_mode_single_dialog(conn, Path(args.db), chat_id, args)
                return
            # Подтверждение
            if args.confirm:
                # Подтянем имя чата и непройденные сообщения
                row = conn.execute(
                    "SELECT chat_name FROM messages WHERE chat_id = ? ORDER BY date DESC LIMIT 1",
                    (chat_id,),
                ).fetchone()
                chat_title = row[0] if row and row[0] else str(chat_id)
                unprocessed = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND date > COALESCE(?, '0000-01-01T00:00:00')",
                    (chat_id, last_dt),
                ).fetchone()[0]
                ph = spart.preview_participants_for_dialog(
                    conn, chat_id, last_dt, limit=max(10, min(30, args.max_chunk))
                )
                if ph:
                    slog.log("Участники: " + ", ".join(ph))
                slog.log(
                    f"Обработать диалог {chat_id} / {chat_title}? Непройденных сообщений: {unprocessed}. [y/N]"
                )
                ans = input("").strip().lower()
                if not ans or ans[0] != "y":
                    sdb.mark_denied(conn, chat_id, "user_denied_interactive")
                    slog.log(
                        f"Диалог {chat_id} отклонён пользователем — помечен в dialog_denied."
                    )
                    return
            # Обрабатываем все порции для выбранного диалога до конца
            total_processed_for_dialog = 0
            while True:
                cur_last_dt = sdb.get_last_context_date(conn, chat_id)
                res = process_one_dialog(
                    conn, chat_id, cur_last_dt, args.max_chunk, log_io=args.log_prompt
                )
                if not res:
                    break
                processed_chat, processed_cnt = res
                total_processed_for_dialog += processed_cnt
                slog.log(
                    f"Готово: dialog_id={processed_chat}, обработано сообщений в партии={processed_cnt} (сумма={total_processed_for_dialog})"
                )
            slog.log(f"Диалог {chat_id} полностью обработан.")
            return

        # Иначе — обрабатываем до N разных диалогов
        overview = sdb.get_unprocessed_overview(conn, exclude_ids=denied_ids)
        if len(overview) == 0:
            slog.log("Нет диалогов с необработанными сообщениями.")
            return

        # Печать сводки
        sproc.print_overview(conn, overview, int(args.max_chunk), int(args.max_dialogs))

        # Параллельная обработка (только без интерактива)
        if int(args.concurrency) > 1 and not args.confirm:
            if args.use_batch:
                _run_batch_mode_multi_dialogs(conn, Path(args.db), overview, args)
                # Сбор и применение — только в конце, после отправки
                _collect_and_apply_all_ready(conn, args)
                return
            sproc.process_overview_parallel(
                db_path,
                overview,
                max_dialogs=int(args.max_dialogs),
                concurrency=int(args.concurrency),
                max_chunk=int(args.max_chunk),
                log_io=bool(args.log_prompt),
                process_dialog_until_done_func=process_dialog_until_done,
            )
            # Не batch режим — всё синхронно
            return

        # Последовательная обработка (как было)
        if args.use_batch:
            # Передаём полный overview — внутри будет лимит по max_dialogs и фильтрация pending
            _run_batch_mode_multi_dialogs(conn, Path(args.db), overview, args)
            # Сбор и применение — только в конце, после отправки
            _collect_and_apply_all_ready(conn, args)
            return

        sproc.process_overview_sequential(
            conn,
            max_dialogs=int(args.max_dialogs),
            max_chunk=int(args.max_chunk),
            log_io=bool(args.log_prompt),
            exclude_ids=denied_ids,
            confirm=bool(args.confirm),
            preview_participants=spart.preview_participants_for_dialog,
            on_denied=sdb.mark_denied,
            process_one_dialog_func=process_one_dialog,
        )
        return
    finally:
        conn.close()


if __name__ == "__main__":
    main()
