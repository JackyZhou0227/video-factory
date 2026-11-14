from __future__ import annotations

import json
import math
import unittest

from fastapi import HTTPException

from app.core.config import ROOT
from app.services import workflow_catalog


class WorkflowCatalogTests(unittest.TestCase):
    def test_public_catalog_contains_runninghub_lip_sync_workflow(self):
        workflows = workflow_catalog.list_public_workflows()

        self.assertEqual(len(workflows), 3)  # digital-human-lipsync, text-to-image, image-edit

        # Find digital-human-lipsync
        lipsync = next(w for w in workflows if w["key"] == "digital-human-lipsync")
        self.assertIn("runninghub", lipsync["sources"])
        self.assertEqual(
            [(item["key"], item["type"]) for item in lipsync["inputs"]],
            [("image", "image"), ("audio", "audio")],
        )

        # text-to-image 只有 selfhost 来源
        text2img = next(w for w in workflows if w["key"] == "text-to-image")
        self.assertEqual(text2img["sources"], ["selfhost"])
        self.assertEqual(
            [(item["key"], item["type"]) for item in text2img["inputs"]],
            [("prompt", "textarea"), ("resolution", "select"), ("aspect_ratio", "select")],
        )
        resolution = next(item for item in text2img["inputs"] if item["key"] == "resolution")
        self.assertEqual(list(resolution["options"]), ["480p", "720p", "1080p"])
        aspect = next(item for item in text2img["inputs"] if item["key"] == "aspect_ratio")
        self.assertEqual(
            list(aspect["options"]),
            ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "21:9", "9:16"],
        )
        self.assertNotIn("selfhost_value_map", resolution)

        image_edit = next(w for w in workflows if w["key"] == "image-edit")
        self.assertEqual(image_edit["sources"], ["selfhost"])
        self.assertEqual(
            [(item["key"], item["type"]) for item in image_edit["inputs"]],
            [("image", "image"), ("prompt", "textarea")],
        )

    def test_selfhost_input_mappings_point_at_nodes_in_the_workflow_json(self):
        for workflow in workflow_catalog.WORKFLOWS:
            sources = workflow_catalog._scan_workflow_sources(workflow["key"])
            if "selfhost" not in sources:
                continue
            workflow_json = json.loads(
                (ROOT / sources["selfhost"]["workflow_path"]).read_text(encoding="utf-8")
            )
            for field in workflow["inputs"]:
                node_id = field.get("selfhost_node_id")
                if not node_id:
                    continue
                self.assertIn(node_id, workflow_json, f"{workflow['key']}:{field['key']}")
                self.assertIn(
                    field["selfhost_input_key"],
                    workflow_json[node_id]["inputs"],
                    f"{workflow['key']}:{field['key']}",
                )

    def test_text_to_image_resolution_presets_match_resolution_selector(self):
        workflow = workflow_catalog.get_workflow("text-to-image")
        resolution = next(field for field in workflow["inputs"] if field["key"] == "resolution")
        aspect = next(field for field in workflow["inputs"] if field["key"] == "aspect_ratio")
        ratios = {
            "1:1": (1, 1),
            "4:3": (4, 3),
            "3:4": (3, 4),
            "3:2": (3, 2),
            "2:3": (2, 3),
            "16:9": (16, 9),
            "21:9": (21, 9),
            "9:16": (9, 16),
        }
        expected = {
            "480p": {
                "1:1": (640, 640),
                "4:3": (736, 560),
                "3:4": (560, 736),
                "3:2": (784, 528),
                "2:3": (528, 784),
                "16:9": (848, 480),
                "21:9": (976, 416),
                "9:16": (480, 848),
            },
            "720p": {
                "1:1": (960, 960),
                "4:3": (1104, 832),
                "3:4": (832, 1104),
                "3:2": (1168, 784),
                "2:3": (784, 1168),
                "16:9": (1280, 720),
                "21:9": (1472, 624),
                "9:16": (720, 1280),
            },
            "1080p": {
                "1:1": (1440, 1440),
                "4:3": (1664, 1248),
                "3:4": (1248, 1664),
                "3:2": (1760, 1168),
                "2:3": (1168, 1760),
                "16:9": (1920, 1088),
                "21:9": (2192, 944),
                "9:16": (1088, 1920),
            },
        }

        self.assertEqual(set(resolution["selfhost_value_map"]), set(resolution["options"]))
        self.assertEqual(set(aspect["selfhost_value_map"]), set(aspect["options"]))
        for clarity, megapixels in resolution["selfhost_value_map"].items():
            for label, (width_ratio, height_ratio) in ratios.items():
                total_pixels = megapixels * 1024 * 1024
                scale = math.sqrt(total_pixels / (width_ratio * height_ratio))
                width = round(width_ratio * scale / 16) * 16
                height = round(height_ratio * scale / 16) * 16
                self.assertEqual((width, height), expected[clarity][label])

    def test_text_to_image_omitted_inputs_use_workflow_defaults(self):
        workflow = workflow_catalog.get_workflow("text-to-image")

        valid = workflow_catalog.validate_scalar_inputs(workflow, {"prompt": "a cat"})

        self.assertEqual(valid["resolution"], "720p")
        self.assertEqual(valid["aspect_ratio"], "9:16")
        self.assertEqual(set(valid), {"prompt", "resolution", "aspect_ratio"})

    def test_resolve_workflow_rejects_unknown_key(self):
        with self.assertRaises(HTTPException) as error:
            workflow_catalog.get_workflow("unknown")

        self.assertEqual(error.exception.status_code, 404)

    def test_validate_scalar_inputs_enforces_number_and_select_constraints(self):
        workflow = {
            "inputs": [
                {
                    "key": "strength",
                    "label": "Strength",
                    "type": "number",
                    "required": True,
                    "min": 0,
                    "max": 1,
                },
                {
                    "key": "mode",
                    "label": "Mode",
                    "type": "select",
                    "required": True,
                    "options": ["fast", "quality"],
                },
            ]
        }

        valid = workflow_catalog.validate_scalar_inputs(
            workflow,
            {"strength": "0.5", "mode": "quality"},
        )
        self.assertEqual(valid, {"strength": 0.5, "mode": "quality"})

        with self.assertRaises(HTTPException):
            workflow_catalog.validate_scalar_inputs(
                workflow,
                {"strength": "1.5", "mode": "quality"},
            )
        with self.assertRaises(HTTPException):
            workflow_catalog.validate_scalar_inputs(
                workflow,
                {"strength": "0.5", "mode": "invalid"},
            )
        with self.assertRaises(HTTPException):
            workflow_catalog.validate_scalar_inputs(
                workflow,
                {"strength": "0.5"},
            )


if __name__ == "__main__":
    unittest.main()
