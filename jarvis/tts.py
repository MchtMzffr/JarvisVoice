"""A pinned, CPU-only Turkish voice for the first local assistant.

EMA Lightning 1.1.2 exposes ``EMA(device="cpu").say(...)``. Its public
constructor has no model-directory or revision argument, so setup creates a
verified Hugging Face cache and binds its local ``main`` ref to one known
revision. Normal use is offline and never downloads replacement weights.

The three assets below are the complete download set used by that constructor.
EMA's loaders use ``torch.load(..., weights_only=True)``; we additionally verify
the known asset digests *before* constructing EMA. Code and weights are Apache
2.0. This small model has one Turkish voice, without cloning or emotion control;
its naturalness is limited. It is a practical first voice, not a promise of
human-level conversation or a measured latency on the user's Windows machine.

Primary sources, inspected 2026-11-23:
https://pypi.org/project/ema-lightning/1.1.2/
https://github.com/canberk7/ema-lightning/blob/main/src/ema_lightning/api.py
https://huggingface.co/canberkkkkkk/ema-lightning/tree/e7c96f2fc0ba843cd0f86e02786655bb56f50df8
https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables
https://huggingface.co/docs/huggingface_hub/en/guides/manage-cache

``cache_dir`` is the app's HF_HOME directory; Hub files live in its ``hub``
subdirectory. Run ``prepare_tts`` in the setup process, then start the assistant
in a fresh process. Hugging Face reads its environment settings on import.
This module never changes the user's persistent Windows environment settings.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Callable

import numpy as np


EMA_PACKAGE_VERSION = "1.1.2"
MODEL_REPO = "canberkkkkkk/ema-lightning"
MODEL_REVISION = "e7c96f2fc0ba843cd0f86e02786655bb56f50df8"
SAMPLE_RATE = 24_000
_CACHE_REPO = "models--canberkkkkkk--ema-lightning"
# filename: (byte count, SHA-256). Hashes identify the reviewed model bytes,
# independently of a remote branch name or the contents of a cached ref.
_ASSETS: dict[str, tuple[int, str]] = {
    "config.json": (
        342,
        "27546c470dd4e86d9ab8172fd1c85c45a4bffdf52d9ccb3f511c4b0c3ae38241",
    ),
    "ema.pt": (
        22_285_878,
        "95aec03dafbe0e1d69bca774ab597c779464729a14bc99bfcb52480090c7dfe6",
    ),
    "decoder.pt": (
        12_103_269,
        "9595819b173f411340f63d11332695121a97f8bf1f6d8b6fef0b21cf99c7ad67",
    ),
}

_LIFECYCLE_LOCK = threading.RLock()
_SYNTHESIS_LOCK = threading.Lock()
_MODEL: Any = None
_MODEL_CACHE: Path | None = None
_MODEL_THREADS: int | None = None


def _paths(cache_dir: Path) -> tuple[Path, Path, Path]:
    home = Path(cache_dir).expanduser().resolve()
    hub = home / "hub"
    snapshot = hub / _CACHE_REPO / "snapshots" / MODEL_REVISION
    return home, hub, snapshot


def _configure_environment(home: Path, hub: Path, *, offline: bool) -> None:
    # These settings affect this app process only. Set them before importing
    # huggingface_hub, torch, or ema_lightning.
    os.environ["HF_HOME"] = str(home)
    os.environ["HF_HUB_CACHE"] = str(hub)
    os.environ["HF_HUB_OFFLINE"] = "1" if offline else "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"


def _asset_is_valid(path: Path, size: int, sha256: str) -> bool:
    try:
        if not path.is_file() or path.stat().st_size != size:
            return False
        with path.open("rb") as asset:
            digest = hashlib.file_digest(asset, "sha256").hexdigest()
        return digest == sha256
    except OSError:
        return False


def _verify_assets(snapshot: Path) -> None:
    for filename, (size, sha256) in _ASSETS.items():
        if not _asset_is_valid(snapshot / filename, size, sha256):
            raise RuntimeError(
                f"EMA ses dosyası eksik veya doğrulanamadı: {filename}. "
                "Kurulum adımını yeniden çalıştırın."
            )


def _bind_main_ref(hub: Path) -> None:
    refs = hub / _CACHE_REPO / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="ascii", dir=refs, prefix="main-", delete=False
        ) as output:
            temporary = Path(output.name)
            # No newline: HF reads a ref's entire content as a commit ID.
            output.write(MODEL_REVISION)
        temporary.replace(refs / "main")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _verify_main_ref(hub: Path) -> None:
    try:
        revision = (hub / _CACHE_REPO / "refs" / "main").read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(
            "EMA çevrimdışı önbelleği hazır değil. Kurulum adımını yeniden çalıştırın."
        ) from error
    if revision != MODEL_REVISION:
        raise RuntimeError(
            "EMA önbelleği beklenen model sürümüne bağlı değil. "
            "Kurulum adımını yeniden çalıştırın."
        )


def prepare_tts(cache_dir: Path, progress: Callable[[str], None]) -> None:
    """Download and verify ~34.39 MB of pinned weights during explicit setup.

    No PyTorch import or synthesis is performed here. An already verified
    snapshot requires no network access; its local main ref can be repaired.
    In normal use instantiate Speaker in a fresh, offline app process.
    """
    with _LIFECYCLE_LOCK:
        home, hub, snapshot = _paths(cache_dir)
        complete = all(
            _asset_is_valid(snapshot / name, size, digest)
            for name, (size, digest) in _ASSETS.items()
        )
        if complete:
            _bind_main_ref(hub)
            progress("Türkçe ses modeli hazır; dosyalar doğrulandı.")
            return
        if _MODEL is not None:
            raise RuntimeError(
                "Ses modeli kullanımdayken kurulum yapılamaz. "
                "Uygulamayı kapatıp kurulum adımını çalıştırın."
            )

        home.mkdir(parents=True, exist_ok=True)
        hub.mkdir(parents=True, exist_ok=True)
        _configure_environment(home, hub, offline=False)
        from huggingface_hub import constants, hf_hub_download

        if constants.HF_HUB_OFFLINE:
            raise RuntimeError(
                "Bu süreç daha önce çevrimdışı başlatılmış. "
                "Model indirmek için kurulum adımını ayrı bir süreçte çalıştırın."
            )

        progress("Türkçe ses modeli hazırlanıyor (yaklaşık 34,4 MB).")
        for filename, (size, sha256) in _ASSETS.items():
            target = snapshot / filename
            if _asset_is_valid(target, size, sha256):
                continue
            progress(f"Ses modeli indiriliyor: {filename}")
            hf_hub_download(
                repo_id=MODEL_REPO,
                filename=filename,
                revision=MODEL_REVISION,
                cache_dir=str(hub),
                local_files_only=False,
                force_download=True,
                token=False,
            )
            if not _asset_is_valid(target, size, sha256):
                raise RuntimeError(
                    f"İndirilen ses dosyasının doğrulaması başarısız: {filename}. "
                    "Dosya yüklenmedi; kurulum adımını yeniden çalıştırın."
                )
        _verify_assets(snapshot)
        _bind_main_ref(hub)
        _verify_main_ref(hub)
        progress("Türkçe ses modeli hazır; dosyalar doğrulandı.")


class Speaker:
    """One persistent CPU model per app process; synthesis is serialized.

    All instances must use the same cache and CPU thread setting. Initialization
    verifies the offline cache and loads the shared model. Raw text and speech
    are never logged or sent to a service. Callers control text segment length.
    """

    def __init__(self, cache_dir: Path, cpu_threads: int = 4):
        global _MODEL, _MODEL_CACHE, _MODEL_THREADS
        if isinstance(cpu_threads, bool) or not isinstance(cpu_threads, int) or cpu_threads < 1:
            raise ValueError("cpu_threads pozitif bir tam sayı olmalı.")
        home, hub, snapshot = _paths(cache_dir)
        with _LIFECYCLE_LOCK:
            if _MODEL is not None:
                if home != _MODEL_CACHE or cpu_threads != _MODEL_THREADS:
                    raise RuntimeError(
                        "Ses modeli zaten farklı ayarlarla açık. "
                        "Yeni ayarları kullanmak için uygulamayı yeniden başlatın."
                    )
                self._model = _MODEL
                return

            _configure_environment(home, hub, offline=True)
            _verify_assets(snapshot)
            _verify_main_ref(hub)
            # Imports remain inside initialization so module import cannot
            # allocate a model or initialize a different Hub environment.
            from huggingface_hub import constants

            if not constants.HF_HUB_OFFLINE or Path(constants.HF_HUB_CACHE).resolve() != hub:
                raise RuntimeError(
                    "Model kütüphanesi bu süreçte farklı ağ/önbellek ayarlarıyla açılmış. "
                    "Kurulumu kapatıp asistanı yeni bir süreçte başlatın."
                )
            if importlib.metadata.version("ema-lightning") != EMA_PACKAGE_VERSION:
                raise RuntimeError(
                    "EMA Lightning 1.1.2 gerekli. Kurulum adımını yeniden çalıştırın."
                )

            import torch
            from ema_lightning import EMA

            torch.set_num_threads(cpu_threads)
            model = EMA(device="cpu")  # Never auto-select the GPU used by Ollama.
            _MODEL = model
            _MODEL_CACHE = home
            _MODEL_THREADS = cpu_threads
            self._model = model

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Return contiguous mono float32 audio at 24 kHz, without playback."""
        if not isinstance(text, str):
            raise TypeError("Seslendirilecek metin str olmalı.")
        if not text.strip():
            return np.empty(0, dtype=np.float32), SAMPLE_RATE
        with _SYNTHESIS_LOCK:
            speech = self._model.say(text, sample_rate=SAMPLE_RATE)
            audio = np.asarray(speech.audio, dtype=np.float32)
            if speech.sample_rate != SAMPLE_RATE or audio.ndim != 1:
                raise RuntimeError("Ses modeli beklenmeyen bir ses biçimi üretti.")
            if not np.isfinite(audio).all():
                raise RuntimeError("Ses modeli geçersiz ses örnekleri üretti.")
            if audio.size and np.max(np.abs(audio)) > 1.0001:
                raise RuntimeError("Ses modeli izin verilen ses aralığını aştı.")
            return np.array(audio, dtype=np.float32, order="C", copy=True), SAMPLE_RATE
