from __future__ import annotations
import time
import uuid
import json
from openai import OpenAI
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import logging as slog
from . import config


def ensure_batch_dir(arg_dir: Optional[str]) -> Path:
    base = (
        Path(arg_dir).expanduser().resolve()
        if arg_dir
        else Path(__file__).resolve().parents[1] / ".batches"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def write_jsonl(path: Path, lines: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def extract_text_from_responses_output(resp_obj: Dict[str, Any]) -> str:
    output = resp_obj.get("output") or []
    chunks: List[str] = []
    for item in output:
        content = item.get("content") or []
        for c in content:
            text = c.get("text")
            if text:
                chunks.append(str(text))
    return "\n".join(chunks).strip()


def submit_and_collect(
    conn,
    requests: List[Dict[str, Any]],
    meta_map: Dict[str, Dict[str, Any]],
    *,
    args,
) -> None:
    client = OpenAI(api_key=config.openai_api_key())

    batch_dir = ensure_batch_dir(getattr(args, "batch_dir", None))
    uid = time.strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:8]}"
    req_path = batch_dir / f"requests-{uid}.jsonl"
    map_path = batch_dir / f"mapping-{uid}.json"
    write_jsonl(req_path, requests)
    # meta_map может содержать несериализуемые объекты (например, функции _apply).
    # Сохраняем в файл только сериализуемую часть для отладки/traceability.
    try:
        serializable_map: Dict[str, Dict[str, Any]] = {}
        for key, meta in meta_map.items():
            cleaned: Dict[str, Any] = {}
            for mk, mv in meta.items():
                if callable(mv):
                    continue
                cleaned[mk] = mv
            serializable_map[key] = cleaned
        map_path.write_text(
            json.dumps(serializable_map, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        # В крайнем случае пишем только ключи custom_id, если фильтрация неожиданно упала
        try:
            fallback_map = {k: {"_note": "meta omitted"} for k in meta_map.keys()}
            map_path.write_text(
                json.dumps(fallback_map, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            # Игнорируем запись маппинга, если вообще ничего не получилось
            pass

    with req_path.open("rb") as rf:
        up = client.files.create(file=rf, purpose="batch")
    bt = client.batches.create(
        input_file_id=up.id,
        endpoint="/v1/responses",
        completion_window=str(
            getattr(
                args,
                "batch_completion_window",
                config.batch_completion_window_default(),
            )
        ),
    )
    slog.log(f"Batch submitted: {bt.id}, requests={len(requests)}")
    # Persist batch descriptor for later collection
    batch_desc = {
        "uid": uid,
        "batch_id": getattr(bt, "id", None),
        "status": getattr(bt, "status", None),
        "requests_file": str(req_path),
        "mapping_file": str(map_path),
        "output_file": str((batch_dir / f"output-{uid}.jsonl").resolve()),
        "completion_window": str(
            getattr(
                args,
                "batch_completion_window",
                config.batch_completion_window_default(),
            )
        ),
        "created_ts": int(time.time()),
    }
    (batch_dir / f"batch-{uid}.json").write_text(
        json.dumps(batch_desc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Poll
    wait_seconds = max(
        1, int(getattr(args, "batch_wait_seconds", config.batch_wait_seconds_default()))
    )
    while True:
        cur = client.batches.retrieve(bt.id)
        status = getattr(cur, "status", None)
        if status in {"completed", "failed", "expired", "cancelling", "cancelled"}:
            break
        time.sleep(wait_seconds)

    cur = client.batches.retrieve(bt.id)
    status = getattr(cur, "status", None)
    if status != "completed":
        slog.log(f"Batch finished with status={status}")
    output_id = getattr(cur, "output_file_id", None)
    if not output_id:
        slog.log("No output_file_id present in batch result")
        return
    resp = client.files.content(output_id)
    out_text = (
        resp.text
        if hasattr(resp, "text")
        else (resp.get("text") if isinstance(resp, dict) else None)
    )
    if not out_text:
        try:
            out_text = resp.read().decode("utf-8")  # type: ignore
        except Exception:
            out_text = None
    if not out_text:
        slog.log("Empty batch output content")
        return
    out_path = batch_dir / f"output-{uid}.jsonl"
    out_path.write_text(out_text, encoding="utf-8")

    ok_cnt = 0
    err_cnt = 0
    for line in out_text.splitlines():
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
        text = extract_text_from_responses_output(response_body)
        if not text:
            err_cnt += 1
            continue
        try:
            # Defer upsert to caller-provided function via meta_map
            applier = meta_map[custom_id].get("_apply")
            if callable(applier):
                applier(text)
                ok_cnt += 1
            else:
                err_cnt += 1
        except Exception as e:
            err_cnt += 1
            slog.log(f"Failed to apply result for {custom_id}: {e}")

    slog.log(f"Batch applied: ok={ok_cnt}, errors={err_cnt}")


def list_pending_custom_ids(*, args) -> set:
    """Return set of custom_id that are pending (submitted but output not yet downloaded)."""
    batch_dir = ensure_batch_dir(getattr(args, "batch_dir", None))
    pending: set = set()
    for desc_path in sorted(batch_dir.glob("batch-*.json")):
        try:
            desc = json.loads(desc_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        uid = desc.get("uid")
        mapping_file = desc.get("mapping_file")
        if not uid or not mapping_file:
            continue
        out_path = batch_dir / f"output-{uid}.jsonl"
        if out_path.exists() and out_path.stat().st_size > 0:
            # Completed (downloaded) — not pending
            continue
        try:
            mapping = json.loads(Path(mapping_file).read_text(encoding="utf-8"))
            for cid in mapping.keys():
                pending.add(cid)
        except Exception:
            continue
    return pending


def is_custom_id_pending(custom_id: str, *, args) -> bool:
    return custom_id in list_pending_custom_ids(args=args)


def list_blocked_custom_ids(*, args) -> set:
    """Return custom_ids that must not be re-submitted now:
    - pending in an active batch
    - completed batch has output file downloaded, but results not yet applied
    """
    batch_dir = ensure_batch_dir(getattr(args, "batch_dir", None))
    blocked = set(list_pending_custom_ids(args=args))
    for desc_path in sorted(batch_dir.glob("batch-*.json")):
        try:
            desc = json.loads(desc_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        uid = desc.get("uid")
        mapping_file = desc.get("mapping_file")
        if not uid or not mapping_file:
            continue
        out_path = batch_dir / f"output-{uid}.jsonl"
        if out_path.exists() and out_path.stat().st_size > 0:
            # Load mapping
            try:
                mapping = json.loads(Path(mapping_file).read_text(encoding="utf-8"))
            except Exception:
                continue
            # Determine which ids were already applied successfully
            applied_path = batch_dir / f"applied-{uid}.json"
            applied_ids: set = set()
            try:
                if applied_path.exists():
                    applied_ids = set(
                        json.loads(applied_path.read_text(encoding="utf-8"))
                    )
            except Exception:
                applied_ids = set()
            for cid in mapping.keys():
                if cid not in applied_ids:
                    blocked.add(cid)
    return blocked


def submit_only(
    conn,
    requests: List[Dict[str, Any]],
    meta_map: Dict[str, Dict[str, Any]],
    *,
    args,
) -> None:
    """Submit a batch and return immediately without polling or applying results."""
    client = OpenAI(api_key=config.openai_api_key())
    batch_dir = ensure_batch_dir(getattr(args, "batch_dir", None))
    uid = time.strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:8]}"
    req_path = batch_dir / f"requests-{uid}.jsonl"
    map_path = batch_dir / f"mapping-{uid}.json"
    write_jsonl(req_path, requests)
    # Store serializable meta
    try:
        serializable_map: Dict[str, Dict[str, Any]] = {}
        for key, meta in meta_map.items():
            cleaned: Dict[str, Any] = {}
            for mk, mv in meta.items():
                if callable(mv):
                    continue
                cleaned[mk] = mv
            serializable_map[key] = cleaned
        map_path.write_text(
            json.dumps(serializable_map, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        try:
            fallback_map = {k: {"_note": "meta omitted"} for k in meta_map.keys()}
            map_path.write_text(
                json.dumps(fallback_map, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    with req_path.open("rb") as rf:
        up = client.files.create(file=rf, purpose="batch")
    bt = client.batches.create(
        input_file_id=up.id,
        endpoint="/v1/responses",
        completion_window=str(
            getattr(
                args,
                "batch_completion_window",
                config.batch_completion_window_default(),
            )
        ),
    )
    slog.log(f"Batch submitted (submit-only): {bt.id}, requests={len(requests)}")
    batch_desc = {
        "uid": uid,
        "batch_id": getattr(bt, "id", None),
        "status": getattr(bt, "status", None),
        "requests_file": str(req_path),
        "mapping_file": str(map_path),
        "output_file": str((batch_dir / f"output-{uid}.jsonl").resolve()),
        "completion_window": str(
            getattr(
                args,
                "batch_completion_window",
                config.batch_completion_window_default(),
            )
        ),
        "created_ts": int(time.time()),
    }
    (batch_dir / f"batch-{uid}.json").write_text(
        json.dumps(batch_desc, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def collect_ready(*, args) -> int:
    """Download outputs for all completed batches in batch dir. Returns count."""
    client = OpenAI(api_key=config.openai_api_key())
    batch_dir = ensure_batch_dir(getattr(args, "batch_dir", None))
    downloaded = 0
    for desc_path in sorted(batch_dir.glob("batch-*.json")):
        try:
            desc = json.loads(desc_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        uid = desc.get("uid")
        batch_id = desc.get("batch_id")
        if not uid or not batch_id:
            continue
        out_path = batch_dir / f"output-{uid}.jsonl"
        if out_path.exists() and out_path.stat().st_size > 0:
            continue
        try:
            cur = client.batches.retrieve(batch_id)
        except Exception as e:
            slog.log(f"Failed to retrieve batch {batch_id}: {e}")
            continue
        status = getattr(cur, "status", None)
        if status != "completed":
            continue
        output_id = getattr(cur, "output_file_id", None)
        if not output_id:
            slog.log(f"Batch {batch_id} completed without output_file_id")
            try:
                out_path.touch(exist_ok=True)
            except Exception:
                pass
            continue
        try:
            resp = client.files.content(output_id)
            out_text = (
                resp.text
                if hasattr(resp, "text")
                else (resp.get("text") if isinstance(resp, dict) else None)
            )
            if not out_text:
                try:
                    out_text = resp.read().decode("utf-8")  # type: ignore
                except Exception:
                    out_text = None
            if out_text:
                out_path.write_text(out_text, encoding="utf-8")
                downloaded += 1
                try:
                    desc["status"] = status
                    desc["output_file_id"] = output_id
                    desc_path.write_text(
                        json.dumps(desc, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
        except Exception as e:
            slog.log(f"Failed to download output for batch {batch_id}: {e}")
            continue
    return downloaded
