"""Consumer checks for the pinned skills' explicit prompt routes."""

import re
import unittest
from pathlib import Path


class KernelBenderConsumerTest(unittest.TestCase):
    def test_basic_prompt_routes_to_initialized_skill_entry(self):
        self.check_skill("skills/KernelBender/skills/kernelbender/SKILL.md", "kernelbender")

    def test_basic_prompt_routes_to_kernelwiki(self):
        self.check_skill("skills/KernelWiki/SKILL.md", "KernelWiki")

    def test_basic_prompt_routes_to_ncu_report_skill(self):
        self.check_skill("skills/ncu-report-skill/SKILL.md", "ncu-report-skill")

    def check_skill(self, entry, name):
        root = Path(__file__).resolve().parents[1]
        prompt = (root / "prompts/basic-flow.md").read_text(encoding="utf-8")
        match = re.search(r"`(" + re.escape(entry) + r")`", prompt)
        self.assertIsNotNone(match, "basic-flow prompt should expose the skill entry path")

        skill_path = root / match.group(1)
        if not skill_path.is_file():
            self.skipTest(f"optional {name} submodule is not initialized")

        content = skill_path.read_text(encoding="utf-8")
        frontmatter = re.match(r"\A---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        self.assertIsNotNone(frontmatter, "skill entry should have YAML frontmatter")
        self.assertRegex(frontmatter.group(1), r"(?m)^name:\s*" + re.escape(name) + r"\s*$")
        self.assertRegex(frontmatter.group(1), r"(?m)^description:\s*\S")


if __name__ == "__main__":
    unittest.main()
