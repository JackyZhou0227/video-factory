from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.schemas.template_definition import TemplateDefinition


WEB_APP_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = WEB_APP_ROOT / "frontend" / "skills" / "generate-template-production-template"
VALIDATOR_PATH = SKILL_ROOT / "scripts" / "validate_template.py"

spec = importlib.util.spec_from_file_location("template_skill_validator", VALIDATOR_PATH)
assert spec is not None and spec.loader is not None
validator_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator_module)


def generic_template() -> dict:
    return {
        "schema_version": 1,
        "template_version": 1,
        "id": "product-story",
        "name": "产品故事",
        "description": "根据产品信息和素材批量生成介绍视频。",
        "content_fields": [
            {
                "key": "product-name",
                "label": "产品名称",
                "required": True,
                "max_length": 100,
            }
        ],
        "material_requirements": [
            {
                "key": "product-video",
                "label": "产品视频",
                "description": "清晰展示产品的视频。",
                "media_type": "video",
                "min_count": 1,
                "max_count": 3,
            }
        ],
        "script_generation": {
            "system_prompt": "你是短视频文案编导。",
            "prompt_template": (
                "根据以下信息生成 {{candidate_count}} 条文案。\n"
                "{{content_context}}\n{{material_context}}\n{{response_contract}}"
            ),
            "rewrite_prompt_template": (
                "根据 {{content_context}} 重写：{{original_script}}\n{{response_contract}}"
            ),
            "response_format": "plain_scripts_v1",
        },
        "production": {"pipeline_id": "generic_concat_v1"},
    }


def standalone_errors(value: object) -> list[str]:
    return validator_module.TemplateValidator().validate(value)


class TemplateSkillValidatorTests(unittest.TestCase):
    def test_accepts_general_template(self):
        candidates = [generic_template()]
        for candidate in candidates:
            with self.subTest(template=candidate["id"]):
                self.assertEqual(standalone_errors(candidate), [])
                TemplateDefinition.model_validate(candidate)

    def test_rejects_same_representative_invalid_templates_as_backend(self):
        cases: dict[str, dict] = {}

        value = generic_template()
        value["unexpected"] = True
        cases["unknown field"] = value

        value = generic_template()
        value["id"] = "Invalid ID"
        cases["invalid id"] = value

        value = generic_template()
        value["content_fields"].append(copy.deepcopy(value["content_fields"][0]))
        cases["duplicate content key"] = value

        value = generic_template()
        value["material_requirements"].append(
            {
                "key": "extra-video",
                "label": "补充视频",
                "description": "补充画面。",
                "media_type": "video",
                "min_count": 0,
                "max_count": 18,
            }
        )
        cases["material capacity"] = value

        value = generic_template()
        value["script_generation"]["prompt_template"] = "{{unknown_value}}"
        cases["unknown placeholder"] = value

        value = generic_template()
        value["script_generation"]["response_format"] = "markdown_v1"
        cases["unsupported response"] = value

        value = generic_template()
        value["production"]["pipeline_id"] = "custom_pipeline_v1"
        cases["unknown pipeline"] = value

        value = generic_template()
        value["production"]["default_ratio"] = "4:3"
        cases["unsupported ratio"] = value

        for name, candidate in cases.items():
            with self.subTest(case=name):
                self.assertTrue(standalone_errors(candidate))
                with self.assertRaises(ValidationError):
                    TemplateDefinition.model_validate(candidate)

    def test_cli_exit_codes_and_field_paths(self):
        environment = {**os.environ, "PYTHONUTF8": "1"}
        with tempfile.TemporaryDirectory() as temp_dir:
            valid_path = Path(temp_dir) / "valid.json"
            valid_path.write_text(json.dumps(generic_template(), ensure_ascii=False), encoding="utf-8")
            valid = subprocess.run(
                [sys.executable, str(VALIDATOR_PATH), str(valid_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                check=False,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertIn("模板校验通过", valid.stdout)

            invalid_path = Path(temp_dir) / "invalid.json"
            invalid_path.write_text('{"id":', encoding="utf-8")
            invalid = subprocess.run(
                [sys.executable, str(VALIDATOR_PATH), str(invalid_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                check=False,
            )
            self.assertEqual(invalid.returncode, 1)
            self.assertIn("- $:", invalid.stderr)

            wrong_id = generic_template()
            wrong_id["id"] = "Not Valid"
            invalid_path.write_text(json.dumps(wrong_id, ensure_ascii=False), encoding="utf-8")
            invalid = subprocess.run(
                [sys.executable, str(VALIDATOR_PATH), str(invalid_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                check=False,
            )
            self.assertEqual(invalid.returncode, 1)
            self.assertIn("$.id", invalid.stderr)

            usage = subprocess.run(
                [sys.executable, str(VALIDATOR_PATH)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                check=False,
            )
            self.assertEqual(usage.returncode, 2)


if __name__ == "__main__":
    unittest.main()
