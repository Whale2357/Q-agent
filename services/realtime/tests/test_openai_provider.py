from __future__ import annotations

import io
import json
import unittest
import wave

import httpx
import numpy as np

from q_agent_realtime.openai_provider import (
    OpenAILLMClient,
    OpenAIProviderError,
    OpenAITranscriber,
    _strict_json_schema,
    _wav_bytes,
)


class StructuredSchemaTest(unittest.TestCase):
    def test_nested_objects_are_closed_and_required(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "meta": {
                    "type": "object",
                    "properties": {"score": {"type": "number"}},
                },
            },
        }

        strict = _strict_json_schema(schema)

        self.assertEqual(strict["required"], ["answer", "meta"])
        self.assertFalse(strict["additionalProperties"])
        self.assertEqual(strict["properties"]["meta"]["required"], ["score"])
        self.assertFalse(strict["properties"]["meta"]["additionalProperties"])
        self.assertNotIn("required", schema)

    def test_pcm_is_encoded_as_16khz_mono_wav(self) -> None:
        content = _wav_bytes(np.array([-1.0, 0.0, 1.0], dtype=np.float32), 16_000)
        with wave.open(io.BytesIO(content), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 16_000)
            self.assertEqual(wav.getnframes(), 3)


class OpenAIClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_responses_request_uses_structured_outputs(self) -> None:
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"id": "gpt-4o-mini"})
            captured["authorization"] = request.headers.get("Authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '{"answer":"ok"}',
                                }
                            ],
                        }
                    ]
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OpenAILLMClient(
            api_key="test-key",
            model="gpt-4o-mini",
            base_url="https://api.test/v1",
            client=http,
        )
        try:
            await client.ensure_ready()
            result = await client.chat_json(
                system="system",
                user="user",
                schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
                think=False,
                temperature=0.1,
                num_predict=100,
            )
        finally:
            await client.close()

        self.assertEqual(result, {"answer": "ok"})
        self.assertEqual(captured["authorization"], "Bearer test-key")
        body = captured["body"]
        assert isinstance(body, dict)
        self.assertFalse(body["store"])
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertFalse(
            body["text"]["format"]["schema"]["additionalProperties"]
        )

    async def test_missing_key_fails_without_network(self) -> None:
        client = OpenAILLMClient(api_key="", model="gpt-4o-mini")
        try:
            with self.assertRaisesRegex(OpenAIProviderError, "OPENAI_API_KEY"):
                await client.ensure_ready()
        finally:
            await client.close()

    async def test_audio_is_sent_to_transcription_endpoint(self) -> None:
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"id": "gpt-4o-mini-transcribe"})
            captured["path"] = request.url.path
            captured["content_type"] = request.headers.get("Content-Type")
            content = await request.aread()
            captured["contains_wav"] = b"RIFF" in content and b"WAVE" in content
            captured["contains_model"] = b"gpt-4o-mini-transcribe" in content
            return httpx.Response(200, json={"text": "회의 내용입니다."})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        transcriber = OpenAITranscriber(
            api_key="test-key",
            model="gpt-4o-mini-transcribe",
            base_url="https://api.test/v1",
            client=http,
        )
        try:
            await transcriber.ensure_ready()
            result = await transcriber.transcribe(
                np.zeros(16_000, dtype=np.float32)
            )
        finally:
            await transcriber.close()

        self.assertEqual(result.text, "회의 내용입니다.")
        self.assertEqual(captured["path"], "/v1/audio/transcriptions")
        self.assertIn("multipart/form-data", str(captured["content_type"]))
        self.assertTrue(captured["contains_wav"])
        self.assertTrue(captured["contains_model"])


if __name__ == "__main__":
    unittest.main()
