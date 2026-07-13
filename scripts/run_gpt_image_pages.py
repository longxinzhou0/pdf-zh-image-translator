#!/usr/bin/env python3
"""Batch-run gpt-image edits for prepared PDF page images."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request


DEFAULT_IMAGE_BASE_URL = "https://img.proxy2it.com/v1"
GENERAL_PROXY_BASE_URL = "https://api.proxy2it.com/v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True, type=Path, help="Prepared translation work directory")
    parser.add_argument("--model", default="gpt-image-2", help="Image model passed to gpt-image")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OPENAI_BASE_URL") or DEFAULT_IMAGE_BASE_URL,
        help="Image API base URL exported as OPENAI_BASE_URL for gpt-image",
    )
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Environment variable containing API key")
    parser.add_argument(
        "--gpt-image-skill-dir",
        type=Path,
        help="Path to the gpt-image skill directory. Defaults to a sibling 'gpt-image' skill folder.",
    )
    parser.add_argument("--quality", default="high", choices=["low", "medium", "high", "auto"])
    parser.add_argument(
        "--size",
        default="source",
        help="gpt-image --size value. Use 'source' to match each rendered page size; set a literal or shortcut to override.",
    )
    parser.add_argument("--start-page", type=int, help="1-based inclusive start page")
    parser.add_argument("--end-page", type=int, help="1-based inclusive end page")
    parser.add_argument("--force", action="store_true", help="Regenerate pages even when raw output exists")
    parser.add_argument("--preflight-only", action="store_true", help="Check key, endpoint, and gpt-image launcher only")
    parser.add_argument("--skip-model-check", action="store_true", help="Skip /models endpoint check")
    parser.add_argument("--timeout", type=int, default=900, help="Per-page gpt-image timeout in seconds")
    return parser.parse_args()


def normalize_base_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base == GENERAL_PROXY_BASE_URL:
        print(f"Switching general proxy endpoint to image endpoint: {DEFAULT_IMAGE_BASE_URL}")
        return DEFAULT_IMAGE_BASE_URL
    return base


def load_manifest(workdir: Path) -> dict:
    manifest_path = workdir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"manifest.json not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def gpt_image_launcher(skill_dir: Path) -> Path:
    launcher = skill_dir / "scripts" / "generate.py"
    if not launcher.exists():
        raise SystemExit(f"gpt-image launcher not found: {launcher}")
    return launcher


def default_gpt_image_skill_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "gpt-image"


def preflight(base_url: str, api_key: str, model: str, launcher: Path, env: dict[str, str], skip_model_check: bool) -> None:
    help_result = subprocess.run(
        [sys.executable, str(launcher), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if help_result.returncode != 0:
        details = (help_result.stderr or help_result.stdout).strip()
        raise SystemExit(
            "gpt-image launcher is present but no working CLI backend was found.\n"
            "Install the gpt-image CLI backend or make uv/uvx available on PATH, then rerun this skill.\n"
            f"Launcher output:\n{details}"
        )

    if skip_model_check:
        print("Preflight OK: gpt-image launcher found; /models check skipped.")
        return

    req = request.Request(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
    try:
        with request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Image API preflight failed: HTTP {exc.code}\n{details}") from exc
    except Exception as exc:
        raise SystemExit(f"Image API preflight failed: {exc}") from exc

    model_ids = {item.get("id") for item in payload.get("data", []) if isinstance(item, dict)}
    if model_ids and model not in model_ids:
        print(f"Warning: model {model!r} was not listed by /models; continuing because proxies may omit image models.")
    print(f"Preflight OK: {base_url}")


def page_in_scope(page_number: int, start_page: int | None, end_page: int | None) -> bool:
    if start_page is not None and page_number < start_page:
        return False
    if end_page is not None and page_number > end_page:
        return False
    return True


def append_log(log_path: Path, payload: dict) -> None:
    payload = {"logged_at": dt.datetime.now(dt.timezone.utc).isoformat(), **payload}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def round_to_api_multiple(value: float) -> int:
    return max(16, int(round(value / 16.0)) * 16)


def size_for_page(page: dict, requested_size: str) -> str | None:
    if not requested_size:
        return None
    if requested_size != "source":
        return requested_size

    width = int(page.get("render_width_px") or 0)
    height = int(page.get("render_height_px") or 0)
    if width <= 0 or height <= 0:
        return None

    # gpt-image accepts literal sizes with max edge up to 3840 and 16px multiples.
    scale = min(1.0, 3840.0 / max(width, height))
    out_width = round_to_api_multiple(width * scale)
    out_height = round_to_api_multiple(height * scale)
    return f"{out_width}x{out_height}"


def run_page(
    page: dict,
    launcher: Path,
    out_dir: Path,
    env: dict[str, str],
    model: str,
    quality: str,
    size: str,
    force: bool,
    timeout: int,
    log_path: Path,
) -> None:
    page_number = int(page["page_number"])
    source_image = Path(page["image_path"])
    prompt_path = Path(page["prompt_path"])
    output_path = out_dir / f"page-{page_number:03d}.png"

    if output_path.exists() and output_path.stat().st_size > 0 and not force:
        print(f"Skip page {page_number}: existing raw output")
        append_log(log_path, {"page": page_number, "status": "skipped", "output": str(output_path)})
        return
    if not source_image.exists():
        raise SystemExit(f"Missing source page image: {source_image}")
    if not prompt_path.exists():
        raise SystemExit(f"Missing prompt: {prompt_path}")

    prompt = prompt_path.read_text(encoding="utf-8")
    command = [
        sys.executable,
        str(launcher),
        "-p",
        prompt,
        "-i",
        str(source_image),
        "-f",
        str(output_path),
        "--model",
        model,
        "--quality",
        quality,
    ]
    resolved_size = size_for_page(page, size)
    if resolved_size:
        command.extend(["--size", resolved_size])

    started = time.time()
    print(f"Run page {page_number}: {output_path} size={resolved_size or 'cli-default'}")
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=timeout,
        check=False,
    )
    elapsed = round(time.time() - started, 2)
    if completed.returncode != 0:
        append_log(
            log_path,
            {
                "page": page_number,
                "status": "error",
                "elapsed_seconds": elapsed,
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            },
        )
        raise SystemExit(
            f"gpt-image failed on page {page_number} with exit code {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    if not output_path.exists() or output_path.stat().st_size == 0:
        append_log(log_path, {"page": page_number, "status": "error", "elapsed_seconds": elapsed, "error": "missing output"})
        raise SystemExit(f"gpt-image reported success but output is missing: {output_path}")

    append_log(
        log_path,
        {
            "page": page_number,
            "status": "ok",
            "elapsed_seconds": elapsed,
            "output": str(output_path),
            "model": model,
            "quality": quality,
            "size": resolved_size,
        },
    )
    print(f"Page {page_number} done in {elapsed}s")


def main() -> int:
    args = parse_args()
    workdir = args.workdir.expanduser().resolve()
    manifest = load_manifest(workdir)
    base_url = normalize_base_url(args.base_url)
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"{args.api_key_env} is not set")

    gpt_image_skill_dir = args.gpt_image_skill_dir or default_gpt_image_skill_dir()
    launcher = gpt_image_launcher(gpt_image_skill_dir.expanduser().resolve())
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = api_key
    env["OPENAI_BASE_URL"] = base_url

    preflight(base_url, api_key, args.model, launcher, env, args.skip_model_check)
    if args.preflight_only:
        return 0

    out_dir = workdir / "translated_pages_raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = workdir / "gpt_image_run_log.jsonl"

    selected = [
        page
        for page in manifest.get("pages", [])
        if page_in_scope(int(page["page_number"]), args.start_page, args.end_page)
    ]
    if not selected:
        raise SystemExit("No manifest pages matched the requested page range.")

    for page in selected:
        run_page(page, launcher, out_dir, env, args.model, args.quality, args.size, args.force, args.timeout, log_path)

    print(f"Raw translated pages: {out_dir}")
    print(f"Run log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
