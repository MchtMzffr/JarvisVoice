"""Narrow Windows application adapter; only direct user commands may call it.

The caller owns consent, rate limits and cancellation. Model output, web text,
plans, paths and shell snippets must never be routed into ``launch_application``.
Successful process creation is reported as a request, not proof of a visible UI.
"""
from dataclasses import dataclass
import ctypes
import ntpath
import os
import re
import subprocess
import sys
from types import MappingProxyType
from typing import Literal
import unicodedata

from .config import SETTINGS


@dataclass(frozen=True)
class AppSpec:
    id: str
    label: str
    relative_executable: tuple[str, ...]
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class LaunchResult:
    app_id: str
    label: str
    status: Literal["requested", "unavailable", "unsupported_platform", "failed"]
    message: str


APP_SPECS = (
    AppSpec("calculator", "Hesap Makinesi", ("System32", "calc.exe"),
            ("hesap makinesi", "hesap makinesini", "hesapmakinesi", "hesapmakinesini", "calculator", "calculatori")),
    AppSpec("notepad", "Not Defteri", ("System32", "notepad.exe"),
            ("not defteri", "not defterini", "notdefteri", "notdefterini", "notepad", "notepadi")),
    AppSpec("explorer", "Dosya Gezgini", ("explorer.exe",),
            ("dosya gezgini", "dosya gezginini", "dosya yoneticisi", "dosya yoneticisini", "explorer", "exploreri")),
    AppSpec("paint", "Paint", ("System32", "mspaint.exe"),
            ("paint", "painti", "mspaint", "mspainti", "boya", "boyayi")),
)
_BY_ID = MappingProxyType({app.id: app for app in APP_SPECS})
_ALIASES = MappingProxyType({alias: app.id for app in APP_SPECS for alias in app.aliases})
_children: list[subprocess.Popen] = []


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.translate(str.maketrans("ıçğöşüâîû’", "icgosuaiu'"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def application_command(text: str, assistant_name: str = "Jarvis") -> str | None:
    """Recognize one explicit command; no substring or fuzzy intent matching.

    ``unsupported`` means an explicit simple open request names an unknown app.
    Pronouns, negation, quotation and chained/narrative text are not commands.
    """
    if not isinstance(text, str) or not text or len(text) > SETTINGS.max_text_chars:
        return None
    if any(unicodedata.category(char).startswith("C") or char in "\n\r\t" for char in text):
        return None
    command = _fold(text).strip()
    name = _fold(assistant_name).strip() if isinstance(assistant_name, str) else ""
    if name:
        command = re.sub(r"^(?:hey +)?" + re.escape(name) + r"(?:, *| +)", "", command, count=1)
    command = re.sub(r"^lutfen +", "", command, count=1)
    match = re.fullmatch(
        r"([a-z][a-z0-9]*(?:'[a-z]+)?(?: +[a-z][a-z0-9]*(?:'[a-z]+)?){0,3}) +"
        r"(?:ac|acar misin|acar misiniz|acabilir misin|acabilir misiniz|"
        r"baslat|baslatir misin|baslatabilir misin|calistir|calistirir misin)"
        r"(?: +lutfen)?[.!?]*",
        command,
    )
    if match is None:
        return None
    target = " ".join(match.group(1).replace("'", "").split())
    if set(target.split()).intersection({
        "onu", "bunu", "sunu", "bu", "su", "birini", "birisini", "hepsini",
        "tumunu", "uygulamayi", "programi", "sakin", "asla", "belki", "ornegin",
        "diyelim", "eger", "ve", "veya", "ya", "da", "ama", "sonra", "once",
        "ac", "acma", "hicbirini", "hicbir", "yalniz", "degil",
    }):
        return None
    return _ALIASES.get(target, "unsupported")


def _is_windows() -> bool:
    return sys.platform == "win32"


def _windows_directory() -> str:
    """Ask Windows itself; never select an executable via PATH or SystemRoot."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_directory = kernel.GetWindowsDirectoryW
    get_directory.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    get_directory.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_directory(buffer, len(buffer))
    if length == 0 or length >= len(buffer):
        raise OSError("Windows directory unavailable")
    return buffer.value


def _executable(app: AppSpec) -> str:
    root = _windows_directory()
    if not isinstance(root, str) or "\0" in root:
        raise OSError("Invalid Windows directory")
    root = ntpath.normpath(root)
    drive, tail = ntpath.splitdrive(root)
    # No relative, UNC, device or drive-relative path can become a launcher.
    if not re.fullmatch(r"[A-Za-z]:", drive) or not tail.startswith("\\"):
        raise OSError("Invalid Windows directory")
    return ntpath.join(root, *app.relative_executable)


def apps_catalog() -> list[dict]:
    result = []
    for app in APP_SPECS:
        available = False
        if _is_windows():
            try:
                available = os.path.isfile(_executable(app))
            except (OSError, ValueError, AttributeError):
                pass
        result.append({"id": app.id, "label": app.label, "available": available})
    return result


def _reap_children() -> None:
    """Only nonblocking poll; never stop a user application or wait for exit."""
    active = []
    for child in _children:
        try:
            if child.poll() is None:
                active.append(child)
        except OSError:
            # Keep an uncertain handle tracked; bounded capacity fails closed.
            active.append(child)
    _children[:] = active


def launch_application(app_id: str) -> LaunchResult:
    app = _BY_ID.get(app_id) if isinstance(app_id, str) else None
    if app is None:
        return LaunchResult("", "Uygulama", "unavailable", "Bu uygulama izin listesinde yok.")
    if not _is_windows():
        return LaunchResult(app.id, app.label, "unsupported_platform", "Uygulama açma bu sürümde yalnız Windows üzerinde kullanılabilir.")
    _reap_children()
    if len(_children) >= SETTINGS.desktop_max_tracked_processes:
        return LaunchResult(app.id, app.label, "failed", "Başlatılan uygulamalar için takip sınırına ulaşıldı. Açtığın uygulamalardan birini kapatıp yeniden dene.")
    try:
        executable = _executable(app)
        if not os.path.isfile(executable):
            return LaunchResult(app.id, app.label, "unavailable", f"{app.label} bu bilgisayarda beklenen konumda bulunamadı.")
        process = subprocess.Popen(
            [executable], shell=False, cwd=ntpath.dirname(executable),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        _children.append(process)
        _reap_children()
    except (OSError, ValueError, AttributeError):
        return LaunchResult(app.id, app.label, "failed", f"{app.label} için başlatma isteği gönderilemedi.")
    return LaunchResult(app.id, app.label, "requested", f"{app.label} için başlatma isteği gönderildi.")
