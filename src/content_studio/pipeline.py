from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import shutil
import subprocess
import sys
from typing import Any, Callable, Sequence

from .baseline import douyin_baseline
from .deps import subprocess_env
from .judge import JudgeFn, cli_judge
from .structure import build_report, load_glossary, render_markdown

DEFAULT_GLOSSARY_PATH = Path(__file__).resolve().parents[2] / "config" / "glossary.json"


def drop_partial(downloads_dir: Path, content_id: str | None) -> int:
    """Throw away a half-finished download so the next attempt starts clean.

    A failed download can leave a content dir with metadata but no video (one such partial was
    499 MB). Worse, `_find_content_dir` then finds that dir, skips the download, and extraction
    fails with "No video file" — the job can never succeed again. Only dirs without a
    transcript are removed; anything already transcribed is finished work.
    """
    if not content_id:
        return 0
    # _find_content_dir looks for content_item.json, but a download can die before writing it
    # and leave a folder holding nothing but media/ (one such orphan was 499 MB). Fall back to
    # the folder the downloader names after the video id.
    candidates = [d for d in [_find_content_dir(downloads_dir, content_id)] if d is not None]
    candidates += [d for d in downloads_dir.rglob(content_id) if d.is_dir() and d not in candidates]
    freed = 0
    for content_dir in candidates:
        if (content_dir / "transcript.json").is_file():
            continue
        freed += sum(f.stat().st_size for f in content_dir.rglob("*") if f.is_file())
        shutil.rmtree(content_dir, ignore_errors=True)
    return freed


def prune_media(content_dir: Path) -> int:
    """Drop the downloaded video/audio once the transcript exists.

    One item is ~70 MB, of which media/ is ~69.5 MB; transcript.json, metadata.json and
    structured_text.md — everything a re-analysis needs — are the remaining 350 KB. 作者's
    boot disk has single-digit GB free, so keeping the raw video of an already torn-down
    video costs real space and buys nothing.
    """
    media = content_dir / "media"
    if not media.is_dir():
        return 0
    freed = sum(f.stat().st_size for f in media.rglob("*") if f.is_file())
    shutil.rmtree(media, ignore_errors=True)
    return freed


class PipelineError(RuntimeError):
    """A pipeline stage could not produce a verifiable result."""


def _secure_dir(path: Path) -> Path:
    path = path.expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"JSON artifact must be an object: {path}")
    return value


def _find_content_dir(downloads_dir: Path, content_id: str | None) -> Path | None:
    if not content_id:
        return None
    for path in downloads_dir.rglob("content_item.json"):
        try:
            item = _read_json(path)
        except PipelineError:
            continue
        if content_id is None or str(item.get("content_id")) == content_id:
            return path.parent
    return None


def _content_id_from_url(url: str) -> str | None:
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else None


def _download_one(url: str, cookies: Path, output_dir: Path) -> Path:
    from .creator_metrics import load_cookie_file

    cookies = cookies.expanduser().resolve()
    repo_root = Path.cwd().resolve()
    try:
        cookies.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise PipelineError("cookies must be stored outside the content-studio repository")
    load_cookie_file(cookies)
    output_dir = _secure_dir(output_dir)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "content_downloader",
            "download",
            url,
            "--cookies",
            str(cookies),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=subprocess_env(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        hint = detail[-1][:200] if detail else ""
        raise PipelineError(f"下载失败（退出码 {completed.returncode}）{('：' + hint) if hint else ''}")
    content_id = _content_id_from_url(url)
    if content_id is None:
        match = re.search(
            r"(?:Downloaded|Skipped \(already downloaded\)):\s*([A-Za-z0-9_-]+)",
            completed.stdout,
        )
        content_id = match.group(1) if match else None
    content_dir = _find_content_dir(output_dir, content_id)
    if content_dir is None:
        raise PipelineError("download reported success but no content_item.json was found")
    return content_dir


def _extract_one(content_dir: Path, whisper_model: str) -> Path:
    try:
        from content_extractor.config import ExtractorConfig
        from content_extractor.extract import extract_content
    except ImportError as exc:
        raise PipelineError("content-extractor is not installed") from exc
    extract_content(
        content_dir,
        ExtractorConfig(whisper_model=whisper_model, force_reprocess=False),
    )
    if not (content_dir / "transcript.json").is_file():
        raise PipelineError("transcription stage returned without transcript.json")
    return content_dir


def _creator_metrics(db_path: Path | None, content_id: str) -> dict[str, Any] | None:
    """Creator-backend metrics for one of 作者's own videos, if synced."""
    if db_path is None:
        return None
    db_path = db_path.expanduser()
    if not db_path.is_file():
        return None
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM creator_video_metrics WHERE video_id = ?", (content_id,)
        ).fetchone()
    if row is None:
        return None
    return {key: row[key] for key in row.keys() if key != "raw_json"}


def _default_baseline(content_dir: Path, cookie_path: Path, cache_dir: Path) -> dict[str, Any] | None:
    from .creator_metrics import load_cookie_file

    metadata_path = content_dir / "metadata.json"
    if not metadata_path.is_file():
        return None
    author = (_read_json(metadata_path).get("author") or {})
    sec_uid = str(author.get("sec_uid") or "").strip()
    if not sec_uid:
        return None
    return douyin_baseline(sec_uid, cookies=load_cookie_file(cookie_path), cache_dir=cache_dir)


def _write_report(report: dict, data_dir: Path) -> dict[str, str]:
    report_dir = _secure_dir(data_dir / "reports" / str(report["content_id"]))
    json_path = report_dir / "report.json"
    markdown_path = report_dir / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.chmod(0o600)
    markdown_path.chmod(0o600)
    return {"report_json": str(json_path), "report_markdown": str(markdown_path)}


StageFn = Callable[[str], None]


def process_url(
    url: str,
    *,
    cookie_path: Path,
    data_dir: Path,
    downloads_dir: Path,
    download_fn: Callable[[str, Path, Path], Path] = _download_one,
    extract_fn: Callable[[Path, str], Path] = _extract_one,
    whisper_model: str = "turbo",
    generated_at: str | None = None,
    judge_fn: JudgeFn = cli_judge,
    baseline_fn: Callable[[Path, Path, Path], dict[str, Any] | None] = _default_baseline,
    creator_db: Path | None = None,
    glossary: dict[str, str] | None = None,
    on_stage: StageFn = lambda _stage: None,
) -> dict[str, Any]:
    """Download → transcribe → analyse one link, reporting each stage as it starts."""
    on_stage("downloading")
    content_dir = _find_content_dir(downloads_dir, _content_id_from_url(url))
    if content_dir is None:
        try:
            content_dir = download_fn(url, cookie_path, downloads_dir)
        except PipelineError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(f"下载失败：{exc}") from exc
    item = _read_json(content_dir / "content_item.json")
    if not (content_dir / "transcript.json").is_file():
        on_stage("transcribing")
        try:
            content_dir = extract_fn(content_dir, whisper_model)
        except PipelineError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(f"转写失败：{exc}") from exc
    transcript = _read_json(content_dir / "transcript.json")
    on_stage("analyzing")
    content_id = str(item.get("content_id") or "")
    try:
        baseline = baseline_fn(content_dir, cookie_path, data_dir / "baselines")
    except Exception:  # noqa: BLE001 - a missing baseline only removes the multiple
        baseline = None
    report = build_report(
        item,
        transcript,
        judge_fn=judge_fn,
        baseline=baseline,
        creator_metrics=_creator_metrics(creator_db, content_id),
        glossary=glossary,
        generated_at=generated_at,
    )
    paths = _write_report(report, data_dir)
    # The transcript is written and the report is on disk; the video itself is dead weight.
    freed = prune_media(content_dir)
    return {"content_id": report["content_id"], "freed_bytes": freed, **paths}


def run_pipeline(
    urls: Sequence[str],
    *,
    cookie_path: Path,
    data_dir: Path,
    downloads_dir: Path | None = None,
    download_fn: Callable[[str, Path, Path], Path] = _download_one,
    extract_fn: Callable[[Path, str], Path] = _extract_one,
    whisper_model: str = "turbo",
    generated_at: str | None = None,
    judge_fn: JudgeFn = cli_judge,
    baseline_fn: Callable[[Path, Path, Path], dict[str, Any] | None] = _default_baseline,
    creator_db: Path | None = None,
    glossary_path: Path | None = DEFAULT_GLOSSARY_PATH,
) -> dict:
    """Run download → transcribe → structure → report serially for URLs."""
    if not urls:
        raise PipelineError("at least one video URL is required")
    data_dir = _secure_dir(data_dir)
    downloads_dir = _secure_dir(downloads_dir or data_dir / "downloads")
    run_at = generated_at or datetime.now(timezone.utc).isoformat()
    glossary = load_glossary(glossary_path)
    results: list[dict] = []
    for url in urls:
        try:
            paths = process_url(
                url,
                cookie_path=cookie_path,
                data_dir=data_dir,
                downloads_dir=downloads_dir,
                download_fn=download_fn,
                extract_fn=extract_fn,
                whisper_model=whisper_model,
                generated_at=run_at,
                judge_fn=judge_fn,
                baseline_fn=baseline_fn,
                creator_db=creator_db,
                glossary=glossary,
            )
            results.append({"status": "ok", "url": url, **paths})
        except Exception as exc:  # noqa: BLE001
            results.append({"status": "failed", "url": url, "error": str(exc)})

    status = "ok" if all(result["status"] == "ok" for result in results) else "partial"
    receipt = {"status": status, "generated_at": run_at, "reports": results}
    receipt_path = data_dir / "pipeline-run.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt_path.chmod(0o600)
    return receipt
