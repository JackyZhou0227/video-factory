from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from comfykit import ComfyKit
from comfykit.comfyui.runninghub_executor import RunningHubExecutor

from app.core.config import app_config

_kit: Optional[ComfyKit] = None
_kit_config: Optional[tuple[str, Optional[str], str]] = None
_kit_lock = asyncio.Lock()


def _runninghub_base_url() -> str:
    runninghub_config = app_config.get("runninghub") or {}
    return (
        os.getenv("RUNNINGHUB_BASE_URL")
        or str(runninghub_config.get("base_url") or "").strip()
        or "https://www.runninghub.cn"
    ).rstrip("/")


def _system_runninghub_api_key() -> str:
    runninghub_config = app_config.get("runninghub") or {}
    return (os.getenv("RUNNINGHUB_API_KEY") or str(runninghub_config.get("api_key") or "")).strip()


def _new_runninghub_executor(api_key: str, instance_type: Optional[str]) -> RunningHubExecutor:
    return RunningHubExecutor(
        base_url=_runninghub_base_url(),
        api_key=api_key,
        instance_type=instance_type,
    )


def _should_retry_workflow_fetch_with_system_key(exc: Exception) -> bool:
    message = str(exc).lower()
    return "user not exist" in message or "apikey_user_not_found" in message


async def _get_kit(api_key: str, instance_type: Optional[str]) -> ComfyKit:
    """Get or create a shared ComfyKit instance."""
    global _kit, _kit_config
    async with _kit_lock:
        base_url = _runninghub_base_url()
        requested_config = (api_key, instance_type, base_url)
        if _kit is None or _kit_config != requested_config:
            config: dict = {
                "runninghub_api_key": api_key,
                "runninghub_url": base_url,
            }
            if instance_type:
                config["runninghub_instance_type"] = instance_type
            _kit = ComfyKit(**config)
            _kit_config = requested_config
        return _kit


async def _get_workflow_json_for_submission(
    executor: RunningHubExecutor,
    workflow_id: str,
    user_api_key: str,
) -> tuple[dict[str, Any], bool]:
    try:
        return await executor.client.get_workflow_json(workflow_id), False
    except Exception as exc:
        if not _should_retry_workflow_fetch_with_system_key(exc):
            raise

        system_api_key = _system_runninghub_api_key()
        if not system_api_key or system_api_key == user_api_key:
            raise RuntimeError(
                "RunningHub rejected this API key while reading the fixed workflow. "
                "Set runninghub.base_url to the account region and configure a system RunningHub API key."
            ) from exc

        system_executor = _new_runninghub_executor(system_api_key, None)
        try:
            return await system_executor.client.get_workflow_json(workflow_id), True
        except Exception as system_exc:
            raise RuntimeError(
                "RunningHub rejected the customer API key and the configured system API key "
                f"could not read workflow {workflow_id}: {system_exc}"
            ) from exc
        finally:
            await system_executor.close()


async def _create_task(
    executor: RunningHubExecutor,
    workflow_id: str,
    node_info_list: list[dict[str, Any]] | None,
    workflow_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if workflow_json is None:
        return await executor.client.create_task(
            workflow_id,
            node_info_list if node_info_list else None,
        )

    data: dict[str, Any] = {
        "apiKey": executor.client.api_key,
        "workflowId": workflow_id,
        "workflow": json.dumps(workflow_json, ensure_ascii=False),
    }
    if node_info_list:
        data["nodeInfoList"] = node_info_list
    if executor.client.instance_type:
        data["instanceType"] = executor.client.instance_type

    result = await executor.client._make_request("POST", "/task/openapi/create", data=data)
    return result.get("data", {})


async def generate_digital_human(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    workflow_id: str,
    api_key: str,
    instance_type: Optional[str] = None,
) -> Path:
    """
    Submit image + audio to RunningHub lipsync workflow.
    Downloads the resulting video to output_path and returns it.
    """
    kit = await _get_kit(api_key, instance_type)

    params = {
        "videoimage": str(image_path),
        "audio": str(audio_path),
    }

    result = await kit.execute(workflow_id, params)

    if result.status != "completed":
        raise RuntimeError(f"RunningHub workflow failed: {result.msg}")

    # Extract video URL from result
    video_url: Optional[str] = None
    if hasattr(result, "videos") and result.videos:
        video_url = result.videos[0]
    elif hasattr(result, "outputs") and result.outputs:
        for node_output in result.outputs.values():
            if isinstance(node_output, dict) and node_output.get("videos"):
                video_url = node_output["videos"][0]
                break

    if not video_url:
        raise RuntimeError("RunningHub workflow returned no video output.")

    # Download video to local output path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(300.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(video_url)
        response.raise_for_status()
        output_path.write_bytes(response.content)

    return output_path


async def submit_digital_human(
    image_path: Path,
    audio_path: Path,
    workflow_id: str,
    api_key: str,
    instance_type: Optional[str] = None,
) -> str:
    """
    Submit image + audio to RunningHub and return the RunningHub task id.
    Does not wait for remote completion or download the generated video.
    """
    executor = _new_runninghub_executor(api_key, instance_type)
    params = {
        "videoimage": str(image_path),
        "audio": str(audio_path),
    }

    try:
        workflow_json, include_workflow_json = await _get_workflow_json_for_submission(
            executor,
            workflow_id,
            api_key,
        )
        workflow_json, seed_changes = executor._randomize_seed_in_workflow(workflow_json)

        from comfykit.comfyui.workflow_parser import WorkflowParser

        parser = WorkflowParser()
        metadata = parser.parse_workflow(workflow_json, f"workflow_{workflow_id}")
        if not metadata:
            raise RuntimeError("Failed to parse RunningHub workflow metadata")

        metadata.workflow_id = workflow_id
        metadata.is_runninghub = True

        node_info_list = await executor._convert_params_to_node_info_list(
            metadata,
            params,
            seed_changes,
        )
        task_data = await _create_task(
            executor,
            workflow_id,
            node_info_list if node_info_list else None,
            workflow_json if include_workflow_json else None,
        )
        runninghub_task_id = task_data.get("taskId")
        if not runninghub_task_id:
            raise RuntimeError("RunningHub did not return a task id")

        return str(runninghub_task_id)
    finally:
        await executor.close()

