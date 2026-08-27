from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.core import uploads


class FakeUpload:
    def __init__(self, payload: bytes, *, filename: str, content_type: str, chunk_size: int = 3):
        self._payload = payload
        self._offset = 0
        self._chunk_size = chunk_size
        self.filename = filename
        self.content_type = content_type
        self.size = None
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self._offset >= len(self._payload):
            return b""
        end = min(self._offset + self._chunk_size, len(self._payload))
        if size >= 0:
            end = min(end, self._offset + size)
        chunk = self._payload[self._offset : end]
        self._offset = end
        return chunk


class UploadLimitTests(unittest.TestCase):
    def test_save_upload_reads_in_bounded_chunks_and_replaces_atomically(self):
        upload = FakeUpload(
            b"abcdefghij",
            filename="sample.png",
            content_type="image/png",
            chunk_size=2,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "sample.png"
            size = asyncio.run(
                uploads.save_upload(
                    upload,
                    destination,
                    allowed_extensions={".png"},
                    allowed_mime_types=uploads.IMAGE_MIME_TYPES,
                    max_size=20,
                    label="图片",
                )
            )

            self.assertEqual(size, 10)
            self.assertEqual(destination.read_bytes(), b"abcdefghij")
            self.assertTrue(upload.read_sizes)
            self.assertTrue(all(size == uploads.UPLOAD_CHUNK_SIZE for size in upload.read_sizes))
            self.assertFalse(destination.with_name(f".{destination.name}.part").exists())

    def test_oversized_upload_cleans_partial_file(self):
        upload = FakeUpload(
            b"abcdefghij",
            filename="sample.wav",
            content_type="audio/wav",
            chunk_size=2,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "sample.wav"
            with self.assertRaises(HTTPException) as context:
                asyncio.run(
                    uploads.save_upload(
                        upload,
                        destination,
                        allowed_extensions={".wav"},
                        allowed_mime_types=uploads.AUDIO_MIME_TYPES,
                        max_size=5,
                        label="音频",
                    )
                )

            self.assertEqual(context.exception.status_code, 422)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(f".{destination.name}.part").exists())

    def test_extension_and_mime_must_match(self):
        extension_upload = FakeUpload(
            b"data",
            filename="sample.exe",
            content_type="application/octet-stream",
        )
        with self.assertRaises(HTTPException):
            uploads.validate_upload(
                extension_upload,
                allowed_extensions={".png"},
                allowed_mime_types=uploads.IMAGE_MIME_TYPES,
                max_size=20,
                label="图片",
            )

        mime_upload = FakeUpload(
            b"data",
            filename="sample.png",
            content_type="audio/wav",
        )
        with self.assertRaises(HTTPException):
            uploads.validate_upload(
                mime_upload,
                allowed_extensions={".png"},
                allowed_mime_types=uploads.IMAGE_MIME_TYPES,
                max_size=20,
                label="图片",
            )

