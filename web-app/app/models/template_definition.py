from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Callable, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FieldType: TypeAlias = Literal["text", "textarea", "select"]
MediaType: TypeAlias = Literal["image", "video"]
ResponseFormat: TypeAlias = Literal["plain_scripts_v1", "segmented_scripts_v1"]

MAX_CONTENT_FIELDS = 50
MAX_MATERIAL_REQUIREMENTS = 20
MAX_TOTAL_MATERIAL_COUNT = 20
MAX_SELECT_OPTIONS = 100
MAX_CONTENT_VALUE_LENGTH = 10_000
SUPPORTED_VIDEO_RATIOS = frozenset({"9:16", "16:9", "1:1", "3:4"})

PROMPT_PLACEHOLDERS = frozenset(
    {"candidate_count", "content_context", "material_context", "response_contract"}
)
REWRITE_PROMPT_PLACEHOLDERS = PROMPT_PLACEHOLDERS | {"original_script"}

_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$"
_PIPELINE_ID_PATTERN = r"^[a-z][a-z0-9_]*$"
_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
_ANY_PLACEHOLDER_PATTERN = re.compile(r"\{\{.*?\}\}", flags=re.DOTALL)


class StrictTemplateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SelectOption(StrictTemplateModel):
    value: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)


class ContentField(StrictTemplateModel):
    key: str = Field(min_length=1, max_length=64, pattern=_IDENTIFIER_PATTERN)
    label: str = Field(min_length=1, max_length=100)
    input_type: FieldType = "text"
    required: bool = True
    placeholder: str | None = Field(default=None, max_length=500)
    help_text: str | None = Field(default=None, max_length=1_000)
    default: str | None = Field(default=None, max_length=MAX_CONTENT_VALUE_LENGTH)
    options: list[SelectOption] = Field(default_factory=list, max_length=MAX_SELECT_OPTIONS)
    min_length: int | None = Field(default=None, ge=0, le=MAX_CONTENT_VALUE_LENGTH)
    max_length: int | None = Field(default=None, ge=1, le=MAX_CONTENT_VALUE_LENGTH)

    @model_validator(mode="after")
    def validate_field_configuration(self) -> ContentField:
        if self.min_length is not None and self.max_length is not None and self.min_length > self.max_length:
            raise ValueError("min_length cannot exceed max_length")

        if self.input_type == "select":
            if not self.options:
                raise ValueError("select fields require at least one option")
            option_values = [option.value for option in self.options]
            if len(option_values) != len(set(option_values)):
                raise ValueError("select option values must be unique")
            if self.min_length is not None and any(
                len(value) < self.min_length for value in option_values
            ):
                raise ValueError("select option values cannot be shorter than min_length")
            if self.max_length is not None and any(
                len(value) > self.max_length for value in option_values
            ):
                raise ValueError("select option values cannot be longer than max_length")
            if self.default is not None and self.default not in option_values:
                raise ValueError("select field default must match an option value")
        elif self.options:
            raise ValueError("options are only supported for select fields")

        if self.default is not None:
            if self.required and not self.default:
                raise ValueError("required field default cannot be empty")
            if self.min_length is not None and len(self.default) < self.min_length:
                raise ValueError("default is shorter than min_length")
            if self.max_length is not None and len(self.default) > self.max_length:
                raise ValueError("default is longer than max_length")
        return self


class MaterialRequirement(StrictTemplateModel):
    key: str = Field(min_length=1, max_length=64, pattern=_IDENTIFIER_PATTERN)
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1_000)
    media_type: MediaType
    min_count: int = Field(ge=0, le=MAX_TOTAL_MATERIAL_COUNT)
    max_count: int = Field(ge=1, le=MAX_TOTAL_MATERIAL_COUNT)

    @model_validator(mode="after")
    def validate_count_range(self) -> MaterialRequirement:
        if self.min_count > self.max_count:
            raise ValueError("min_count cannot exceed max_count")
        return self


def _validate_prompt_placeholders(value: str, allowed: frozenset[str], field_name: str) -> str:
    if "{%" in value or "%}" in value or "{#" in value or "#}" in value:
        raise ValueError(f"{field_name} does not support template statements or comments")

    unknown: set[str] = set()
    malformed: list[str] = []
    for match in _ANY_PLACEHOLDER_PATTERN.finditer(value):
        placeholder = match.group(0)
        strict_match = _PLACEHOLDER_PATTERN.fullmatch(placeholder)
        if strict_match is None:
            malformed.append(placeholder)
            continue
        name = strict_match.group(1)
        if name not in allowed:
            unknown.add(name)

    remainder = _ANY_PLACEHOLDER_PATTERN.sub("", value)
    if "{{" in remainder or "}}" in remainder:
        malformed.append("unmatched placeholder delimiter")
    if malformed:
        raise ValueError(f"{field_name} contains malformed placeholders")
    if unknown:
        raise ValueError(f"{field_name} contains unknown placeholders: {', '.join(sorted(unknown))}")
    return value


class ScriptGeneration(StrictTemplateModel):
    system_prompt: str = Field(min_length=1, max_length=20_000)
    prompt_template: str = Field(min_length=1, max_length=80_000)
    rewrite_prompt_template: str | None = Field(default=None, max_length=80_000)
    response_format: ResponseFormat
    default_candidate_count: int = Field(default=3, ge=1, le=10)
    temperature: float = Field(default=0.75, ge=0, le=2)
    max_tokens: int = Field(default=2400, ge=1, le=32_768)

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, value: str) -> str:
        return _validate_prompt_placeholders(value, frozenset(), "system_prompt")

    @field_validator("prompt_template")
    @classmethod
    def validate_prompt_template(cls, value: str) -> str:
        return _validate_prompt_placeholders(value, PROMPT_PLACEHOLDERS, "prompt_template")

    @field_validator("rewrite_prompt_template")
    @classmethod
    def validate_rewrite_prompt_template(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _validate_prompt_placeholders(value, REWRITE_PROMPT_PLACEHOLDERS, "rewrite_prompt_template")
        if "original_script" not in {
            match.group(1) for match in _PLACEHOLDER_PATTERN.finditer(value)
        }:
            raise ValueError("rewrite_prompt_template must contain {{original_script}}")
        return value


class ProductionBinding(StrictTemplateModel):
    pipeline_id: str = Field(min_length=1, max_length=64, pattern=_PIPELINE_ID_PATTERN)
    default_ratio: str = "9:16"
    default_batch_size: int = Field(default=5, ge=1, le=50)
    max_batch_size: int = Field(default=50, ge=1, le=50)

    @field_validator("default_ratio")
    @classmethod
    def validate_default_ratio(cls, value: str) -> str:
        if value not in SUPPORTED_VIDEO_RATIOS:
            raise ValueError(f"unsupported video ratio: {value}")
        return value

    @model_validator(mode="after")
    def validate_batch_range(self) -> ProductionBinding:
        if self.default_batch_size > self.max_batch_size:
            raise ValueError("default_batch_size cannot exceed max_batch_size")
        return self


class MaterialManifestItem(StrictTemplateModel):
    requirement_id: str = Field(min_length=1, max_length=64, pattern=_IDENTIFIER_PATTERN)
    file_index: int = Field(ge=0, le=MAX_TOTAL_MATERIAL_COUNT - 1)
    media_type: MediaType
    name: str | None = Field(default=None, max_length=255)


ContentValues: TypeAlias = dict[str, str]
MaterialManifest: TypeAlias = list[MaterialManifestItem]


PipelineCompatibilityValidator: TypeAlias = Callable[["TemplateDefinition"], None]
_PIPELINE_COMPATIBILITY_VALIDATORS: dict[str, PipelineCompatibilityValidator] = {}


class TemplateDefinition(StrictTemplateModel):
    schema_version: Literal[1] = 1
    template_version: int = Field(default=1, ge=1)
    id: str = Field(min_length=1, max_length=64, pattern=_IDENTIFIER_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1_000)
    content_fields: list[ContentField] = Field(default_factory=list, max_length=MAX_CONTENT_FIELDS)
    material_requirements: list[MaterialRequirement] = Field(
        min_length=1,
        max_length=MAX_MATERIAL_REQUIREMENTS,
    )
    script_generation: ScriptGeneration
    production: ProductionBinding

    @model_validator(mode="after")
    def validate_definition(self) -> TemplateDefinition:
        content_keys = [field.key for field in self.content_fields]
        if len(content_keys) != len(set(content_keys)):
            raise ValueError("content field keys must be unique")

        material_keys = [requirement.key for requirement in self.material_requirements]
        if len(material_keys) != len(set(material_keys)):
            raise ValueError("material requirement keys must be unique")

        total_material_capacity = sum(requirement.max_count for requirement in self.material_requirements)
        if total_material_capacity > MAX_TOTAL_MATERIAL_COUNT:
            raise ValueError(
                f"total material max_count cannot exceed {MAX_TOTAL_MATERIAL_COUNT}"
            )

        validate_pipeline_compatibility(self)
        return self

    @property
    def material_rules(self) -> dict[str, tuple[MediaType, int, int]]:
        return material_rules(self)


def _validate_generic_concat(template: TemplateDefinition) -> None:
    if not template.material_requirements:
        raise ValueError("generic_concat_v1 requires at least one material requirement")
    if not any(requirement.min_count > 0 for requirement in template.material_requirements):
        raise ValueError("generic_concat_v1 requires at least one required material slot")


def _validate_zhongyi_visit(template: TemplateDefinition) -> None:
    requirements = {requirement.key: requirement for requirement in template.material_requirements}
    for key in ("doctor-scene", "clinic-scene"):
        requirement = requirements.get(key)
        if requirement is None:
            raise ValueError(f"zhongyi_visit_v1 requires the {key} material requirement")
        if requirement.media_type != "video" or requirement.min_count < 1:
            raise ValueError(f"zhongyi_visit_v1 requires {key} to be a required video slot")
    if template.script_generation.response_format != "segmented_scripts_v1":
        raise ValueError("zhongyi_visit_v1 requires segmented_scripts_v1 responses")


_PIPELINE_COMPATIBILITY_VALIDATORS.update(
    {
        "generic_concat_v1": _validate_generic_concat,
        "zhongyi_visit_v1": _validate_zhongyi_visit,
    }
)


def register_pipeline_validator(
    pipeline_id: str,
    validator: PipelineCompatibilityValidator,
    *,
    replace: bool = False,
) -> None:
    """Register a trusted server-side pipeline implementation and compatibility hook."""

    if not re.fullmatch(_PIPELINE_ID_PATTERN, pipeline_id):
        raise ValueError("pipeline_id has an invalid format")
    if pipeline_id in _PIPELINE_COMPATIBILITY_VALIDATORS and not replace:
        raise ValueError(f"pipeline validator already registered: {pipeline_id}")
    _PIPELINE_COMPATIBILITY_VALIDATORS[pipeline_id] = validator


def validate_pipeline_compatibility(template: TemplateDefinition) -> None:
    validator = _PIPELINE_COMPATIBILITY_VALIDATORS.get(template.production.pipeline_id)
    if validator is None:
        raise ValueError(f"unknown production pipeline: {template.production.pipeline_id}")
    validator(template)


class TemplateRuntimeValidationError(ValueError):
    """Raised when task data does not satisfy a validated template definition."""


def validate_content_values(
    template: TemplateDefinition,
    values: Mapping[str, str],
) -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise TemplateRuntimeValidationError("content_values must be an object")
    if any(not isinstance(key, str) for key in values):
        raise TemplateRuntimeValidationError("content field keys must be strings")

    fields_by_key = {field.key: field for field in template.content_fields}
    unknown = sorted(set(values) - set(fields_by_key))
    if unknown:
        raise TemplateRuntimeValidationError(f"unknown content fields: {', '.join(unknown)}")

    normalized: dict[str, str] = {}
    for field in template.content_fields:
        raw_value = values.get(field.key, field.default if field.default is not None else "")
        if not isinstance(raw_value, str):
            raise TemplateRuntimeValidationError(f"content field {field.key} must be a string")
        value = raw_value.strip()
        if field.required and not value:
            raise TemplateRuntimeValidationError(f"content field {field.key} is required")
        if value and field.min_length is not None and len(value) < field.min_length:
            raise TemplateRuntimeValidationError(
                f"content field {field.key} must contain at least {field.min_length} characters"
            )
        if field.max_length is not None and len(value) > field.max_length:
            raise TemplateRuntimeValidationError(
                f"content field {field.key} cannot exceed {field.max_length} characters"
            )
        if field.input_type == "select" and value:
            allowed_values = {option.value for option in field.options}
            if value not in allowed_values:
                raise TemplateRuntimeValidationError(f"content field {field.key} has an invalid option")
        normalized[field.key] = value
    return normalized


def normalize_material_context(
    template: TemplateDefinition,
    context: Mapping[str, int] | None,
) -> dict[str, int]:
    if context is None:
        source: Mapping[str, int] = {}
    elif not isinstance(context, Mapping):
        raise TemplateRuntimeValidationError("material_context must be an object")
    else:
        source = context
    if any(not isinstance(key, str) for key in source):
        raise TemplateRuntimeValidationError("material context keys must be strings")
    requirements = {requirement.key: requirement for requirement in template.material_requirements}
    unknown = sorted(set(source) - set(requirements))
    if unknown:
        raise TemplateRuntimeValidationError(f"unknown material requirements: {', '.join(unknown)}")

    normalized: dict[str, int] = {}
    for key, raw_count in source.items():
        if isinstance(raw_count, bool) or not isinstance(raw_count, int):
            raise TemplateRuntimeValidationError(f"material count for {key} must be an integer")
        count = raw_count
        if count < 0 or count > requirements[key].max_count:
            raise TemplateRuntimeValidationError(
                f"material count for {key} must be between 0 and {requirements[key].max_count}"
            )
        normalized[key] = count
    return normalized


def validate_material_manifest(
    template: TemplateDefinition,
    manifest: Sequence[MaterialManifestItem | Mapping[str, object]],
    file_count: int,
) -> list[MaterialManifestItem]:
    if isinstance(manifest, (str, bytes)) or not isinstance(manifest, Sequence):
        raise TemplateRuntimeValidationError("material_manifest must be an array")
    if isinstance(file_count, bool) or not isinstance(file_count, int):
        raise TemplateRuntimeValidationError("file_count must be an integer")
    if file_count < 0 or file_count > MAX_TOTAL_MATERIAL_COUNT:
        raise TemplateRuntimeValidationError(
            f"file_count must be between 0 and {MAX_TOTAL_MATERIAL_COUNT}"
        )
    if len(manifest) != file_count:
        raise TemplateRuntimeValidationError("material_manifest does not match the uploaded file count")

    parsed: list[MaterialManifestItem] = []
    for index, item in enumerate(manifest):
        try:
            parsed.append(
                item if isinstance(item, MaterialManifestItem) else MaterialManifestItem.model_validate(item)
            )
        except Exception as exc:
            raise TemplateRuntimeValidationError(f"invalid material manifest item at index {index}") from exc

    requirements = {requirement.key: requirement for requirement in template.material_requirements}
    counts = {key: 0 for key in requirements}
    indexes: set[int] = set()
    for item in parsed:
        requirement = requirements.get(item.requirement_id)
        if requirement is None:
            raise TemplateRuntimeValidationError(
                f"unknown material requirement: {item.requirement_id}"
            )
        if item.file_index >= file_count or item.file_index in indexes:
            raise TemplateRuntimeValidationError("material file indexes must be unique and contiguous")
        if item.media_type != requirement.media_type:
            raise TemplateRuntimeValidationError(
                f"material requirement {item.requirement_id} requires {requirement.media_type} files"
            )
        indexes.add(item.file_index)
        counts[item.requirement_id] += 1

    if indexes != set(range(file_count)):
        raise TemplateRuntimeValidationError("material file indexes must be unique and contiguous")
    for requirement in template.material_requirements:
        count = counts[requirement.key]
        if count < requirement.min_count or count > requirement.max_count:
            raise TemplateRuntimeValidationError(
                f"material requirement {requirement.key} requires "
                f"{requirement.min_count}-{requirement.max_count} files; received {count}"
            )
    return parsed


def material_rules(template: TemplateDefinition) -> dict[str, tuple[MediaType, int, int]]:
    return {
        requirement.key: (
            requirement.media_type,
            requirement.min_count,
            requirement.max_count,
        )
        for requirement in template.material_requirements
    }


_RESPONSE_CONTRACTS: dict[ResponseFormat, str] = {
    "plain_scripts_v1": (
        '只输出合法的 JSON 字符串数组，不使用 Markdown 代码块或额外解释。'
        '例如：["第一条文案", "第二条文案"]'
    ),
    "segmented_scripts_v1": (
        '只输出合法 JSON，不使用 Markdown 代码块或额外解释。格式为：'
        '{"scripts":[{"style":"寻访过程","sentences":["第一句","第二句"]}]}'
    ),
}


def _render_prompt_template(source: str, context: Mapping[str, str]) -> str:
    return _PLACEHOLDER_PATTERN.sub(lambda match: context[match.group(1)], source)


def render_script_prompt(
    template: TemplateDefinition,
    content_values: Mapping[str, str],
    *,
    candidate_count: int | None = None,
    material_context: Mapping[str, int] | None = None,
    original_script: str | None = None,
) -> str:
    """Render a validated prompt without evaluating expressions or object paths."""

    count = template.script_generation.default_candidate_count if candidate_count is None else candidate_count
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise TemplateRuntimeValidationError("candidate_count must be between 1 and 10")
    normalized_values = validate_content_values(template, content_values)
    normalized_materials = normalize_material_context(template, material_context)

    content_lines = [
        f"- {field.label}：{normalized_values[field.key] or '未提供'}"
        for field in template.content_fields
    ]
    material_lines = [
        f"- {requirement.label}：{normalized_materials.get(requirement.key, 0)} 个"
        for requirement in template.material_requirements
        if normalized_materials.get(requirement.key, 0) > 0
    ]
    context = {
        "candidate_count": str(count),
        "content_context": "\n".join(content_lines) or "- 无额外内容信息",
        "material_context": "\n".join(material_lines) or "- 尚未提供素材数量，仅按内容信息创作文案",
        "response_contract": _RESPONSE_CONTRACTS[template.script_generation.response_format],
    }

    if original_script is None:
        source = template.script_generation.prompt_template
    else:
        if not isinstance(original_script, str) or not original_script.strip():
            raise TemplateRuntimeValidationError("original_script cannot be empty")
        source = template.script_generation.rewrite_prompt_template
        if source is None:
            raise TemplateRuntimeValidationError("this template does not support script rewriting")
        context["original_script"] = original_script.strip()
    return _render_prompt_template(source, context)
