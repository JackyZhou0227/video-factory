from __future__ import annotations

import json
import unittest
from copy import deepcopy

from pydantic import ValidationError

from app.schemas.template_definition import (
    MAX_TOTAL_MATERIAL_COUNT,
    TemplateDefinition,
    TemplateRuntimeValidationError,
    render_script_prompt,
    validate_content_values,
    validate_material_manifest,
)
from app.services.template_registry import (
    MAX_TEMPLATE_JSON_BYTES,
    TemplateConflictError,
    TemplateImportError,
    TemplateNotFoundError,
    TemplateRegistry,
)
from tests.pg_test_utils import ensure_test_user


def _generic_template(template_id: str = "campaign-template") -> dict:
    return {
        "schema_version": 1,
        "template_version": 1,
        "id": template_id,
        "name": "活动介绍",
        "description": "用于测试导入模板。",
        "content_fields": [
            {
                "key": "tone",
                "label": "表达风格",
                "input_type": "select",
                "required": True,
                "default": "calm",
                "options": [
                    {"value": "calm", "label": "克制"},
                    {"value": "warm", "label": "温暖"},
                ],
            },
            {
                "key": "subject",
                "label": "介绍对象",
                "required": True,
                "min_length": 2,
                "max_length": 100,
            },
        ],
        "material_requirements": [
            {
                "key": "main-image",
                "label": "主体图片",
                "description": "用于视频主体画面的图片。",
                "media_type": "image",
                "min_count": 1,
                "max_count": 2,
            }
        ],
        "script_generation": {
            "system_prompt": "你是短视频文案编导。",
            "prompt_template": "生成 {{candidate_count}} 条文案。\n{{content_context}}\n{{material_context}}\n{{response_contract}}",
            "rewrite_prompt_template": "重写 {{original_script}}\n{{content_context}}\n{{response_contract}}",
            "response_format": "plain_scripts_v1",
            "default_candidate_count": 3,
            "temperature": 0.75,
            "max_tokens": 2400,
        },
        "production": {
            "pipeline_id": "generic_concat_v1",
            "default_ratio": "9:16",
            "default_batch_size": 5,
            "max_batch_size": 50,
        },
    }


class TemplateDefinitionTests(unittest.TestCase):
    def test_models_are_strict_and_validate_nested_constraints(self):
        value = _generic_template()
        value["unexpected"] = True
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

        value = _generic_template()
        value["material_requirements"][0].update(min_count=2, max_count=1)
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

        value = _generic_template()
        value["content_fields"][0]["options"].append(
            {"value": "calm", "label": "重复值"}
        )
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

        value = _generic_template()
        value["content_fields"][0]["default"] = "missing-option"
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

        value = _generic_template()
        value["content_fields"][0]["default"] = ""
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

        value = _generic_template()
        value["content_fields"][0]["max_length"] = 3
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

        value = _generic_template()
        value["content_fields"].append(deepcopy(value["content_fields"][1]))
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

    def test_prompt_placeholders_and_pipeline_bindings_are_whitelisted(self):
        value = _generic_template()
        value["script_generation"]["prompt_template"] = "{{content_context.__class__}}"
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

        value = _generic_template()
        value["script_generation"]["prompt_template"] = "{{unknown_value}}"
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

        value = _generic_template()
        value["script_generation"]["response_format"] = "markdown_v1"
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

        value = _generic_template()
        value["production"]["pipeline_id"] = "run_python_v1"
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

    def test_total_material_capacity_is_limited(self):
        value = _generic_template()
        value["material_requirements"] = [
            {
                "key": f"slot-{index}",
                "label": f"槽位 {index}",
                "description": "测试素材。",
                "media_type": "video",
                "min_count": 0,
                "max_count": 2,
            }
            for index in range(MAX_TOTAL_MATERIAL_COUNT // 2 + 1)
        ]
        with self.assertRaises(ValidationError):
            TemplateDefinition.model_validate(value)

    def test_runtime_values_manifest_and_prompt_rendering(self):
        template = TemplateDefinition.model_validate(_generic_template())
        normalized = validate_content_values(template, {"subject": "  王医生  "})
        self.assertEqual(normalized, {"tone": "calm", "subject": "王医生"})

        prompt = render_script_prompt(
            template,
            {"subject": "王医生"},
            candidate_count=2,
            material_context={"main-image": 1},
        )
        self.assertIn("生成 2 条文案", prompt)
        self.assertIn("介绍对象：王医生", prompt)
        self.assertIn("主体图片：1 个", prompt)
        self.assertNotIn("{{", prompt)

        parsed = validate_material_manifest(
            template,
            [
                {
                    "requirement_id": "main-image",
                    "file_index": 0,
                    "media_type": "image",
                    "name": "doctor.png",
                }
            ],
            1,
        )
        self.assertEqual(parsed[0].name, "doctor.png")

        with self.assertRaises(TemplateRuntimeValidationError):
            validate_material_manifest(
                template,
                [{"requirement_id": "main-image", "file_index": 0, "media_type": "video"}],
                1,
            )
        with self.assertRaises(TemplateRuntimeValidationError):
            render_script_prompt(
                template,
                {"subject": "王医生"},
                material_context=[],  # type: ignore[arg-type]
            )
        with self.assertRaises(TemplateRuntimeValidationError):
            validate_content_values(template, {1: "invalid key"})  # type: ignore[dict-item]


class TemplateRegistryTests(unittest.TestCase):
    def setUp(self):
        ensure_test_user("user-a")
        ensure_test_user("user-b")

    def test_import_list_and_export_round_trip_preserves_unicode(self):
        registry = TemplateRegistry()
        imported = registry.import_template_json(
            "user-a", json.dumps(_generic_template(), ensure_ascii=False)
        )
        self.assertEqual(imported.id, "campaign-template")
        self.assertEqual(registry.get_template("user-a", imported.id), imported)

        entries = registry.list_entries("user-a")
        self.assertEqual([entry.definition.id for entry in entries], ["campaign-template"])
        exported = registry.export_template_json("user-a", imported.id)
        self.assertIn("活动介绍", exported)
        restored = TemplateDefinition.model_validate_json(exported)
        self.assertEqual(restored, imported)
        self.assertNotIn("content_values", exported)
        self.assertNotIn("material_manifest", exported)

        with self.assertRaises(TemplateNotFoundError):
            registry.get_template("user-a", "missing-template")

    def test_import_is_conflict_checked_across_users(self):
        registry = TemplateRegistry()
        payload = json.dumps(_generic_template(), ensure_ascii=False)
        registry.import_template_json("user-a", payload)
        with self.assertRaises(TemplateConflictError):
            registry.import_template_json("user-b", payload)

    def test_import_rejects_size_limit_and_unknown_pipeline(self):
        registry = TemplateRegistry()
        with self.assertRaises(TemplateImportError):
            registry.import_template_json("user-a", b" " * (MAX_TEMPLATE_JSON_BYTES + 1))
        with self.assertRaises(TemplateImportError):
            registry.import_template_json("user-a", "\ud800")

        value = _generic_template()
        value["production"]["pipeline_id"] = "unregistered_v1"
        with self.assertRaises(TemplateImportError):
            registry.import_template_json(
                "user-a",
                json.dumps(value, ensure_ascii=False),
            )

    def test_import_rejects_definition_whose_export_exceeds_size_limit(self):
        registry = TemplateRegistry()
        value = _generic_template("large-canonical-template")
        compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        canonical = TemplateDefinition.model_validate(value).model_dump_json(
            indent=2,
            exclude_none=True,
        )
        whitespace_overhead = len(canonical.encode("utf-8")) - len(compact.encode("utf-8"))
        target_size = MAX_TEMPLATE_JSON_BYTES - max(1, whitespace_overhead // 2)
        filler_size = target_size - len(compact.encode("utf-8"))

        prompt = value["script_generation"]["prompt_template"]
        prompt_room = 80_000 - len(prompt)
        prompt_filler = min(filler_size, prompt_room)
        value["script_generation"]["prompt_template"] = prompt + ("x" * prompt_filler)
        rewrite_filler = filler_size - prompt_filler
        value["script_generation"]["rewrite_prompt_template"] += "y" * rewrite_filler
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))

        self.assertLessEqual(len(payload.encode("utf-8")), MAX_TEMPLATE_JSON_BYTES)
        with self.assertRaises(TemplateImportError):
            registry.import_template_json("user-a", payload)


if __name__ == "__main__":
    unittest.main()
