from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx

from q_agent_realtime.config import RuntimeConfig
from q_agent_realtime.llm_roles import create_role_llms
from q_agent_realtime.ollama import OllamaClient, OllamaError
from q_agent_realtime.openai_provider import OpenAILLMClient


class RoleConfigTest(unittest.TestCase):
    def test_defaults_use_openai_api_providers(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = RuntimeConfig.from_env()

        self.assertEqual(config.llm_provider, "openai")
        self.assertEqual(config.stt_provider, "openai")
        self.assertEqual(config.openai_context_model, "gpt-4o-mini")
        self.assertEqual(config.openai_generator_model, "gpt-4o-mini")
        self.assertEqual(config.openai_evaluator_model, "gpt-4o-mini")
        self.assertEqual(config.openai_stt_model, "gpt-4o-mini-transcribe")

    def test_local_models_remain_available_when_selected(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "ollama", "STT_PROVIDER": "local"},
            clear=True,
        ):
            config = RuntimeConfig.from_env()

        self.assertEqual(config.ollama_context_model, "qwen3:4b")
        self.assertEqual(config.ollama_generator_model, "qwen3:8b")
        self.assertEqual(config.ollama_evaluator_model, "qwen3:1.7b")
        self.assertEqual(config.context_interval_seconds, 5)
        self.assertEqual(config.question_interval_seconds, 30)
        self.assertEqual(config.reevaluation_interval_seconds, 60)

    def test_legacy_ollama_model_only_changes_generator(self) -> None:
        with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3:14b"}, clear=True):
            config = RuntimeConfig.from_env()

        self.assertEqual(config.ollama_context_model, "qwen3:4b")
        self.assertEqual(config.ollama_generator_model, "qwen3:14b")
        self.assertEqual(config.ollama_evaluator_model, "qwen3:1.7b")

    def test_factory_creates_independent_role_clients(self) -> None:
        llms = create_role_llms(RuntimeConfig(llm_provider="ollama"))
        try:
            self.assertEqual(
                llms.models(),
                {
                    "context": "qwen3:4b",
                    "generator": "qwen3:8b",
                    "evaluator": "qwen3:1.7b",
                },
            )
            self.assertIsNot(llms.context, llms.evaluator)
            self.assertEqual(llms.context.num_ctx, 4096)
            self.assertEqual(llms.generator.num_ctx, 8192)
        finally:
            asyncio.run(llms.close())

    def test_default_factory_creates_openai_clients(self) -> None:
        llms = create_role_llms(RuntimeConfig(openai_api_key="test-key"))
        try:
            self.assertTrue(
                all(isinstance(client, OpenAILLMClient) for _, client in llms.items())
            )
            self.assertEqual(
                llms.models(),
                {
                    "context": "gpt-4o-mini",
                    "generator": "gpt-4o-mini",
                    "evaluator": "gpt-4o-mini",
                },
            )
        finally:
            asyncio.run(llms.close())


class OllamaRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_preload_and_close_keep_role_model_resident(self) -> None:
        requests: list[dict[str, object]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"done": True})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OllamaClient(
            base_url="http://ollama.test",
            model="qwen3:1.7b",
            role="Question Evaluator",
            client=http,
        )

        await client.preload()
        self.assertTrue(client._preloaded)
        await client.close()

        self.assertEqual(requests[0]["model"], "qwen3:1.7b")
        self.assertEqual(requests[0]["keep_alive"], -1)
        self.assertEqual(requests[1]["keep_alive"], 0)

    async def test_truncated_json_retries_without_thinking(self) -> None:
        requests: list[dict[str, object]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                return httpx.Response(
                    200,
                    json={
                        "message": {"content": '{"answer":'},
                        "done_reason": "length",
                    },
                )
            return httpx.Response(
                200,
                json={"message": {"content": '{"answer":"ok"}'}, "done": True},
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OllamaClient(
            base_url="http://ollama.test",
            model="qwen3:4b",
            role="Context Agent",
            client=http,
        )
        try:
            result = await client.chat_json(
                system="system",
                user="user",
                schema={"type": "object"},
                think=True,
                temperature=0.5,
                num_predict=100,
            )
        finally:
            await client.close()

        self.assertEqual(result, {"answer": "ok"})
        self.assertEqual(len(requests), 2)
        self.assertFalse(requests[1]["think"])
        self.assertEqual(requests[1]["options"]["temperature"], 0)
        self.assertGreaterEqual(requests[1]["options"]["num_predict"], 4096)

    async def test_error_names_the_failed_role(self) -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"message": {"content": "not-json"}, "done": True},
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OllamaClient(
            base_url="http://ollama.test",
            model="qwen3:4b",
            role="Question Evaluator",
            client=http,
        )
        try:
            with self.assertRaisesRegex(OllamaError, "Question Evaluator"):
                await client.chat_json(
                    system="system",
                    user="user",
                    schema={"type": "object"},
                    think=False,
                    temperature=0,
                    num_predict=100,
                )
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
