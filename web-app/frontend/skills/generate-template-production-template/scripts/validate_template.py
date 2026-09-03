#!/usr/bin/env python3
"""Validate a Video Factory template JSON without project dependencies."""

from __future__ import annotations

import copy
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


MAX_TEMPLATE_BYTES = 128 * 1024
MAX_CONTENT_FIELDS = 50
MAX_MATERIAL_REQUIREMENTS = 20
MAX_TOTAL_MATERIAL_COUNT = 20
MAX_SELECT_OPTIONS = 100
MAX_CONTENT_VALUE_LENGTH = 10_000

IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
ANY_PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}", flags=re.DOTALL)

PROMPT_PLACEHOLDERS = {
    "candidate_count",
    "content_context",
    "material_context",
    "response_contract",
}
REWRITE_PROMPT_PLACEHOLDERS = PROMPT_PLACEHOLDERS | {"original_script"}
VIDEO_RATIOS = {"9:16", "16:9", "1:1", "3:4"}
PIPELINES = {"generic_concat_v1"}
RESPONSE_FORMATS = {"plain_scripts_v1", "segmented_scripts_v1"}


class TemplateValidator:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def object(
        self,
        value: Any,
        path: str,
        *,
        allowed: set[str],
        required: set[str] = frozenset(),
    ) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            self.error(path, "必须是 JSON 对象")
            return None
        for key in value:
            if not isinstance(key, str) or key not in allowed:
                self.error(f"{path}.{key}", "不支持的字段")
        for key in sorted(required - set(value)):
            self.error(f"{path}.{key}", "缺少必填字段")
        return value

    def array(
        self,
        value: Any,
        path: str,
        *,
        minimum: int = 0,
        maximum: int | None = None,
    ) -> list[Any] | None:
        if not isinstance(value, list):
            self.error(path, "必须是数组")
            return None
        if len(value) < minimum:
            self.error(path, f"至少需要 {minimum} 项")
        if maximum is not None and len(value) > maximum:
            self.error(path, f"最多允许 {maximum} 项")
        return value

    def string(
        self,
        value: Any,
        path: str,
        *,
        minimum: int = 0,
        maximum: int | None = None,
        pattern: re.Pattern[str] | None = None,
        choices: set[str] | None = None,
    ) -> str | None:
        if not isinstance(value, str):
            self.error(path, "必须是字符串")
            return None
        normalized = value.strip()
        if len(normalized) < minimum:
            self.error(path, f"长度不能小于 {minimum}")
        if maximum is not None and len(normalized) > maximum:
            self.error(path, f"长度不能超过 {maximum}")
        if pattern is not None and not pattern.fullmatch(normalized):
            self.error(path, "格式不正确")
        if choices is not None and normalized not in choices:
            self.error(path, f"不支持的值 {normalized!r}")
        return normalized

    def integer(
        self,
        value: Any,
        path: str,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            self.error(path, "必须是整数")
            return None
        if minimum is not None and value < minimum:
            self.error(path, f"不能小于 {minimum}")
        if maximum is not None and value > maximum:
            self.error(path, f"不能大于 {maximum}")
        return value

    def number(
        self,
        value: Any,
        path: str,
        *,
        minimum: float,
        maximum: float,
    ) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.error(path, "必须是数字")
            return None
        parsed = float(value)
        if not math.isfinite(parsed):
            self.error(path, "必须是有限数字")
        elif not minimum <= parsed <= maximum:
            self.error(path, f"必须在 {minimum:g}-{maximum:g} 之间")
        return parsed

    def boolean(self, value: Any, path: str) -> bool | None:
        if not isinstance(value, bool):
            self.error(path, "必须是布尔值")
            return None
        return value

    def validate_placeholders(self, value: str | None, path: str, allowed: set[str]) -> None:
        if value is None:
            return
        if "{%" in value or "%}" in value or "{#" in value or "#}" in value:
            self.error(path, "不支持模板语句或模板注释")

        unknown: set[str] = set()
        malformed = False
        for match in ANY_PLACEHOLDER_RE.finditer(value):
            strict_match = PLACEHOLDER_RE.fullmatch(match.group(0))
            if strict_match is None:
                malformed = True
            elif strict_match.group(1) not in allowed:
                unknown.add(strict_match.group(1))

        remainder = ANY_PLACEHOLDER_RE.sub("", value)
        if "{{" in remainder or "}}" in remainder:
            malformed = True
        if malformed:
            self.error(path, "包含格式错误的占位符")
        if unknown:
            self.error(path, f"包含未知占位符：{', '.join(sorted(unknown))}")

    def validate_select_option(self, value: Any, path: str) -> tuple[str | None, str | None]:
        item = self.object(
            value,
            path,
            allowed={"value", "label"},
            required={"value", "label"},
        )
        if item is None:
            return None, None
        option_value = self.string(item.get("value"), f"{path}.value", minimum=1, maximum=200)
        label = self.string(item.get("label"), f"{path}.label", minimum=1, maximum=200)
        return option_value, label

    def validate_content_field(self, value: Any, path: str) -> str | None:
        item = self.object(
            value,
            path,
            allowed={
                "key",
                "label",
                "input_type",
                "required",
                "placeholder",
                "help_text",
                "default",
                "options",
                "min_length",
                "max_length",
            },
            required={"key", "label"},
        )
        if item is None:
            return None

        key = self.string(
            item.get("key"),
            f"{path}.key",
            minimum=1,
            maximum=64,
            pattern=IDENTIFIER_RE,
        )
        self.string(item.get("label"), f"{path}.label", minimum=1, maximum=100)
        input_type = self.string(
            item.get("input_type", "text"),
            f"{path}.input_type",
            choices={"text", "textarea", "select"},
        )
        required = self.boolean(item.get("required", True), f"{path}.required")

        optional_strings = {
            "placeholder": 500,
            "help_text": 1_000,
            "default": MAX_CONTENT_VALUE_LENGTH,
        }
        normalized_strings: dict[str, str | None] = {}
        for name, maximum in optional_strings.items():
            raw = item.get(name)
            normalized_strings[name] = (
                None if raw is None else self.string(raw, f"{path}.{name}", maximum=maximum)
            )

        min_length = item.get("min_length")
        if min_length is not None:
            min_length = self.integer(
                min_length,
                f"{path}.min_length",
                minimum=0,
                maximum=MAX_CONTENT_VALUE_LENGTH,
            )
        max_length = item.get("max_length")
        if max_length is not None:
            max_length = self.integer(
                max_length,
                f"{path}.max_length",
                minimum=1,
                maximum=MAX_CONTENT_VALUE_LENGTH,
            )
        if min_length is not None and max_length is not None and min_length > max_length:
            self.error(path, "min_length 不能大于 max_length")

        raw_options = item.get("options", [])
        options = self.array(raw_options, f"{path}.options", maximum=MAX_SELECT_OPTIONS)
        option_values: list[str] = []
        if options is not None:
            for index, option in enumerate(options):
                option_value, _ = self.validate_select_option(option, f"{path}.options[{index}]")
                if option_value is not None:
                    option_values.append(option_value)

        if input_type == "select":
            if not options:
                self.error(f"{path}.options", "select 字段至少需要一个选项")
            if len(option_values) != len(set(option_values)):
                self.error(f"{path}.options", "选项 value 必须唯一")
            if min_length is not None and any(len(option) < min_length for option in option_values):
                self.error(f"{path}.options", "选项 value 不能短于 min_length")
            if max_length is not None and any(len(option) > max_length for option in option_values):
                self.error(f"{path}.options", "选项 value 不能长于 max_length")
            default = normalized_strings["default"]
            if default is not None and default not in option_values:
                self.error(f"{path}.default", "必须匹配一个选项 value")
        elif options:
            self.error(f"{path}.options", "只有 select 字段支持 options")

        default = normalized_strings["default"]
        if default is not None:
            if required is True and not default:
                self.error(f"{path}.default", "必填字段的默认值不能为空")
            if min_length is not None and len(default) < min_length:
                self.error(f"{path}.default", "短于 min_length")
            if max_length is not None and len(default) > max_length:
                self.error(f"{path}.default", "长于 max_length")
        return key

    def validate_material_requirement(self, value: Any, path: str) -> tuple[str | None, dict[str, Any] | None]:
        item = self.object(
            value,
            path,
            allowed={"key", "label", "description", "media_type", "min_count", "max_count"},
            required={"key", "label", "description", "media_type", "min_count", "max_count"},
        )
        if item is None:
            return None, None
        key = self.string(
            item.get("key"),
            f"{path}.key",
            minimum=1,
            maximum=64,
            pattern=IDENTIFIER_RE,
        )
        self.string(item.get("label"), f"{path}.label", minimum=1, maximum=100)
        self.string(item.get("description"), f"{path}.description", minimum=1, maximum=1_000)
        media_type = self.string(
            item.get("media_type"),
            f"{path}.media_type",
            choices={"image", "video"},
        )
        min_count = self.integer(
            item.get("min_count"),
            f"{path}.min_count",
            minimum=0,
            maximum=MAX_TOTAL_MATERIAL_COUNT,
        )
        max_count = self.integer(
            item.get("max_count"),
            f"{path}.max_count",
            minimum=1,
            maximum=MAX_TOTAL_MATERIAL_COUNT,
        )
        if min_count is not None and max_count is not None and min_count > max_count:
            self.error(path, "min_count 不能大于 max_count")
        return key, {
            "key": key,
            "media_type": media_type,
            "min_count": min_count,
            "max_count": max_count,
        }

    def validate_script_generation(self, value: Any, path: str) -> dict[str, Any] | None:
        item = self.object(
            value,
            path,
            allowed={
                "system_prompt",
                "prompt_template",
                "rewrite_prompt_template",
                "response_format",
                "default_candidate_count",
                "temperature",
                "max_tokens",
            },
            required={"system_prompt", "prompt_template", "response_format"},
        )
        if item is None:
            return None
        system_prompt = self.string(
            item.get("system_prompt"), f"{path}.system_prompt", minimum=1, maximum=20_000
        )
        prompt_template = self.string(
            item.get("prompt_template"), f"{path}.prompt_template", minimum=1, maximum=80_000
        )
        rewrite_prompt = item.get("rewrite_prompt_template")
        if rewrite_prompt is not None:
            rewrite_prompt = self.string(
                rewrite_prompt, f"{path}.rewrite_prompt_template", maximum=80_000
            )
        response_format = self.string(
            item.get("response_format"),
            f"{path}.response_format",
            choices=RESPONSE_FORMATS,
        )
        self.integer(
            item.get("default_candidate_count", 3),
            f"{path}.default_candidate_count",
            minimum=1,
            maximum=10,
        )
        self.number(
            item.get("temperature", 0.75),
            f"{path}.temperature",
            minimum=0,
            maximum=2,
        )
        self.integer(
            item.get("max_tokens", 2400),
            f"{path}.max_tokens",
            minimum=1,
            maximum=32_768,
        )
        self.validate_placeholders(system_prompt, f"{path}.system_prompt", set())
        self.validate_placeholders(prompt_template, f"{path}.prompt_template", PROMPT_PLACEHOLDERS)
        self.validate_placeholders(
            rewrite_prompt, f"{path}.rewrite_prompt_template", REWRITE_PROMPT_PLACEHOLDERS
        )
        if rewrite_prompt is not None and "original_script" not in {
            match.group(1) for match in PLACEHOLDER_RE.finditer(rewrite_prompt)
        }:
            self.error(f"{path}.rewrite_prompt_template", "必须包含 {{original_script}}")
        return {"response_format": response_format}

    def validate_production(self, value: Any, path: str) -> dict[str, Any] | None:
        item = self.object(
            value,
            path,
            allowed={"pipeline_id", "default_ratio", "default_batch_size", "max_batch_size"},
            required={"pipeline_id"},
        )
        if item is None:
            return None
        pipeline_id = self.string(
            item.get("pipeline_id"), f"{path}.pipeline_id", minimum=1, maximum=64, choices=PIPELINES
        )
        self.string(
            item.get("default_ratio", "9:16"),
            f"{path}.default_ratio",
            choices=VIDEO_RATIOS,
        )
        default_batch_size = self.integer(
            item.get("default_batch_size", 5),
            f"{path}.default_batch_size",
            minimum=1,
            maximum=50,
        )
        max_batch_size = self.integer(
            item.get("max_batch_size", 50),
            f"{path}.max_batch_size",
            minimum=1,
            maximum=50,
        )
        if (
            default_batch_size is not None
            and max_batch_size is not None
            and default_batch_size > max_batch_size
        ):
            self.error(path, "default_batch_size 不能大于 max_batch_size")
        return {"pipeline_id": pipeline_id}

    def validate(self, value: Any) -> list[str]:
        template = self.object(
            value,
            "$",
            allowed={
                "schema_version",
                "template_version",
                "id",
                "name",
                "description",
                "content_fields",
                "material_requirements",
                "script_generation",
                "production",
            },
            required={"id", "name", "material_requirements", "script_generation", "production"},
        )
        if template is None:
            return self.errors

        schema_version = self.integer(template.get("schema_version", 1), "$.schema_version")
        if schema_version is not None and schema_version != 1:
            self.error("$.schema_version", "当前仅支持版本 1")
        self.integer(template.get("template_version", 1), "$.template_version", minimum=1)
        self.string(
            template.get("id"), "$.id", minimum=1, maximum=64, pattern=IDENTIFIER_RE
        )
        self.string(template.get("name"), "$.name", minimum=1, maximum=100)
        self.string(template.get("description", ""), "$.description", maximum=1_000)

        content_fields = self.array(
            template.get("content_fields", []), "$.content_fields", maximum=MAX_CONTENT_FIELDS
        )
        content_keys: list[str] = []
        if content_fields is not None:
            for index, field in enumerate(content_fields):
                key = self.validate_content_field(field, f"$.content_fields[{index}]")
                if key is not None:
                    content_keys.append(key)
        if len(content_keys) != len(set(content_keys)):
            self.error("$.content_fields", "字段 key 必须唯一")

        materials = self.array(
            template.get("material_requirements"),
            "$.material_requirements",
            minimum=1,
            maximum=MAX_MATERIAL_REQUIREMENTS,
        )
        material_items: list[dict[str, Any]] = []
        material_keys: list[str] = []
        if materials is not None:
            for index, material in enumerate(materials):
                key, parsed = self.validate_material_requirement(
                    material, f"$.material_requirements[{index}]"
                )
                if key is not None:
                    material_keys.append(key)
                if parsed is not None:
                    material_items.append(parsed)
        if len(material_keys) != len(set(material_keys)):
            self.error("$.material_requirements", "素材槽 key 必须唯一")
        capacities = [item["max_count"] for item in material_items if item["max_count"] is not None]
        if sum(capacities) > MAX_TOTAL_MATERIAL_COUNT:
            self.error(
                "$.material_requirements",
                f"所有素材槽的 max_count 总和不能超过 {MAX_TOTAL_MATERIAL_COUNT}",
            )

        script = self.validate_script_generation(
            template.get("script_generation"), "$.script_generation"
        )
        production = self.validate_production(template.get("production"), "$.production")
        pipeline_id = production.get("pipeline_id") if production else None
        response_format = script.get("response_format") if script else None

        if pipeline_id == "generic_concat_v1" and material_items:
            if not any((item["min_count"] or 0) > 0 for item in material_items):
                self.error(
                    "$.material_requirements",
                    "generic_concat_v1 至少需要一个 min_count 大于 0 的素材槽",
                )
        if not self.errors:
            normalized = add_defaults_and_strip_strings(value)
            canonical = json.dumps(normalized, ensure_ascii=False, indent=2).encode("utf-8")
            if len(canonical) > MAX_TEMPLATE_BYTES:
                self.error("$", f"标准化后的模板不能超过 {MAX_TEMPLATE_BYTES} 字节")
        return self.errors


def add_defaults_and_strip_strings(value: Any) -> dict[str, Any]:
    normalized = copy.deepcopy(value)
    normalized.setdefault("schema_version", 1)
    normalized.setdefault("template_version", 1)
    normalized.setdefault("description", "")
    normalized.setdefault("content_fields", [])
    for field in normalized["content_fields"]:
        field.setdefault("input_type", "text")
        field.setdefault("required", True)
        field.setdefault("options", [])
    script = normalized["script_generation"]
    script.setdefault("default_candidate_count", 3)
    script.setdefault("temperature", 0.75)
    script.setdefault("max_tokens", 2400)
    production = normalized["production"]
    production.setdefault("default_ratio", "9:16")
    production.setdefault("default_batch_size", 5)
    production.setdefault("max_batch_size", 50)

    def normalize(item: Any) -> Any:
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items() if child is not None}
        return item

    return normalize(normalized)


def load_template(path: Path) -> Any:
    raw = path.read_bytes()
    if not raw:
        raise OSError("文件为空")
    if len(raw) > MAX_TEMPLATE_BYTES:
        raise ValueError(f"模板文件不能超过 {MAX_TEMPLATE_BYTES} 字节")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("模板文件必须使用 UTF-8 编码") from exc

    def reject_constant(value: str) -> None:
        raise ValueError(f"JSON 不支持常量 {value}")

    try:
        return json.loads(text, parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 语法错误（第 {exc.lineno} 行，第 {exc.colno} 列）：{exc.msg}") from exc


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("用法：python scripts/validate_template.py <模板文件路径>", file=sys.stderr)
        return 2
    path = Path(arguments[0]).expanduser()
    try:
        value = load_template(path)
    except OSError as exc:
        print(f"无法读取模板：{exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"模板不合规：\n- $: {exc}", file=sys.stderr)
        return 1

    errors = TemplateValidator().validate(value)
    if errors:
        print("模板不合规：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"模板校验通过：{path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
