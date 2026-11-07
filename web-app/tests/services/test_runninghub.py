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
