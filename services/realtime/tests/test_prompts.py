from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from q_agent_realtime.prompts import PromptLoadError, PromptTemplates


class PromptTemplatesTest(unittest.TestCase):
    def test_loads_and_renders_markdown_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prompt_dir = Path(directory)
            (prompt_dir / "_shared_v1.md").write_text("공유 규칙", encoding="utf-8")
            (prompt_dir / "context_v1.md").write_text("맥락", encoding="utf-8")
            (prompt_dir / "evaluator_v1.md").write_text(
                "평가 {{STALE_GUIDANCE}}", encoding="utf-8"
            )
            (prompt_dir / "generator_v1.md").write_text(
                "후보 {{GENERATOR_CANDIDATE_COUNT}}개\n{{PURPOSE_GUIDE}}",
                encoding="utf-8",
            )
            (prompt_dir / "purpose_guide_v1.md").write_text(
                "목적 가이드", encoding="utf-8"
            )

            prompts = PromptTemplates.from_directory(
                prompt_dir, generator_candidate_count=8
            )

            self.assertEqual(prompts.context, "맥락")
            self.assertIn("후보 8개", prompts.generator)
            self.assertIn("목적 가이드", prompts.generator)
            self.assertIn("공유 규칙", prompts.generator)
            self.assertIn("question_history", prompts.evaluator)
            self.assertNotIn("{{", prompts.generator)
            self.assertNotIn("{{", prompts.evaluator)

    def test_missing_required_file_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PromptLoadError):
                PromptTemplates.from_directory(Path(directory))


if __name__ == "__main__":
    unittest.main()
