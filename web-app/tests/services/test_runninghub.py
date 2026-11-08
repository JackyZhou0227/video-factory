import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services import runninghub


def test_workflow_fetch_does_not_retry_with_configured_key():
    user_key_error = RuntimeError("user not exist")
    executor = Mock()
    executor.client.get_workflow_json = AsyncMock(side_effect=user_key_error)

    with (
        patch.dict(runninghub.app_config, {"runninghub": {"api_key": "config-key"}}),
        patch.object(runninghub, "_new_runninghub_executor") as create_executor,
    ):
        with pytest.raises(RuntimeError, match="user not exist"):
            asyncio.run(
                runninghub._get_workflow_json_for_submission(
                    executor,
                    "workflow-id",
                )
            )

    create_executor.assert_not_called()
    executor.client.get_workflow_json.assert_awaited_once_with("workflow-id")


def test_submit_workflow_uses_declared_provider_parameters():
    executor = Mock()
    executor.client.get_workflow_json = AsyncMock(return_value={"nodes": []})
    executor._randomize_seed_in_workflow.return_value = ({"nodes": []}, {})
    executor._convert_params_to_node_info_list = AsyncMock(return_value=[{"nodeId": "1"}])
    executor.close = AsyncMock()
    metadata = Mock()
    parser = Mock()
    parser.parse_workflow.return_value = metadata
    create_task = AsyncMock(return_value={"taskId": "rh-task-1"})
    parameters = {"videoimage": "input.png", "audio": "input.wav", "strength": 0.5}

    with (
        patch.object(runninghub, "_new_runninghub_executor", return_value=executor),
        patch("comfykit.comfyui.workflow_parser.WorkflowParser", return_value=parser),
        patch.object(runninghub, "_create_task", create_task),
    ):
        task_id = asyncio.run(
            runninghub.submit_workflow(
                workflow_id="workflow-id",
                parameters=parameters,
                api_key="test-key",
                instance_type="plus",
            )
        )

    assert task_id == "rh-task-1"
    executor._convert_params_to_node_info_list.assert_awaited_once_with(
        metadata,
        parameters,
        {},
    )
    create_task.assert_awaited_once()
    executor.close.assert_awaited_once()
