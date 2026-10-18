"""Consumer check for the optional KernelBender skill route."""

import re
import unittest
from pathlib import Path


class KernelBenderConsumerTest(unittest.TestCase):
    def test_basic_prompt_routes_to_initialized_skill_entry(self):
        root = Path(__file__).resolve().parents[1]
        prompt = (root / "prompts/basic-flow.md").read_text(encoding="utf-8")
        match = re.search(r"`(skills/KernelBender/skills/kernelbender/SKILL\.md)`", prompt)
        self.assertIsNotNone(match, "basic-flow prompt should expose the skill entry path")

        skill_path = root / match.group(1)
        if not skill_path.is_file():
            self.skipTest("optional KernelBender submodule is not initialized")

        content = skill_path.read_text(encoding="utf-8")
        frontmatter = re.match(r"\A---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        self.assertIsNotNone(frontmatter, "skill entry should have YAML frontmatter")
        self.assertRegex(frontmatter.group(1), r"(?m)^name:\s*kernelbender\s*$")
        self.assertRegex(frontmatter.group(1), r"(?m)^description:\s*\S")


if __name__ == "__main__":
    unittest.main()
