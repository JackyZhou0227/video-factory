from __future__ import annotations

import json
from dataclasses import dataclass
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


def _parse_stored_definition(row: Template) -> TemplateDefinition:
    if not isinstance(row.definition, dict):
        raise TemplateImportError("stored template definition must be a JSON object")
    return parse_template_json(json.dumps(row.definition, ensure_ascii=False))


class TemplateRegistry:
    """PostgreSQL-backed, shared template registry.

    Template definitions are database data only. The registry deliberately has
    no source-tree or local-file fallback.
    """

    def list_entries(self, user_id: str) -> list[TemplateRegistryEntry]:
        settings_store.init_db()
        with settings_store._orm_session() as session:
            rows = session.scalars(select(Template).order_by(Template.id.asc())).all()
            result = []
            for row in rows:
                try:
                    definition = _parse_stored_definition(row)
                    result.append(TemplateRegistryEntry(definition))
                except TemplateImportError as exc:
                    raise TemplateStorageError(str(exc)) from exc
        return sorted(result, key=lambda entry: entry.definition.id)

    def list_templates(self, user_id: str) -> list[TemplateDefinition]:
        return [entry.definition for entry in self.list_entries(user_id)]

    def get_entry(self, user_id: str, template_id: str) -> TemplateRegistryEntry:
        normalized_id = str(template_id or "").strip()
        if not normalized_id:
            raise TemplateNotFoundError("template ID cannot be empty")
        settings_store.init_db()
        with settings_store._orm_session() as session:
            row = session.get(Template, normalized_id)
            if row is None:
                raise TemplateNotFoundError(f"template not found: {normalized_id}")
            try:
                definition = _parse_stored_definition(row)
                return TemplateRegistryEntry(definition)
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
