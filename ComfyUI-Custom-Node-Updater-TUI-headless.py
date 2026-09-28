#!/usr/bin/env python3
"""Headless runner for ComfyUI-Custom-Node-Updater-TUI.

Scans every git repo in one or more custom_nodes directories and fast-forwards
the safe ones, using the EXACT same safety gate as the TUI (pull_reason /
pull from the main module): fast-forward only, never merges/rebases/forces,
skips diverged/detached repos, autostash with overlap protection.

Usage:
    python -X utf8 ComfyUI-Custom-Node-Updater-TUI-headless.py [--nodes-dir DIR ...] [--no-pull] [--no-fetch]

    --nodes-dir DIR   custom_nodes dir to process (repeatable; default: the
                      DEFAULT_NODES_DIRS list below)
    --no-pull         dry run: scan and report, change nothing
    --no-fetch        compare against local refs only (no network fetch)

Output:
    - console summary
    - appended to activity.log (same file/dir as the TUI's log)
    - JSON summary written to last-headless-run.json (same dir)

Exit code: 0 on success (even if some repos were skipped), 1 on fatal error.
A stale-lock guard prevents overlapping runs (e.g. scheduled + manual).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN_SCRIPT = HERE / "ComfyUI-Custom-Node-Updater-TUI.py"

# Active custom_nodes dirs on this machine (2026-09-28). Override with --nodes-dir.
DEFAULT_NODES_DIRS = [
    r"E:\AI\ComfyUI-Easy-Install\ComfyUI\custom_nodes",
    r"E:\AI\ComfyUI-Easy-VRGDG-PROD\ComfyUI\custom_nodes",
    r"E:\AI\ComfyUI-Easy-VRGDG-TEST\ComfyUI\custom_nodes",
    r"E:\AI\ComfyUI-Python-3.13\ComfyUI\custom_nodes",
    r"D:\AI\ComfyUI-Installs\HERMES\custom_nodes",
]

LOCK_STALE_SECONDS = 6 * 3600  # a lock older than 6h is considered stale


def load_module():
    spec = importlib.util.spec_from_file_location("cnu_tui", MAIN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cnu_tui"] = module  # required: dataclasses resolve the module via sys.modules
    spec.loader.exec_module(module)
    return module


def log_line(module, text: str) -> None:
    """Append to the shared activity.log (plain, timestamped)."""
    try:
        path = module.log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {text}\n")
    except OSError:
        pass


def acquire_lock(module) -> Path | None:
    lock = module.log_path().parent / "headless.lock"
    try:
        if lock.exists():
            age = time.time() - lock.stat().st_mtime
            if age < LOCK_STALE_SECONDS:
                return None  # another run in progress
        lock.write_text(f"pid={__import__('os').getpid()} started={datetime.now().isoformat()}\n", encoding="utf-8")
        return lock
    except OSError:
        return None


def release_lock(lock: Path | None) -> None:
    if lock is not None:
        try:
            lock.unlink()
        except OSError:
            pass


def discover_repos(module, nodes_dir: Path) -> list:
    """Immediate subdirectories that are git repos (same scope as the TUI)."""
    repos = []
    for entry in sorted(nodes_dir.iterdir()):
        if entry.is_dir() and (entry / ".git").exists():
            repos.append(module.Repo(path=entry, name=entry.name))
    return repos


def main() -> int:
    parser = argparse.ArgumentParser(description="Headless ComfyUI custom-node updater")
    parser.add_argument("--nodes-dir", type=Path, action="append", default=None,
                       help="custom_nodes dir to process (repeatable)")
    parser.add_argument("--no-pull", action="store_true", help="dry run: report only")
    parser.add_argument("--no-fetch", action="store_true", help="skip the network fetch")
    args = parser.parse_args()

    if not MAIN_SCRIPT.is_file():
        print(f"fatal: main script not found at {MAIN_SCRIPT}", file=sys.stderr)
        return 1
    module = load_module()

    lock = acquire_lock(module)
    if lock is None:
        print("another headless run appears to be in progress (fresh lock file) - exiting")
        return 1

    nodes_dirs = [Path(d) for d in (args.nodes_dir or DEFAULT_NODES_DIRS)]
    run_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line(module, f"headless run start ({'dry-run' if args.no_pull else 'pull'}, "
                    f"fetch={'off' if args.no_fetch else 'on'}, {len(nodes_dirs)} dir(s))")

    summary = {"run": run_id, "dry_run": args.no_pull, "dirs": [], "repos": 0,
              "pulled": [], "skipped": {}, "errors": []}

    try:
        for nodes_dir in nodes_dirs:
            nodes_dir = nodes_dir.expanduser().resolve()
            dir_report = {"dir": str(nodes_dir), "repos": 0, "pulled": [], "skipped": {}, "errors": []}
            summary["dirs"].append(dir_report)
            if not nodes_dir.is_dir():
                dir_report["errors"].append("directory not found")
                log_line(module, f"skip dir {nodes_dir} - not found")
                continue

            repos = discover_repos(module, nodes_dir)
            dir_report["repos"] = len(repos)
            log_line(module, f"scanning {nodes_dir} ({len(repos)} repos)")

            # Parallel scan (same pattern as the TUI).
            with ThreadPoolExecutor(max_workers=min(module.MAX_FETCH_THREADS, max(len(repos), 1))) as pool:
                futures = {pool.submit(scan_one, module, repo, not args.no_fetch): repo for repo in repos}
                for future in as_completed(futures):
                    repo = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        repo.error = f"scan error: {exc}"

            # Sequential pulls (same as the TUI - safer for git locks).
            for repo in repos:
                if args.no_pull:
                    reason = module.pull_reason(repo, autostash=True)
                    if reason is None:
                        log_line(module, f"[dry] would pull {repo.name}")
                        dir_report["pulled"].append(repo.name)
                    else:
                        dir_report["skipped"].setdefault(reason, []).append(repo.name)
                    continue
                ok, message = module.pull(repo, autostash=True)
                if ok:
                    dir_report["pulled"].append(repo.name)
                    log_line(module, f"ok   {repo.name} - {message}")
                else:
                    dir_report["skipped"].setdefault(message, []).append(repo.name)
                    log_line(module, f"skip {repo.name} - {message}")
                if repo.error:
                    dir_report["errors"].append(f"{repo.name}: {repo.error}")

            summary["repos"] += len(repos)
            summary["pulled"].extend(dir_report["pulled"])
            for reason, names in dir_report["skipped"].items():
                summary["skipped"].setdefault(reason, []).extend(names)
            summary["errors"].extend(dir_report["errors"])
            log_line(module, f"dir done: {nodes_dir} - {len(dir_report['pulled'])} pulled, "
                           f"{sum(len(v) for v in dir_report['skipped'].values())} skipped")
    finally:
        release_lock(lock)

    # JSON summary (same dir as activity.log).
    try:
        module.log_path().parent.mkdir(parents=True, exist_ok=True)
        (module.log_path().parent / "last-headless-run.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"warning: could not write JSON summary: {exc}", file=sys.stderr)

    pulled_n = len(summary["pulled"])
    skipped_n = sum(len(v) for v in summary["skipped"].values())
    log_line(module, f"headless run complete: {pulled_n} pulled, {skipped_n} skipped, "
                    f"{len(summary['errors'])} errors")
    print(f"done: {pulled_n} pulled, {skipped_n} skipped, {len(summary['errors'])} errors "
          f"(report: {module.log_path()})")
    return 0


def scan_one(module, repo, fetch: bool) -> None:
    module.inspect_repo(repo)
    if fetch:
        module.remote_fetch(repo)
    repo.target = module.resolve_target(repo)
    module.update_counts(repo)


if __name__ == "__main__":
    sys.exit(main())
