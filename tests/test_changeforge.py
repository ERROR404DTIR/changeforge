import unittest
import changeforge

class ChangeForgeTests(unittest.TestCase):
    def test_parse_scoped_commit(self):
        item = changeforge.parse_commit("feat(api): add pagination")
        self.assertEqual(item["type"], "feat")
        self.assertEqual(item["scope"], "api")
        self.assertEqual(item["description"], "add pagination")

    def test_breaking_footer(self):
        item = changeforge.parse_commit("refactor(core): change contract\n\nBREAKING CHANGE: old API removed")
        self.assertTrue(item["breaking"])

    def test_lint_rejects_bad_header(self):
        self.assertTrue(changeforge.lint_message("added a thing"))

    def test_lint_accepts_valid_header(self):
        self.assertEqual(changeforge.lint_message("fix(parser): handle empty input"), [])

    def test_semver_priority(self):
        commits = [
            {"type": "fix", "breaking": False},
            {"type": "feat", "breaking": False},
        ]
        self.assertEqual(changeforge.next_version("1.2.3", commits), "1.3.0")
        commits.append({"type": "docs", "breaking": True})
        self.assertEqual(changeforge.next_version("1.2.3", commits), "2.0.0")

    def test_changelog_groups(self):
        commits = [{"type":"feat","scope":"cli","description":"add output","sha":"123456789","breaking":False}]
        text = changeforge.render_changelog(commits, "1.0.0")
        self.assertIn("## 1.0.0", text)
        self.assertIn("### Features", text)
        self.assertIn("add output", text)

if __name__ == "__main__":
    unittest.main()
