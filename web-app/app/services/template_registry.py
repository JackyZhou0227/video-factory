from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.models.template_definition import TemplateDefinition

MAX_TEMPLATE_JSON_BYTES = 128 * 1024
BUILTIN_TEMPLATE_ORDER = ("zhongyi-xunfang", "doctor-intro")


class TemplateRegistryError(RuntimeError):
    """Base class for template registry failures."""


class TemplateNotFoundError(TemplateRegistryError):
    pass


class TemplateConflictError(TemplateRegistryError):
    pass


class TemplateImportError(TemplateRegistryError):
    pass


class TemplateStorageError(TemplateRegistryError):
    pass


@dataclass(frozen=True)
class TemplateRegistryEntry:
    definition: TemplateDefinition
    is_builtin: bool


def _web_app_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_builtin_root() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "builtin"


def _payload_bytes(payload: str | bytes | bytearray) -> bytes:
    if isinstance(payload, str):
        try:
            raw = payload.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise TemplateImportError("template JSON must be valid UTF-8 text") from exc
    elif isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    else:
        raise TemplateImportError("template JSON must be text or bytes")
    if not raw:
        raise TemplateImportError("template JSON cannot be empty")
    if len(raw) > MAX_TEMPLATE_JSON_BYTES:
        raise TemplateImportError(
            f"template JSON cannot exceed {MAX_TEMPLATE_JSON_BYTES} bytes"
        )
    return raw


def parse_template_json(payload: str | bytes | bytearray) -> TemplateDefinition:
    """Validate an untrusted JSON document and return its reusable definition."""

    raw = _payload_bytes(payload)
    try:
        definition = TemplateDefinition.model_validate_json(raw)
    except (ValidationError, ValueError, UnicodeError) as exc:
        raise TemplateImportError(f"invalid template JSON: {exc}") from exc
    canonical_size = len(export_template_json(definition).encode("utf-8"))
    if canonical_size > MAX_TEMPLATE_JSON_BYTES:
        raise TemplateImportError(
            f"exported template JSON cannot exceed {MAX_TEMPLATE_JSON_BYTES} bytes"
        )
    return definition


def export_template_json(template: TemplateDefinition) -> str:
    return template.model_dump_json(indent=2, exclude_none=True)


def _atomic_create(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            temporary_path.unlink(missing_ok=True)
            temporary_path = None
            raise TemplateConflictError(f"template ID already exists: {path.stem}") from exc
        temporary_path.unlink()
        temporary_path = None
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise TemplateStorageError(f"could not persist template {path.name}: {exc}") from exc


class TemplateRegistry:
    """Read-only built-ins plus JSON definitions isolated by application user ID."""

    def __init__(
        self,
        *,
        storage_root: Path | None = None,
        builtin_root: Path | None = None,
    ) -> None:
        self.storage_root = Path(storage_root) if storage_root is not None else _web_app_root() / "data" / "templates"
        self.builtin_root = Path(builtin_root) if builtin_root is not None else _default_builtin_root()
        self._write_lock = threading.RLock()

    @staticmethod
    def _normalized_user_id(user_id: str) -> str:
        if not isinstance(user_id, str) or not user_id.strip():
            raise TemplateStorageError("user_id cannot be empty")
        value = user_id.strip()
        if len(value.encode("utf-8")) > 512:
            raise TemplateStorageError("user_id is too long")
        return value

    def user_template_dir(self, user_id: str) -> Path:
        normalized = self._normalized_user_id(user_id)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self.storage_root / "users" / digest

    @staticmethod
    def _read_definition(path: Path, *, built_in: bool) -> TemplateDefinition:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise TemplateStorageError(f"could not read template {path.name}: {exc}") from exc
        try:
            return parse_template_json(raw)
        except TemplateImportError as exc:
            kind = "built-in" if built_in else "stored"
            raise TemplateStorageError(f"invalid {kind} template {path.name}: {exc}") from exc

    def _builtin_templates(self) -> dict[str, TemplateDefinition]:
        if not self.builtin_root.is_dir():
            raise TemplateStorageError(f"built-in template directory is missing: {self.builtin_root}")

        definitions: dict[str, TemplateDefinition] = {}
        for path in self.builtin_root.glob("*.json"):
            definition = self._read_definition(path, built_in=True)
            if path.stem != definition.id:
                raise TemplateStorageError(
                    f"built-in template filename does not match its ID: {path.name}"
                )
            if definition.id in definitions:
                raise TemplateStorageError(f"duplicate built-in template ID: {definition.id}")
            definitions[definition.id] = definition
        if not definitions:
            raise TemplateStorageError("no built-in templates are configured")
        return definitions

    def _user_templates(self, user_id: str) -> dict[str, TemplateDefinition]:
        directory = self.user_template_dir(user_id)
        if not directory.exists():
            return {}
        if not directory.is_dir():
            raise TemplateStorageError(f"template user path is not a directory: {directory}")

        definitions: dict[str, TemplateDefinition] = {}
        for path in directory.glob("*.json"):
            definition = self._read_definition(path, built_in=False)
            if path.stem != definition.id:
                raise TemplateStorageError(
                    f"stored template filename does not match its ID: {path.name}"
                )
            if definition.id in definitions:
                raise TemplateStorageError(f"duplicate stored template ID: {definition.id}")
            definitions[definition.id] = definition
        return definitions

    @staticmethod
    def _ordered_builtins(
        definitions: dict[str, TemplateDefinition],
    ) -> list[TemplateDefinition]:
        order = {template_id: index for index, template_id in enumerate(BUILTIN_TEMPLATE_ORDER)}
        return sorted(
            definitions.values(),
            key=lambda item: (order.get(item.id, len(order)), item.id),
        )

    def list_entries(self, user_id: str) -> list[TemplateRegistryEntry]:
        builtins = self._builtin_templates()
        users = self._user_templates(user_id)
        overlap = set(builtins) & set(users)
        if overlap:
            raise TemplateStorageError(
                f"stored templates conflict with built-ins: {', '.join(sorted(overlap))}"
            )
        entries = [
            TemplateRegistryEntry(definition=definition, is_builtin=True)
            for definition in self._ordered_builtins(builtins)
        ]
        entries.extend(
            TemplateRegistryEntry(definition=users[template_id], is_builtin=False)
            for template_id in sorted(users)
        )
        return entries

    def list_templates(self, user_id: str) -> list[TemplateDefinition]:
        return [entry.definition for entry in self.list_entries(user_id)]

    def get_entry(self, user_id: str, template_id: str) -> TemplateRegistryEntry:
        normalized_id = str(template_id or "").strip()
        if not normalized_id:
            raise TemplateNotFoundError("template ID cannot be empty")
        builtins = self._builtin_templates()
        if normalized_id in builtins:
            return TemplateRegistryEntry(definition=builtins[normalized_id], is_builtin=True)
        users = self._user_templates(user_id)
        if normalized_id in users:
            return TemplateRegistryEntry(definition=users[normalized_id], is_builtin=False)
        raise TemplateNotFoundError(f"template not found: {normalized_id}")

    def get_template(self, user_id: str, template_id: str) -> TemplateDefinition:
        return self.get_entry(user_id, template_id).definition

    def is_builtin(self, template_id: str) -> bool:
        return str(template_id or "").strip() in self._builtin_templates()

    def import_template_json(
        self,
        user_id: str,
        payload: str | bytes | bytearray,
    ) -> TemplateDefinition:
        definition = parse_template_json(payload)
        with self._write_lock:
            if definition.id in self._builtin_templates():
                raise TemplateConflictError(
                    f"built-in template cannot be overwritten: {definition.id}"
                )
            destination = self.user_template_dir(user_id) / f"{definition.id}.json"
            if destination.exists():
                raise TemplateConflictError(f"template ID already exists: {definition.id}")
            _atomic_create(destination, export_template_json(definition))
        return definition

    def export_template_json(self, user_id: str, template_id: str) -> str:
        return export_template_json(self.get_template(user_id, template_id))

    # Concise aliases make the service convenient outside HTTP handlers.
    list = list_templates
    get = get_template
    import_json = import_template_json
    export_json = export_template_json


template_registry = TemplateRegistry()


def list_templates(user_id: str) -> list[TemplateDefinition]:
    return template_registry.list_templates(user_id)


def get_template(user_id: str, template_id: str) -> TemplateDefinition:
    return template_registry.get_template(user_id, template_id)


def import_template_json(
    user_id: str,
    payload: str | bytes | bytearray,
) -> TemplateDefinition:
    return template_registry.import_template_json(user_id, payload)


def export_registered_template_json(user_id: str, template_id: str) -> str:
    return template_registry.export_template_json(user_id, template_id)


__all__ = [
    "BUILTIN_TEMPLATE_ORDER",
    "MAX_TEMPLATE_JSON_BYTES",
    "TemplateConflictError",
    "TemplateImportError",
    "TemplateNotFoundError",
    "TemplateRegistry",
    "TemplateRegistryEntry",
    "TemplateRegistryError",
    "TemplateStorageError",
    "export_registered_template_json",
    "export_template_json",
    "get_template",
    "import_template_json",
    "list_templates",
    "parse_template_json",
    "template_registry",
]
