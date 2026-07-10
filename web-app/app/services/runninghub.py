from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import httpx
from comfykit import ComfyKit
from comfykit.comfyui.runninghub_executor import RunningHubExecutor

_kit: Optional[ComfyKit] = None
_kit_config: Optional[tuple[str, Optional[str]]] = None
_kit_lock = asyncio.Lock()


async def _get_kit(api_key: str, instance_type: Optional[str]) -> ComfyKit:
    """Get or create a shared ComfyKit instance."""
    global _kit, _kit_config
    async with _kit_lock:
        requested_config = (api_key, instance_type)
        if _kit is None or _kit_config != requested_config:
            config: dict = {"runninghub_api_key": api_key}
            if instance_type:
                config["runninghub_instance_type"] = instance_type
            _kit = ComfyKit(**config)
            _kit_config = requested_config
        return _kit


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
    executor = RunningHubExecutor(api_key=api_key, instance_type=instance_type)
    params = {
        "videoimage": str(image_path),
        "audio": str(audio_path),
    }

    try:
        workflow_json = await executor.client.get_workflow_json(workflow_id)
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
        task_data = await executor.client.create_task(
            workflow_id,
            node_info_list if node_info_list else None,
        )
        runninghub_task_id = task_data.get("taskId")
        if not runninghub_task_id:
            raise RuntimeError("RunningHub did not return a task id")

        return str(runninghub_task_id)
    finally:
        await executor.close()


async def submit_image_to_video(
    image_path: Path,
    prompt: str,
    workflow_id: str,
    api_key: str,
    instance_type: Optional[str] = None,
) -> str:
    """
    Submit image + prompt to a fixed RunningHub image-to-video workflow and return the task id.
    """
    executor = RunningHubExecutor(api_key=api_key, instance_type=instance_type)
    params = {
        "image": str(image_path),
        "prompt": prompt,
    }

    try:
        workflow_json = await executor.client.get_workflow_json(workflow_id)
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
        task_data = await executor.client.create_task(
            workflow_id,
            node_info_list if node_info_list else None,
        )
        runninghub_task_id = task_data.get("taskId")
        if not runninghub_task_id:
            raise RuntimeError("RunningHub did not return a task id")

        return str(runninghub_task_id)
    finally:
        await executor.close()
