from __future__ import annotations

import json
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.core.config import ROOT
from app.services import workflow_catalog


class WorkflowCatalogTests(unittest.TestCase):
    def test_public_catalog_contains_runninghub_talking_video_workflow(self):
        workflows = workflow_catalog.list_public_workflows()

        self.assertEqual(len(workflows), 2)  # digital-human-lipsync, text-to-image

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
            [("prompt", "textarea"), ("negative_prompt", "textarea"), ("width", "number"), ("height", "number")],
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
