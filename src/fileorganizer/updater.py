import json
import subprocess
import sys
import urllib.request
from pathlib import Path

VERSION = "1.2.1"
_REPO   = "SantyCano2022/file-organizer"
_API    = f"https://api.github.com/repos/{_REPO}/releases/latest"


def get_latest_release() -> tuple[str, str] | None:
    """Consulta GitHub y retorna (tag, url_exe) si hay release, o None."""
    try:
        req = urllib.request.Request(_API, headers={"User-Agent": "FileOrganizer"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
        tag = data["tag_name"]
        for asset in data.get("assets", []):
            if asset["name"].lower().endswith(".exe"):
                return tag, asset["browser_download_url"]
    except Exception:
        pass
    return None


def is_newer(tag: str) -> bool:
    def parse(v: str) -> tuple:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    try:
        return parse(tag) > parse(VERSION)
    except Exception:
        return False


def download_and_apply(url: str, on_progress=None) -> bool:
    """Descarga el nuevo exe y programa su reemplazo al cerrar la app."""
    if not getattr(sys, "frozen", False):
        return False

    current = Path(sys.executable)
    tmp     = current.parent / f"{current.stem}_update.exe"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FileOrganizer"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total      = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(tmp, "wb") as f:
                while chunk := resp.read(8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and total:
                        on_progress(downloaded / total)
    except Exception:
        tmp.unlink(missing_ok=True)
        return False

    bat = current.parent / "_update.bat"
    bat.write_text(
        "@echo off\n"
        "timeout /t 3 /nobreak > NUL\n"
        f'move /Y "{tmp}" "{current}"\n'
        f'start "" "{current}"\n'
        'del "%~f0"\n',
        encoding="utf-8",
    )
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    return True
