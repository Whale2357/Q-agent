from __future__ import annotations

import unittest

from q_agent_realtime.session_gate import SessionGate


class SessionGateTest(unittest.TestCase):
    def test_api_key_optional_when_empty(self) -> None:
        gate = SessionGate(api_key="")
        self.assertFalse(gate.auth_required)
        self.assertTrue(gate.check_api_key(None))

    def test_api_key_required_when_configured(self) -> None:
        gate = SessionGate(api_key="secret")
        self.assertTrue(gate.auth_required)
        self.assertFalse(gate.check_api_key(None))
        self.assertFalse(gate.check_api_key("Bearer wrong"))
        self.assertTrue(gate.check_api_key("Bearer secret"))

    def test_ticket_is_single_use(self) -> None:
        gate = SessionGate()
        ticket = gate.issue_ticket()
        self.assertIsNotNone(gate.consume_ticket(ticket.token))
        self.assertIsNone(gate.consume_ticket(ticket.token))

    def test_audio_slot_limit(self) -> None:
        gate = SessionGate(max_audio_sessions=1)
        self.assertTrue(gate.try_acquire_audio_slot())
        self.assertFalse(gate.try_acquire_audio_slot())
        gate.release_audio_slot()
        self.assertTrue(gate.try_acquire_audio_slot())


if __name__ == "__main__":
    unittest.main()
