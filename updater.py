import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from typing import Optional, Callable

APP_VERSION = "1.0.0"
GITHUB_API_URL = "https://api.github.com/repos/mozu93/audio_splitter/releases/latest"
_TIMEOUT = 8


def is_newer_version(current: str, latest: str) -> bool:
    try:
        c = tuple(int(x) for x in current.lstrip("v").split("."))
        l = tuple(int(x) for x in latest.lstrip("v").split("."))
        return l > c
    except Exception:
        return False


def check_latest_version() -> Optional[dict]:
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "audio-splitter-updater",
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name", "")
        assets = data.get("assets", [])
        if not tag or not assets:
            return None
        download_url = next(
            (a["browser_download_url"] for a in assets if a.get("name", "").lower().endswith(".exe")),
            assets[0].get("browser_download_url", ""),
        )
        return {"tag_name": tag, "html_url": data.get("html_url", ""), "download_url": download_url}
    except Exception:
        return None


def download_update(
    url: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "audio-splitter-updater"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", -1))
            fd, tmp_path = tempfile.mkstemp(prefix="AudioSplitter_new_", suffix=".exe")
            received = 0
            with os.fdopen(fd, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    if progress_callback:
                        progress_callback(received, total)
        return tmp_path
    except Exception:
        return None


def launch_updater(new_exe_path: str) -> None:
    """バッチ経由で新EXEを上書きコピーして起動し、現アプリを終了する。"""
    current_exe = sys.executable
    fd, bat_path = tempfile.mkstemp(prefix="audio_splitter_updater_", suffix=".bat")
    with os.fdopen(fd, "w", encoding="cp932") as f:
        f.write("@echo off\r\n")
        f.write("timeout /t 3 /nobreak > nul\r\n")
        f.write(f'copy /y "{new_exe_path}" "{current_exe}"\r\n')
        f.write(f'if exist "{new_exe_path}" del "{new_exe_path}"\r\n')
        f.write(f'start "" "{current_exe}"\r\n')
        f.write('del "%~f0"\r\n')
    subprocess.Popen(
        ["cmd", "/c", bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    sys.exit(0)
