"""Install/check local prerequisites; never called by a model or web response.

Only the explicit KUR launcher passes --install-missing. Normal startup may
start an existing Ollama service, but never installs software or pulls models.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

from .config import SETTINGS


class SetupError(RuntimeError):
    pass


class ServiceUnavailable(SetupError):
    pass


def _connection(timeout=None):
    address = urlsplit(SETTINGS.ollama_url)
    if (address.scheme != "http" or address.hostname not in {"127.0.0.1", "localhost"}
            or address.username or address.password or address.path not in {"", "/"}
            or address.query or address.fragment):
        raise SetupError("Yalnız bu bilgisayardaki Ollama adresi kullanılabilir.")
    return http.client.HTTPConnection(address.hostname, address.port or 80,
                                      timeout=timeout or SETTINGS.ollama_probe_timeout_s)


def installed_models():
    connection = _connection()
    try:
        connection.request("GET", "/api/tags")
        response = connection.getresponse()
        if response.status != 200:
            raise ServiceUnavailable("Yerel Ollama model listesine ulaşılamadı.")
        raw = response.read(SETTINGS.setup_http_max_bytes + 1)
        if len(raw) > SETTINGS.setup_http_max_bytes:
            raise SetupError("Ollama model listesi boyut sınırını aşıyor.")
        body = json.loads(raw)
        if not isinstance(body, dict) or not isinstance(body.get("models"), list):
            raise SetupError("Ollama model listesi doğrulanamadı.")
        return [item["name"] for item in body["models"]
                if isinstance(item, dict) and isinstance(item.get("name"), str)]
    except (OSError, http.client.HTTPException):
        raise ServiceUnavailable("Yerel Ollama sunucusuna ulaşılamadı.") from None
    except (ValueError, UnicodeError):
        raise SetupError("Ollama yanıt biçimi doğrulanamadı.") from None
    finally:
        connection.close()


def ollama_executable():
    candidates = []
    if sys.platform == "win32":
        for variable, parts in (("LOCALAPPDATA", ("Programs", "Ollama", "ollama.exe")),
                                ("ProgramFiles", ("Ollama", "ollama.exe"))):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]).joinpath(*parts))
    found = shutil.which("ollama")
    if found:
        candidates.append(Path(found))
    for path in candidates:
        if path.is_absolute() and path.is_file() and (sys.platform != "win32" or path.suffix.lower() == ".exe"):
            return path
    return None


def install_package(package_id):
    if package_id not in {"Ollama.Ollama", "Microsoft.EdgeWebView2Runtime"}:
        raise SetupError("Kurulum paketi izin listesinde değil.")
    winget = shutil.which("winget")
    if sys.platform != "win32" or not winget:
        raise SetupError("Windows Uygulama Yükleyicisi (winget) bulunamadı. Ollama için https://ollama.com/download/windows ve WebView2 için https://developer.microsoft.com/microsoft-edge/webview2 adreslerini kullan; sonra KUR.cmd dosyasını yeniden aç.")
    try:
        result = subprocess.run([winget, "install", "--id", package_id, "--exact", "--source", "winget",
                                 "--accept-source-agreements", "--accept-package-agreements"], shell=False, check=False)
    except OSError:
        raise SetupError("Paket kurulum aracı başlatılamadı.") from None
    if result.returncode:
        raise SetupError("Paket kurulumu tamamlanmadı. Yukarıdaki winget sonucunu kontrol et.")


def ensure_service(*, install_missing=False, progress=print):
    try:
        return installed_models()
    except ServiceUnavailable:
        pass
    executable = ollama_executable()
    if executable is None and install_missing:
        progress("Ollama kuruluyor; Windows kurulum penceresi açılabilir.")
        install_package("Ollama.Ollama")
        executable = ollama_executable()
    if executable is None:
        raise SetupError("Ollama bulunamadı. KUR.cmd ile ilk kurulumu tamamla.")
    # A package installer may already have started the service.
    try:
        return installed_models()
    except ServiceUnavailable:
        pass
    progress("Yerel Ollama servisi başlatılıyor…")
    environment = dict(os.environ)
    environment["OLLAMA_HOST"] = urlsplit(SETTINGS.ollama_url).netloc
    try:
        process = subprocess.Popen([str(executable), "serve"], shell=False, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   close_fds=True, env=environment,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        raise SetupError("Ollama servisi başlatılamadı. Ollama uygulamasını açıp yeniden dene.") from None
    deadline = time.monotonic() + SETTINGS.ollama_startup_timeout_s
    while time.monotonic() < deadline:
        try:
            return installed_models()
        except ServiceUnavailable:
            if process.poll() is not None:
                break
            time.sleep(0.25)
    raise SetupError("Ollama servisi zamanında hazır olmadı. Ollama uygulamasını açıp yeniden dene.")


def pull_model(progress=print):
    """Download the fixed configured local model through loopback only."""
    if SETTINGS.model != "gpt-oss:20b":
        raise SetupError("Bu kurulum yalnız gpt-oss:20b yerel modelini indirir.")
    connection = _connection(SETTINGS.model_download_timeout_s)
    last_percent = None
    completed = False
    try:
        body = json.dumps({"model": SETTINGS.model, "stream": True})
        connection.request("POST", "/api/pull", body, {"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise SetupError("Yerel model indirme isteği kabul edilmedi.")
        while True:
            line = response.readline(65537)
            if not line:
                break
            if len(line) > 65536:
                raise SetupError("Model indirme yanıtı boyut sınırını aştı.")
            part = json.loads(line)
            if not isinstance(part, dict) or part.get("error"):
                raise SetupError("Model indirilemedi. İnternet bağlantısını ve boş disk alanını kontrol et.")
            if part.get("status") == "success":
                completed = True
                break
            total, downloaded = part.get("total"), part.get("completed")
            if type(total) is int and type(downloaded) is int and total > 0 and 0 <= downloaded <= total:
                percent = downloaded * 100 // total
                if percent != last_percent:
                    progress(f"Model indirme: %{percent}")
                    last_percent = percent
        if not completed:
            raise SetupError("Model indirme tamamlanmadan bağlantı kesildi. KUR.cmd ile yeniden deneyebilirsin.")
    except (OSError, http.client.HTTPException, ValueError, UnicodeError):
        raise SetupError("Model indirme tamamlanamadı. KUR.cmd ile yeniden deneyebilirsin.") from None
    finally:
        connection.close()


def webview2_available():
    if sys.platform != "win32":
        return False
    import winreg
    key = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                    version, _ = winreg.QueryValueEx(handle, "pv")
                if isinstance(version, str) and version and version != "0.0.0.0":
                    return True
            except OSError:
                continue
    return False


def setup(*, install_missing=False, progress=print):
    if sys.platform == "win32" and not webview2_available():
        if not install_missing:
            raise SetupError("Masaüstü penceresi için WebView2 gerekli. KUR.cmd dosyasını aç.")
        progress("Microsoft WebView2 masaüstü bileşeni kuruluyor…")
        install_package("Microsoft.EdgeWebView2Runtime")
        if not webview2_available():
            raise SetupError("WebView2 kurulumu doğrulanamadı. Windows'u yeniden başlatıp KUR.cmd dosyasını tekrar aç.")
    models = ensure_service(install_missing=install_missing, progress=progress)
    if SETTINGS.model not in models:
        if not install_missing:
            raise SetupError("gpt-oss:20b bulunamadı. KUR.cmd dosyasını aç.")
        progress("gpt-oss:20b indiriliyor (yaklaşık 13 GB). Mevcut Ollama modelleri korunur.")
        pull_model(progress)
        if SETTINGS.model not in installed_models():
            raise SetupError("Model indirildi ancak yerel model listesinde doğrulanamadı.")
    progress("Yerel Ollama ve gpt-oss:20b hazır.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-missing", action="store_true")
    args = parser.parse_args()
    try:
        setup(install_missing=args.install_missing, progress=lambda text: print(text, flush=True))
    except (SetupError, OSError) as exc:
        print(str(exc) if isinstance(exc, SetupError) else "Yerel kurulum kontrolü tamamlanamadı.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
