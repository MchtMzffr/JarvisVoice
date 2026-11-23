"""Offline, code-only Jarvis Voice 0.1.0/0.2.0 -> 0.2.1 update with verified backups.

Run with the installed app's Python 3.11. No application module is imported;
models, profiles, memories, virtual environments and global settings are never
copied or rewritten. Windows execution is separate from the portable tests.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import socket
import stat
import sys
import tempfile
import tomllib
import uuid


RELEASE_VERSION = "0.2.1"
SUPPORTED_TARGETS = {"0.1.0", "0.2.0", "0.2.1"}
RELEASE_DIRS = {"jarvis", "tests", "docs"}
RELEASE_FILES = {
    "KUR.cmd", "BASLAT.cmd", "pyproject.toml", "uv.lock", "README.md",
    "SES_ORNEGI.wav", ".gitignore", "GUNCELLE.cmd", "update_jarvis.py",
}
IGNORED_NAMES = {"__pycache__", ".venv", ".runtime", "data", "backups", ".git"}
MAX_FILE_BYTES = 16 * 1024 * 1024
UPDATER_PORT = 8765
REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class UpdateError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plain_components(path: Path) -> None:
    """Reject observed symlinks and Windows junction/reparse components."""
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE_FLAG:
            raise UpdateError("Bağlantı/junction içeren bir klasör güncellenemez. Gerçek kurulum klasörünü seç.")


def _root(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    _plain_components(absolute)
    if not absolute.is_dir():
        raise UpdateError("Kurulum veya güncelleme klasörü bulunamadı.")
    return absolute.resolve(strict=True)


def _inside(root: Path, path: Path) -> None:
    _plain_components(path)
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError:
        raise UpdateError("Dosya yolu izin verilen klasörün dışına çıkıyor.") from None


def allowed_relative(value: str) -> Path:
    if not isinstance(value, str) or "\\" in value or ":" in value or "\x00" in value:
        raise UpdateError("Güncelleme dosya yolu geçersiz.")
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or any(p in {".", ".."} for p in relative.parts):
        raise UpdateError("Güncelleme dosya yolu geçersiz.")
    if relative.as_posix() != value:
        raise UpdateError("Güncelleme dosya yolu normalleştirilmiş değil.")
    if any(p.casefold() in IGNORED_NAMES for p in relative.parts):
        raise UpdateError("Kullanıcı verileri ve çalışma ortamı güncelleme kapsamı dışındadır.")
    if not ((len(relative.parts) == 1 and value in RELEASE_FILES)
            or (len(relative.parts) > 1 and relative.parts[0] in RELEASE_DIRS)):
        raise UpdateError("Dosya güncelleme izin listesinde değil.")
    return Path(*relative.parts)


def _read_file(root: Path, path: Path) -> bytes:
    _inside(root, path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
        raise UpdateError("Güncellenecek dosya normal bir dosya değil veya boyut sınırını aşıyor.")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise UpdateError("Güncellenecek dosya boyut sınırını aşıyor.")
    return data


def _version(root: Path) -> str:
    try:
        tree = ast.parse(_read_file(root, root / "jarvis" / "__init__.py").decode("utf-8-sig"))
        versions = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets):
                value = ast.literal_eval(node.value)
                if isinstance(value, str):
                    versions.append(value)
        if len(versions) != 1:
            raise ValueError
        return versions[0]
    except (OSError, SyntaxError, ValueError, TypeError):
        raise UpdateError("Jarvis sürüm bilgisi okunamadı; dosyalar değiştirilmedi.") from None


def _project(root: Path) -> dict:
    try:
        return tomllib.loads(_read_file(root, root / "pyproject.toml").decode("utf-8-sig"))["project"]
    except (OSError, ValueError, KeyError, TypeError):
        raise UpdateError("Paket bağımlılık tanımı okunamadı; dosyalar değiştirilmedi.") from None


def _port_check_error(stage: str, exc: OSError) -> UpdateError:
    """Report only the operation, exception class and numeric OS error codes."""
    codes = []
    for name in ("errno", "winerror"):
        value = getattr(exc, name, None)
        codes.append(f"{name}={value if type(value) is int else 'yok'}")
    return UpdateError(
        f"{UPDATER_PORT} portu kontrol edilemedi ({stage}; {type(exc).__name__}; "
        + "; ".join(codes)
        + "). Portun boş olduğu doğrulanamadı; kurulum kodu değiştirilmedi."
    )


def jarvis_port_in_use() -> bool:
    """Return occupied/free, or raise when the operating system cannot tell.

    Windows uses a short-lived exclusive wildcard bind instead of a timed TCP
    connection. A specific-address bind can coexist with some wildcard sockets
    on Windows, so 0.0.0.0 is required for this probe. No listen, accept, connect,
    or SO_REUSEADDR operation is performed. An occupied port is never killed.

    Bind can conservatively reject a port whose earlier connections are still
    draining. Access errors may also mean a reservation or system policy; they
    are not evidence that Jarvis is running or that the port is free.
    """
    if sys.platform == "win32":
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is None:
            raise UpdateError(
                f"{UPDATER_PORT} portu kontrol edilemedi: Windows SO_EXCLUSIVEADDRUSE "
                "özelliği yok. Portun boş olduğu doğrulanamadı; kurulum kodu değiştirilmedi."
            )
        stage = "socket"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                stage = "setsockopt"
                probe.setsockopt(socket.SOL_SOCKET, exclusive, 1)
                stage = "bind"
                occupied = False
                try:
                    probe.bind(("0.0.0.0", UPDATER_PORT))
                except OSError as exc:
                    if exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) == 10048:
                        occupied = True
                    else:
                        raise
                stage = "close"
            return occupied
        except OSError as exc:
            raise _port_check_error(stage, exc) from None

    # Preserve the existing non-Windows probe. A timeout stays unknown rather
    # than being converted to 'free'; diagnostics now retain its type/codes.
    try:
        with socket.create_connection(("127.0.0.1", UPDATER_PORT), timeout=0.5):
            return True
    except ConnectionRefusedError:
        return False
    except OSError as exc:
        if getattr(exc, "winerror", None) == 10061:
            return False
        raise _port_check_error("connect", exc) from None


def _collect_release(source: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}

    def add(path: Path):
        relative = path.relative_to(source).as_posix()
        allowed_relative(relative)
        result[relative] = _read_file(source, path)

    def visit(directory: Path):
        _inside(source, directory)
        for path in sorted(directory.iterdir()):
            if path.name.casefold() in IGNORED_NAMES or path.name.startswith(".") or path.suffix.casefold() in {".pyc", ".pyo"}:
                continue
            _inside(source, path)
            if path.is_dir():
                visit(path)
            else:
                add(path)

    for name in sorted(RELEASE_FILES):
        path = source / name
        if not path.is_file():
            raise UpdateError(f"Güncelleme paketi eksik: {name}")
        add(path)
    for name in sorted(RELEASE_DIRS):
        path = source / name
        if not path.is_dir():
            raise UpdateError(f"Güncelleme paketi eksik: {name}")
        visit(path)
    if len({p.casefold() for p in result}) != len(result):
        raise UpdateError("Windows'ta aynı ada denk gelen güncelleme dosyaları var.")
    return dict(sorted(result.items()))


def _atomic_write(path: Path, data: bytes, root: Path) -> None:
    _inside(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _inside(root, path.parent)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".jarvis-update-", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _inside(root, path)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_manifest(backup: Path, manifest: dict, target: Path) -> None:
    payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(backup / "manifest.json", payload, target)


def _update(source: Path, target: Path, *, port_check=jarvis_port_in_use) -> dict:
    """Install only the allowlisted release bytes; return the verified backup.

    A normal write failure triggers rollback. Power loss or forced process
    termination requires manual restoration using files/ and manifest.json.
    Existing user files that are not in the release manifest are preserved.
    """
    source, target = _root(source), _root(target)
    if source == target or source in target.parents or target in source.parents:
        raise UpdateError("Yeni paket ve mevcut kurulum ayrı klasörlerde olmalı; iç içe klasör seçme.")
    if not (target / "jarvis").is_dir():
        raise UpdateError("Seçilen klasör mevcut Jarvis kurulumu değil.")
    for relative in ("BASLAT.cmd", ".venv/Scripts/python.exe", "data/prepared.json"):
        path = target / relative
        _inside(target, path)
        if not path.is_file():
            raise UpdateError("Tamamlanmış kurulum bulunamadı. Çalışan eski klasördeki BASLAT.cmd dosyasını seç.")
    old_version, new_version = _version(target), _version(source)
    if old_version not in SUPPORTED_TARGETS or new_version != RELEASE_VERSION:
        raise UpdateError(f"Bu güncelleme yalnız 0.1.0/0.2.0/0.2.1 kurulumunu {RELEASE_VERSION} sürümüne taşır.")
    old_project, new_project = _project(target), _project(source)
    if new_project.get("version") != RELEASE_VERSION:
        raise UpdateError("Yeni paket sürüm tanımları birbiriyle uyuşmuyor.")
    if old_project.get("version") != old_version:
        raise UpdateError("Mevcut kurulumun sürüm tanımları birbiriyle uyuşmuyor.")
    if (old_project.get("name") != "jarvis-voice-local" or new_project.get("name") != "jarvis-voice-local"
            or old_project.get("dependencies") != new_project.get("dependencies")
            or old_project.get("requires-python") != new_project.get("requires-python")):
        raise UpdateError("Bağımlılıklar farklı. Bu çevrimdışı güncelleme Python paketlerini değiştirmez.")
    if port_check():
        raise UpdateError("Jarvis açık veya 8765 portu kullanımda. Jarvis terminalini Ctrl+C ile kapatıp yeniden dene.")

    release = _collect_release(source)
    old: dict[str, bytes | None] = {}
    entries = []
    for relative, new_data in release.items():
        destination = target / allowed_relative(relative)
        _inside(target, destination)
        old_data = _read_file(target, destination) if destination.exists() else None
        old[relative] = old_data
        entries.append({
            "path": relative, "new_sha256": digest(new_data), "new_size": len(new_data),
            "old_sha256": digest(old_data) if old_data is not None else None,
            "old_size": len(old_data) if old_data is not None else None,
            "changed": old_data != new_data,
        })

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = target / "backups" / f"{timestamp}-{uuid.uuid4().hex[:8]}"
    _inside(target, backup)
    backup.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1, "from_version": old_version, "to_version": new_version,
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "preparing",
        "files": entries, "applied": [],
    }
    _write_manifest(backup, manifest, target)

    # Finish and verify all original-file backups before replacing any code.
    for entry in entries:
        relative = entry["path"]
        if entry["changed"] and old[relative] is not None:
            saved = backup / "files" / allowed_relative(relative)
            _atomic_write(saved, old[relative], target)
            if digest(_read_file(target, saved)) != entry["old_sha256"]:
                raise UpdateError("Kod yedeğinin doğrulaması başarısız. Kurulum dosyaları değiştirilmedi.")
    manifest["status"] = "prepared"
    _write_manifest(backup, manifest, target)
    if port_check():
        raise UpdateError("Jarvis güncelleme sırasında açıldı. Terminalini kapatıp yeniden dene; kod değiştirilmedi.")

    applied = []
    try:
        for entry in entries:
            if not entry["changed"]:
                continue
            relative = entry["path"]
            destination = target / allowed_relative(relative)
            current = _read_file(target, destination) if destination.exists() else None
            if current != old[relative]:
                raise UpdateError("Kurulumdaki bir dosya güncelleme sırasında değişti.")
            _atomic_write(destination, release[relative], target)
            applied.append(relative)
            if digest(_read_file(target, destination)) != entry["new_sha256"]:
                raise UpdateError("Yazılan kod dosyasının doğrulaması başarısız.")
            manifest["applied"] = list(applied)
            manifest["status"] = "applying"
            _write_manifest(backup, manifest, target)
        manifest["status"] = "complete"
        _write_manifest(backup, manifest, target)
    except BaseException as exc:
        failed = []
        for relative in reversed(applied):
            destination = target / allowed_relative(relative)
            try:
                # Never replace a user edit made while the update was running.
                if digest(_read_file(target, destination)) != digest(release[relative]):
                    raise UpdateError("Güncelleme sonrasında dosya değişmiş.")
                if old[relative] is None:
                    _inside(target, destination)
                    destination.unlink()
                else:
                    _atomic_write(destination, old[relative], target)
            except (OSError, UpdateError):
                failed.append(relative)
        manifest["status"] = "rollback_failed" if failed else "rolled_back"
        manifest["rollback_failed_files"] = failed
        try:
            _write_manifest(backup, manifest, target)
        except (OSError, UpdateError):
            pass
        if failed:
            raise UpdateError(f"Güncelleme durdu; bazı kod dosyaları geri alınamadı. Yedek: {backup}") from None
        raise UpdateError(f"Güncelleme tamamlanamadı; değişen kod geri alındı. Yedek: {backup}") from exc

    return {"backup": str(backup), "from_version": old_version, "to_version": new_version, "changed_files": len(applied)}


def update(source: Path, target: Path, *, port_check=jarvis_port_in_use) -> dict:
    # An exclusive marker prevents two simultaneous update processes from
    # making conflicting rollback decisions. A stale marker is not deleted
    # automatically: the user must first establish that no update is running.
    source, target = _root(source), _root(target)
    if source == target or source in target.parents or target in source.parents:
        raise UpdateError("Yeni paket ve mevcut kurulum ayrı klasörlerde olmalı; iç içe klasör seçme.")
    lock = target / ".jarvis-update.lock"
    _inside(target, lock)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise UpdateError("Bir güncelleme kilidi var. Çalışan güncellemeyi kapatma; bitmesini bekle.") from None
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        return _update(source, target, port_check=port_check)
    finally:
        os.close(descriptor)
        _inside(target, lock)
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mevcut Jarvis kurulumunu model indirmeden güncelle.")
    parser.add_argument("--target", required=True, type=Path, help="Mevcut BASLAT.cmd dosyasının bulunduğu klasör")
    args = parser.parse_args()
    try:
        result = update(Path(__file__).parent, args.target)
    except (UpdateError, OSError) as exc:
        print(f"Guncelleme durduruldu: {exc}", file=sys.stderr)
        return 1
    print(f"Guncelleme tamamlandi: {result['from_version']} -> {result['to_version']}")
    print(f"Dogrulanan kod yedegi: {result['backup']}")
    print("Mevcut kurulum klasorundeki BASLAT.cmd dosyasini acabilirsin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
