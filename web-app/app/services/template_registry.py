from __future__ import annotations

import json
import hashlib
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pydantic import ValidationError

from app.schemas.template_definition import TemplateDefinition
from app.db.models import Template, User
from app.services import settings_store

MAX_TEMPLATE_JSON_BYTES = 128 * 1024


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
    is_builtin: bool = False


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


def _default_builtin_root() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "builtin"


def _atomic_create(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.write("\n")
    except FileExistsError as exc:
        raise TemplateConflictError(f"template ID already exists: {path.stem}") from exc
    except OSError as exc:
        raise TemplateStorageError(f"could not persist template {path.name}: {exc}") from exc


class TemplateRegistry:
    """PostgreSQL-backed, shared template registry."""

    def __init__(
        self,
        *,
        storage_root=None,
        builtin_root=None,
    ) -> None:
        self.storage_root = Path(storage_root) if storage_root is not None else None
        self.builtin_root = Path(builtin_root) if builtin_root is not None else _default_builtin_root()
        self._write_lock = threading.RLock()

    @property
    def _legacy_file_mode(self) -> bool:
        return self.storage_root is not None

    def user_template_dir(self, user_id: str) -> Path:
        if self.storage_root is None:
            raise TemplateStorageError("file storage is disabled for the default registry")
        normalized = str(user_id or "").strip()
        if not normalized:
            raise TemplateStorageError("user_id cannot be empty")
        return self.storage_root / "users" / hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _legacy_read(self, path: Path, built_in: bool) -> TemplateDefinition:
        try:
            return parse_template_json(path.read_bytes())
        except (OSError, TemplateImportError) as exc:
            raise TemplateStorageError(f"invalid {'built-in' if built_in else 'stored'} template {path.name}: {exc}") from exc

    def _legacy_builtins(self) -> dict[str, TemplateDefinition]:
        definitions = {}
        for path in self.builtin_root.glob("*.json"):
            definition = self._legacy_read(path, True)
            definitions[definition.id] = definition
        return definitions

    def _legacy_users(self, user_id: str) -> dict[str, TemplateDefinition]:
        directory = self.user_template_dir(user_id)
        if not directory.exists():
            return {}
        definitions = {}
        for path in directory.glob("*.json"):
            definition = self._legacy_read(path, False)
            definitions[definition.id] = definition
        return definitions

    def list_entries(self, user_id: str) -> list[TemplateRegistryEntry]:
        if self._legacy_file_mode:
            builtins = self._legacy_builtins()
            users = self._legacy_users(user_id)
            builtin_items = sorted(builtins.values(), key=lambda item: (0 if item.id == "zhongyi-xunfang" else 1, item.id))
            return [TemplateRegistryEntry(item, True) for item in builtin_items] + [TemplateRegistryEntry(item, False) for item in users.values()]
        settings_store.init_db()
        with settings_store._orm_session() as session:
            rows = session.scalars(select(Template).order_by(Template.id.asc())).all()
        result = []
        for row in rows:
            try:
                result.append(TemplateRegistryEntry(parse_template_json(json.dumps(row.definition, ensure_ascii=False))))
            except TemplateImportError as exc:
                raise TemplateStorageError(str(exc)) from exc
        return sorted(result, key=lambda entry: (0 if entry.definition.id == "zhongyi-xunfang" else 1, entry.definition.id))

    def list_templates(self, user_id: str) -> list[TemplateDefinition]:
        return [entry.definition for entry in self.list_entries(user_id)]

    def get_entry(self, user_id: str, template_id: str) -> TemplateRegistryEntry:
        normalized_id = str(template_id or "").strip()
        if not normalized_id:
            raise TemplateNotFoundError("template ID cannot be empty")
        if self._legacy_file_mode:
            builtins = self._legacy_builtins()
            if normalized_id in builtins:
                return TemplateRegistryEntry(builtins[normalized_id], True)
            users = self._legacy_users(user_id)
            if normalized_id in users:
                return TemplateRegistryEntry(users[normalized_id], False)
            raise TemplateNotFoundError(f"template not found: {normalized_id}")
        settings_store.init_db()
        with settings_store._orm_session() as session:
            row = session.get(Template, normalized_id)
        if row is None:
            raise TemplateNotFoundError(f"template not found: {normalized_id}")
        try:
            return TemplateRegistryEntry(parse_template_json(json.dumps(row.definition, ensure_ascii=False)))
        except TemplateImportError as exc:
            raise TemplateStorageError(str(exc)) from exc

    def get_template(self, user_id: str, template_id: str) -> TemplateDefinition:
        return self.get_entry(user_id, template_id).definition

    def import_template_json(
        self,
        user_id: str,
        payload: str | bytes | bytearray,
    ) -> TemplateDefinition:
        definition = parse_template_json(payload)
        if self._legacy_file_mode:
            with self._write_lock:
                if definition.id in self._legacy_builtins() or definition.id in self._legacy_users(user_id):
                    raise TemplateConflictError(f"template ID already exists: {definition.id}")
                _atomic_create(self.user_template_dir(user_id) / f"{definition.id}.json", export_template_json(definition))
            return definition
        settings_store.init_db()
        try:
            with settings_store._orm_session() as session:
                creator = session.get(User, user_id)
                session.add(Template(
                    id=definition.id,
                    definition=definition.model_dump(mode="json", exclude_none=True),
                    created_by=user_id if creator is not None else None,
                    created_at=settings_store._now_iso(),
                    updated_at=settings_store._now_iso(),
                ))
                session.flush()
        except IntegrityError as exc:
            raise TemplateConflictError(f"template ID already exists: {definition.id}") from exc
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
