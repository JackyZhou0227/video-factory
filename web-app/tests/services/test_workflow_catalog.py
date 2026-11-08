from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.services import workflow_catalog


class WorkflowCatalogTests(unittest.TestCase):
    def test_public_catalog_contains_runninghub_talking_video_workflow(self):
        workflows = workflow_catalog.list_public_workflows()

        self.assertEqual(len(workflows), 1)
        workflow = workflows[0]
        self.assertEqual(workflow["key"], "digital-human-lipsync")
        self.assertEqual(workflow["provider"], "runninghub")
        self.assertEqual(
            [(item["key"], item["type"]) for item in workflow["inputs"]],
            [("image", "image"), ("audio", "audio")],
        )
        self.assertNotIn("workflow_id", workflow)
        self.assertNotIn("api_key", workflow)

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
