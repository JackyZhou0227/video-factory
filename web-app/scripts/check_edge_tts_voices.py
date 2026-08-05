from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "edge_tts_voices.json"
SAMPLES = {"zh": "这是 Edge TTS 音色可用性测试。", "ja": "これは音声合成のテストです。", "ko": "음성 합성 테스트입니다.", "default": "This is an Edge TTS voice availability test."}

def _sample(locale: str) -> str:
    return SAMPLES.get(locale.lower().split("-")[0], SAMPLES["default"])

def _record(raw: dict) -> dict:
    locale = str(raw.get("Locale") or "")
    voice_id = str(raw.get("ShortName") or raw.get("Name") or "")
    friendly = str(raw.get("FriendlyName") or voice_id)
    voice_name = voice_id.rsplit("-", 1)[-1].removesuffix("Neural")
    language_label = friendly.rsplit(" - ", 1)[-1].strip() or locale
    return {"id": voice_id, "name": voice_name or voice_id, "friendly_name": friendly, "gender": str(raw.get("Gender") or "unknown").lower(), "language": locale, "language_label": language_label, "locale": locale, "description": "Edge-TTS online voice", "available": True}

async def _probe(raw: dict, timeout: float) -> tuple[dict, str | None]:
    record = _record(raw)
    try:
        communicator = edge_tts.Communicate(_sample(record["locale"]), record["id"])
        size = 0
        async def consume() -> None:
            nonlocal size
            async for chunk in communicator.stream():
                if chunk.get("type") == "audio":
                    size += len(chunk.get("data") or b"")
        await asyncio.wait_for(consume(), timeout=timeout)
        if size <= 0:
            raise RuntimeError("empty audio stream")
        return record, None
    except Exception as exc:
        return record, str(exc)

async def run(output: Path, timeout: float, concurrency: int) -> int:
    raw_voices = await edge_tts.list_voices()
    available: list[dict] = []
    failures: list[tuple[str, str]] = []
    semaphore = asyncio.Semaphore(concurrency)

    async def probe_limited(raw: dict) -> tuple[dict, str | None]:
        async with semaphore:
            return await _probe(raw, timeout)

    results = await asyncio.gather(*(probe_limited(raw) for raw in raw_voices))
    for index, (voice, error) in enumerate(results, 1):
        if error is None:
            available.append(voice)
        else:
            failures.append((voice["id"], error))
        status = "OK" if error is None else "FAIL"
        print(f"[{index}/{len(raw_voices)}] {status} {voice['id']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"version": 1, "voices": available}, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    print(f"tested={len(raw_voices)} available={len(available)} failed={len(failures)}")
    for voice_id, error in failures:
        print(f"- {voice_id}: {error}")
    print(f"Catalog written to {output}")
    return 0

def main() -> int:
    parser = argparse.ArgumentParser(description="Probe all Edge-TTS voices")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    return asyncio.run(run(args.output, max(1.0, args.timeout), max(1, args.concurrency)))

if __name__ == "__main__":
    sys.exit(main())
