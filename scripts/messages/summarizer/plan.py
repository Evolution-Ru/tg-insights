from typing import Any, Dict, List, Optional, Tuple, Set
from pathlib import Path
import csv

from . import db as sdb
from . import participants as spart
from . import logging as slog


def make_plan(
    conn,
    plan_path: Path,
    *,
    exclude_ids: Optional[Set[int]] = None,
    preview_limit: int = 30,
) -> int:
    overview = sdb.get_unprocessed_overview(conn, exclude_ids=exclude_ids or set())
    if not overview:
        slog.log("Нет диалогов с необработанными сообщениями — план не создан.")
        return 0
    plan_path = plan_path.expanduser().resolve()
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    with plan_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(
            [
                "chat_id",
                "chat_name",
                "total_count",
                "unprocessed_count",
                "last_processed_date",
                "latest_message_date",
                "participants_preview",
                "decision",
                "reason",
            ]
        )
        for o in overview:
            ph = spart.preview_participants_for_dialog(
                conn,
                int(o["chat_id"]),
                o.get("last_processed_date"),
                limit=max(10, min(100, int(preview_limit))),
            )
            writer.writerow(
                [
                    o["chat_id"],
                    (o.get("chat_name") or "").replace("\n", " ").strip(),
                    o.get("total_count"),
                    o.get("unprocessed_count"),
                    o.get("last_processed_date") or "",
                    o.get("latest_message_date") or "",
                    ", ".join(ph),
                    "",  # decision: пусто/deny/approve
                    "",  # reason: опционально
                ]
            )
    slog.log(
        f"План сохранён в {plan_path}. Отредактируйте колонку 'decision' (deny/approve) и, при необходимости, 'reason'."
    )
    slog.log("Затем примените его с флагом --apply-plan <path>.")
    return len(overview)


def apply_plan(conn, plan_path: Path, *, default_reason: str = "user_denied") -> int:
    plan_path = plan_path.expanduser().resolve()
    if not plan_path.exists():
        raise FileNotFoundError(f"План не найден: {plan_path}")
    applied_cnt = 0
    with plan_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            try:
                chat_id_str = (row.get("chat_id") or "").strip()
                if not chat_id_str:
                    continue
                chat_id_val = int(chat_id_str)
            except Exception:
                continue
            decision = (row.get("decision") or "").strip().lower()
            if decision in {"deny", "skip", "no"}:
                reason = (row.get("reason") or default_reason or "user_denied").strip()
                sdb.mark_denied(conn, chat_id_val, reason)
                applied_cnt += 1
    slog.log(f"Применено deny для {applied_cnt} диалогов из плана {plan_path}.")
    return applied_cnt
