from __future__ import annotations

import asyncio
import copy
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
from fastapi.testclient import TestClient
from q_agent_realtime.config import RuntimeConfig
from q_agent_realtime.audio import UtteranceDetector
from q_agent_realtime.domain import DISCUSSION_KEYS, QuestionStatus
from q_agent_realtime.session_gate import SessionGate
from test_quality_regressions import candidate, scores

# Module import must not touch the developer's meeting database or credentials.
_import_directory = tempfile.TemporaryDirectory()
with patch.dict(os.environ, {"REALTIME_DB_PATH": str(Path(_import_directory.name) / "import.db"), "OPENAI_API_KEY": ""}):
    server = importlib.import_module("q_agent_realtime.server")
_import_runtime = server.runtime


def tearDownModule():
    asyncio.run(_import_runtime.close())
    _import_directory.cleanup()


class FakeDetector:
    def __init__(self, **kwargs):
        self.active = False
        self.frames = []

    def push(self, frame):
        self.frames.append(frame.copy())
        return None


class AudioDependencyTests(unittest.TestCase):
    def test_packaged_cpu_vad_can_process_silence_without_network(self):
        detector = UtteranceDetector()
        self.assertIsNone(detector.push(np.zeros(512, dtype=np.float32)))
        self.assertFalse(detector.active)


class ServerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = server.RealtimeRuntime(RuntimeConfig(database_path=Path(self.directory.name) / "test.db", api_key="test-secret"))
        self.runtime.ensure_ready = AsyncMock()
        self.runtime_patch = patch.object(server, "runtime", self.runtime)
        self.runtime_patch.start()
        self.client = TestClient(server.app)

    def tearDown(self):
        self.client.close()
        self.runtime_patch.stop()
        asyncio.run(self.runtime.close())
        self.directory.cleanup()

    def ticket(self):
        return self.client.post("/v1/session", headers={"Authorization": "Bearer test-secret"}).json()["token"]

    def test_http_auth_and_validation(self):
        self.assertEqual(self.client.post("/v1/session").status_code, 401)
        response = self.client.post("/v1/text", headers={"Authorization": "Bearer test-secret"}, json={"text": "a" * 100001})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.post("/v1/text", content=b"x" * (512 * 1024 + 1)).status_code, 413)

    def test_pending_tickets_and_text_requests_are_bounded(self):
        gate = SessionGate(max_pending_tickets=1, max_text_sessions=1)
        ticket = gate.issue_ticket()
        with self.assertRaises(ValueError):
            gate.issue_ticket()
        self.assertIsNone(gate.consume_ticket({"token": ticket.token}))
        self.assertTrue(gate.try_acquire_text_slot())
        self.assertFalse(gate.try_acquire_text_slot())
        gate.release_text_slot()
        self.assertTrue(gate.try_acquire_text_slot())

    def test_malformed_websocket_payload_is_handled(self):
        for payload in [[], 42, {"type": "unknown"}]:
            with self.client.websocket_connect("/v1/realtime") as ws:
                ws.send_json(payload)
                self.assertEqual(ws.receive_json()["type"], "error")

    def test_ticket_is_single_use_on_websocket(self):
        token = self.ticket()
        with patch.object(server, "UtteranceDetector", FakeDetector):
            with self.client.websocket_connect("/v1/realtime") as ws:
                ws.send_json({"type": "start", "sample_rate": 16000, "session_token": token})
                self.assertEqual(ws.receive_json()["type"], "status")
                self.assertEqual(ws.receive_json()["type"], "ready")
                ws.send_bytes(np.zeros(600, dtype="<f4").tobytes())
                ws.send_json({"type": "stop"})
                self.assertEqual(ws.receive_json()["type"], "stopped")
        self.assertEqual(self.runtime.session_gate.active_audio_sessions, 0)
        with self.client.websocket_connect("/v1/realtime") as ws:
            ws.send_json({"type": "start", "sample_rate": 16000, "session_token": token})
            self.assertEqual(ws.receive_json()["type"], "error")

    def test_text_pipeline_end_to_end_with_mock_models(self):
        discussion = {key: [] for key in DISCUSSION_KEYS}
        discussion["open_issues"] = [{"content": "QA 완료 기준", "status": "open", "evidence_segment_ids": [1]}]
        self.runtime.llms.context.chat_json = AsyncMock(return_value={
            "global_summary": "QA 기준 논의", "current_topic": "QA", "current_topic_summary": "QA 완료 기준 미정",
            "current_purpose": {"primary": "decision_making", "secondary": [], "confidence": .9},
            "discussion_state": discussion, "askable_focus": [],
        })
        self.runtime.llms.generator.chat_json = AsyncMock(return_value={"meeting_purpose": "decision_making", "candidates": [{
            "text": "QA 완료 여부는 어떤 기준으로 확인할까요?", "category": "essence", "operator": "criterion_clarification",
            "anchor_terms": ["QA"], "evidence_segment_ids": [1], "detected_problem": "QA 기준 미정",
        }]})
        async def evaluate(**kwargs):
            questions = json.loads(kwargs["user"])["questions"]
            return {"evaluations": [scores(question_id=q["question_id"]) for q in questions]}
        self.runtime.llms.evaluator.chat_json = AsyncMock(side_effect=evaluate)
        response = self.client.post("/v1/text", headers={"Authorization": "Bearer test-secret"}, json={"text": "QA 완료 기준이 아직 정해지지 않았습니다."})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["diagnosis"]["questions"]), 1)
        self.assertTrue(self.runtime.session_gate.try_acquire_text_slot())

    def test_slow_ask_does_not_block_audio_or_stop(self):
        async def display(session, *, trigger):
            if trigger == "ask":
                await session.send_event({"type": "ask_started"})
                await asyncio.Event().wait()
            return None
        token = self.ticket()
        with patch.object(server, "UtteranceDetector", FakeDetector), patch.object(server.RealtimeMeetingSession, "display_best_question", display):
            with self.client.websocket_connect("/v1/realtime") as ws:
                ws.send_json({"type": "start", "sample_rate": 16000, "session_token": token})
                self.assertEqual(ws.receive_json()["type"], "status")
                self.assertEqual(ws.receive_json()["type"], "ready")
                ws.send_json({"type": "ask"})
                self.assertEqual(ws.receive_json()["type"], "ask_started")
                ws.send_bytes(np.zeros(512, dtype="<f4").tobytes())
                ws.send_json({"type": "stop"})
                self.assertEqual(ws.receive_json()["type"], "stopped")
        self.assertEqual(self.runtime.session_gate.active_audio_sessions, 0)

    def test_host_port_configuration(self):
        with patch.dict(os.environ, {"PORT": "9090", "REALTIME_PORT": "8765"}):
            self.assertEqual(server.build_parser().parse_args([]).port, 9090)


class SessionRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = server.RealtimeRuntime(RuntimeConfig(database_path=Path(self.directory.name) / "test.db"))
        self.session = server.RealtimeMeetingSession(self.runtime, AsyncMock(), audio=False)

    async def asyncTearDown(self):
        await self.session.close()
        await self.runtime.close()
        self.directory.cleanup()

    async def test_stale_evaluation_cannot_be_persisted(self):
        self.session.state.version = 1
        snapshot = copy.deepcopy(self.session.state)
        q = candidate(self.session.meeting_id, status=QuestionStatus.ELIGIBLE)
        async def evaluate(*args, **kwargs):
            self.session.state.version = 2
            return [q]
        self.session.question_evaluator.evaluate = AsyncMock(side_effect=evaluate)
        await self.session._evaluate_batch(server.CandidateBatch(snapshot, [q]))
        self.assertIsNone(self.runtime.repository.best_eligible_question(self.session.meeting_id))

    async def test_pcm_validation_and_final_partial_block(self):
        self.session.audio = True
        self.session.detector = FakeDetector()
        for payload in [b"abc", np.array([np.nan], dtype="<f4").tobytes(), b"0" * (256 * 1024 + 4)]:
            with self.assertRaises(ValueError):
                await self.session.feed_pcm(payload)
        await self.session.feed_pcm(np.full(100, .5, dtype="<f4").tobytes())
        self.assertEqual(len(self.session.detector.frames), 0)
        await self.session.flush_audio()
        np.testing.assert_equal(self.session.detector.frames[0][:100], .5)

    async def test_backpressure_preserves_oldest_utterance(self):
        self.session._utterance_queue = asyncio.Queue(maxsize=1)
        first = server.AudioUtterance(np.zeros(2), 0, 1)
        second = server.AudioUtterance(np.zeros(2), 1, 2)
        await self.session._enqueue_utterance(first)
        queued = asyncio.create_task(self.session._enqueue_utterance(second))
        await asyncio.sleep(0)
        self.assertFalse(queued.done())
        self.assertIs(self.session._utterance_queue.get_nowait(), first)
        self.session._utterance_queue.task_done()
        await queued
        self.assertIs(self.session._utterance_queue.get_nowait(), second)
        self.session._utterance_queue.task_done()


class ConfigValidationTests(unittest.TestCase):
    def test_invalid_limits_fail_on_startup(self):
        for values in [{"max_audio_sessions": 0}, {"question_interval_seconds": float("nan")}, {"llm_provider": "typo"}]:
            with self.assertRaises(ValueError):
                RuntimeConfig(**values)
