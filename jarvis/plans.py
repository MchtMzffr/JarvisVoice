"""Bounded plan data and explicit local persistence; plans never execute steps."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata
import uuid

from .config import SETTINGS


PLAN_SCHEMA_VERSION = 1


class PlanError(ValueError):
    """A bounded user-facing error that excludes private paths and contents."""


def _text(value, maximum):
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > maximum
            or any(unicodedata.category(character).startswith("C") for character in value)):
        raise PlanError("Plan metni boş, çok uzun veya geçersiz karakter içeriyor.")
    return value


def _exact_keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise PlanError("Plan biçimi geçersiz; mevcut plan korunuyor.")


@dataclass(frozen=True)
class PlanStep:
    text: str
    minutes: int | None = None

    def __post_init__(self):
        _text(self.text, SETTINGS.plan_step_max_chars)
        if (self.minutes is not None
                and (type(self.minutes) is not int or not 1 <= self.minutes <= SETTINGS.plan_max_minutes)):
            raise PlanError("Plan adımının tahmini süresi geçersiz.")

    def to_dict(self):
        return {"text": self.text, "minutes": self.minutes}

    @classmethod
    def from_dict(cls, value):
        _exact_keys(value, {"text", "minutes"})
        return cls(text=value["text"], minutes=value["minutes"])


@dataclass(frozen=True)
class PlanDraft:
    title: str
    steps: tuple[PlanStep, ...]
    assumptions: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = PLAN_SCHEMA_VERSION

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != PLAN_SCHEMA_VERSION:
            raise PlanError("Plan sürümü bu uygulamayla uyumlu değil; mevcut plan korunuyor.")
        _text(self.title, SETTINGS.plan_title_max_chars)
        if (type(self.steps) is not tuple or not 1 <= len(self.steps) <= SETTINGS.plan_max_steps
                or any(not isinstance(step, PlanStep) for step in self.steps)):
            raise PlanError("Plan adımları geçersiz veya izin verilen sınırın dışında.")
        if type(self.assumptions) is not tuple or len(self.assumptions) > SETTINGS.plan_max_assumptions:
            raise PlanError("Plan varsayımları geçersiz veya çok uzun.")
        for assumption in self.assumptions:
            _text(assumption, SETTINGS.plan_assumption_max_chars)
        if not isinstance(self.id, str) or re.fullmatch(r"[0-9a-f]{32}", self.id) is None:
            raise PlanError("Plan kimliği geçersiz; mevcut plan korunuyor.")
        if not isinstance(self.created_at, str) or len(self.created_at) > 40:
            raise PlanError("Plan tarihi geçersiz; mevcut plan korunuyor.")
        try:
            created = datetime.fromisoformat(self.created_at)
        except ValueError:
            raise PlanError("Plan tarihi geçersiz; mevcut plan korunuyor.") from None
        if created.tzinfo is None or created.utcoffset() != timezone.utc.utcoffset(created):
            raise PlanError("Plan tarihi UTC olmalı; mevcut plan korunuyor.")

    def to_dict(self):
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "title": self.title,
            "steps": [step.to_dict() for step in self.steps],
            "assumptions": list(self.assumptions),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value):
        _exact_keys(value, {"schema_version", "id", "title", "steps", "assumptions", "created_at"})
        if type(value["steps"]) is not list or type(value["assumptions"]) is not list:
            raise PlanError("Plan listeleri geçersiz; mevcut plan korunuyor.")
        # Check collection sizes before constructing their members.
        if not 1 <= len(value["steps"]) <= SETTINGS.plan_max_steps or len(value["assumptions"]) > SETTINGS.plan_max_assumptions:
            raise PlanError("Plan listeleri izin verilen sınırın dışında.")
        return cls(
            schema_version=value["schema_version"], id=value["id"], title=value["title"],
            steps=tuple(PlanStep.from_dict(step) for step in value["steps"]),
            assumptions=tuple(value["assumptions"]), created_at=value["created_at"],
        )

    def spoken(self):
        sentences = [self.title + "."]
        for index, step in enumerate(self.steps, 1):
            duration = f" Tahmini {step.minutes} dakika." if step.minutes is not None else ""
            sentences.append(f"{index}. adım: {step.text.rstrip('.!?')}." + duration)
        if self.assumptions:
            sentences.append("Varsayımlar: " + "; ".join(self.assumptions) + ".")
        return " ".join(sentences)


def draft_from_model(value):
    """Accept plan content only; identity, schema and date are server-owned."""
    _exact_keys(value, {"title", "steps", "assumptions"})
    if type(value["steps"]) is not list or type(value["assumptions"]) is not list:
        raise PlanError("Model geçerli bir plan listesi oluşturamadı.")
    if not 1 <= len(value["steps"]) <= SETTINGS.plan_max_steps or len(value["assumptions"]) > SETTINGS.plan_max_assumptions:
        raise PlanError("Modelin planı izin verilen sınırın dışında.")
    return PlanDraft(
        title=value["title"], steps=tuple(PlanStep.from_dict(step) for step in value["steps"]),
        assumptions=tuple(value["assumptions"]),
    )


def plan_json_schema():
    """Ollama structured output schema; Settings remains the limits' source."""
    return {
        "type": "object", "additionalProperties": False,
        "required": ["title", "steps", "assumptions"],
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": SETTINGS.plan_title_max_chars},
            "steps": {
                "type": "array", "minItems": 1, "maxItems": SETTINGS.plan_max_steps,
                "items": {
                    "type": "object", "additionalProperties": False, "required": ["text", "minutes"],
                    "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": SETTINGS.plan_step_max_chars},
                        "minutes": {"type": ["integer", "null"], "minimum": 1, "maximum": SETTINGS.plan_max_minutes},
                    },
                },
            },
            "assumptions": {
                "type": "array", "maxItems": SETTINGS.plan_max_assumptions,
                "items": {"type": "string", "minLength": 1, "maxLength": SETTINGS.plan_assumption_max_chars},
            },
        },
    }


def _fold_command(text):
    text = unicodedata.normalize("NFKD", text).casefold()
    text = "".join(character for character in text if unicodedata.category(character) != "Mn")
    return " ".join(text.replace("ı", "i").split())


def plan_command(text):
    """Whole direct utterances only; preserves a creation goal's original text.

    The caller must supply direct user input, never model/web content. Parsing a
    request does not itself write a file or authorize execution of any step.
    """
    if (not isinstance(text, str) or len(text) > SETTINGS.max_text_chars
            or any(unicodedata.category(character).startswith("C") for character in text)):
        return None
    original = unicodedata.normalize("NFC", text).strip().rstrip(".!? ")
    if not original or original[0] in "\"'‘’“”`" or "`" in original:
        return None
    simple = _fold_command(original)
    fixed = {
        "plani kaydet": "save", "bu plani kaydet": "save", "planimi kaydet": "save",
        "planimi goster": "show", "planimi oku": "show", "plani goster": "show", "plani oku": "show",
        "kayitli planimi sil": "delete", "kayitli plani sil": "delete",
        "plan taslagini iptal et": "discard", "plan taslagini sil": "discard",
    }
    if simple in fixed:
        return fixed[simple], ""
    # Match the original string so Turkish characters in the goal are retained.
    verb = r"(?:olu[şs]tur|haz[ıi]rla|yap)"
    patterns = (
        rf"(?:bana\s+)?(?:bir\s+)?plan\s+{verb}(?:\s*:\s*(?P<goal>.+))?",
        rf"(?:bana\s+)?(?P<goal>.+?)\s+i[çc]in\s+(?:bir\s+)?plan\s+{verb}",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, original, flags=re.IGNORECASE)
        if match:
            goal = (match.groupdict().get("goal") or "").strip()
            return "create", goal
    return None


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise PlanError("Plan dosyasında yinelenen alan var; mevcut plan korunuyor.")
        value[key] = item
    return value


def _reject_constant(value):
    raise PlanError("Plan dosyasında geçersiz sayı var; mevcut plan korunuyor.")


class PlanStore:
    """One atomic, bounded JSON file; corrupt/future/link targets are preserved.

    No directory or file is created by load(). The caller is responsible for an
    explicit save/delete request and for serializing those operations. Link and
    identity checks reject observed replacement; this is not an OS sandbox
    against another process running under the same user account.
    """
    def __init__(self, path):
        self.path = Path(os.path.abspath(path))

    def _check_path(self):
        result = None
        for candidate in (self.path, *self.path.parents):
            try:
                value = candidate.lstat()
            except FileNotFoundError:
                continue
            if (stat.S_ISLNK(value.st_mode)
                    or getattr(value, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
                raise PlanError("Plan yolu bağlantı içeriyor; mevcut dosyalar korunuyor.")
            if candidate == self.path:
                if not stat.S_ISREG(value.st_mode):
                    raise PlanError("Plan yolu normal bir dosya değil; mevcut dosyalar korunuyor.")
                result = value
            elif not stat.S_ISDIR(value.st_mode):
                raise PlanError("Plan klasörü geçersiz; mevcut dosyalar korunuyor.")
        return result

    def _read(self):
        try:
            before = self._check_path()
            if before is None:
                return None, None
            if before.st_size > SETTINGS.plan_file_max_bytes:
                raise PlanError("Plan dosyası beklenenden büyük; mevcut plan korunuyor.")
            flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
                     | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(os.open(self.path, flags), "rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
                    raise PlanError("Plan dosyası işlem sırasında değişti; yeniden dene.")
                raw = stream.read(SETTINGS.plan_file_max_bytes + 1)
            if len(raw) > SETTINGS.plan_file_max_bytes:
                raise PlanError("Plan dosyası beklenenden büyük; mevcut plan korunuyor.")
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            return PlanDraft.from_dict(value), _identity(opened)
        except PlanError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            raise PlanError("Plan dosyası okunamadı; mevcut plan korunuyor.") from None

    def load(self):
        return self._read()[0]

    def _require_unchanged(self, expected):
        current = self._check_path()
        identity = _identity(current) if current is not None else None
        if identity != expected:
            raise PlanError("Plan dosyası işlem sırasında değişti; mevcut dosya korunuyor.")

    def save(self, draft):
        if not isinstance(draft, PlanDraft):
            raise PlanError("Kaydedilecek plan geçersiz.")
        validated = PlanDraft.from_dict(draft.to_dict())
        payload = (json.dumps(validated.to_dict(), ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
        if len(payload) > SETTINGS.plan_file_max_bytes:
            raise PlanError("Kaydedilecek plan dosyası çok büyük.")
        _, expected = self._read()
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._require_unchanged(expected)
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".plan-", suffix=".tmp", dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._require_unchanged(expected)
            os.replace(temporary, self.path)
            temporary = None
        except PlanError:
            raise
        except OSError:
            raise PlanError("Plan kaydedilemedi; önceki plan korunuyor.") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def delete(self):
        _, expected = self._read()
        if expected is None:
            return
        try:
            self._require_unchanged(expected)
            self.path.unlink()
        except PlanError:
            raise
        except OSError:
            raise PlanError("Plan silinemedi; kayıtlı plan korunuyor.") from None
