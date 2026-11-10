import os
import tempfile
import unittest
from pathlib import Path

from spec_drafter.config import Config, DEFAULTS, _merge, fill, slugify
from spec_drafter.dispatcher import agent_argv, plan, render, render_settings, ticket_values
from spec_drafter.linear import Issue, build_filter, parse_claude_result, rank
from spec_drafter.state import State


def issue(ident, priority=3, sort=0.0, updated="2026-11-01T00:00:00Z", title="Fix the thing", branch=""):
    return Issue(ident, title, "https://linear.app/x/" + ident, priority, sort, updated, branch, "Todo", "ENG")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(_merge(DEFAULTS, {
            "workspace_root": self.tmp.name,
            "state_file": os.path.join(self.tmp.name, "state.json"),
            "max_open_agents": 2,
        }))
        self.state = State(self.cfg.path("state_file"))

    def tearDown(self):
        self.tmp.cleanup()


class TestHelpers(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Fix VAT: rounding (UK)!"), "fix-vat-rounding-uk")
        self.assertEqual(slugify("!!!"), "spec")

    def test_fill_leaves_unknown(self):
        self.assertEqual(fill("{repo}-{ticket_lower}", ticket_lower="eng-1"), "{repo}-eng-1")

    def test_rank_priority_none_last(self):
        out = rank([issue("ENG-1", 0), issue("ENG-2", 4), issue("ENG-3", 1, 2.0), issue("ENG-4", 1, 1.0)])
        self.assertEqual([i.identifier for i in out], ["ENG-4", "ENG-3", "ENG-2", "ENG-1"])

    def test_filter(self):
        f = build_filter({"statuses": ["Backlog", "Todo"], "current_cycle_only": True, "team_keys": ["ENG"]})
        self.assertEqual(f["state"]["name"]["in"], ["Backlog", "Todo"])
        self.assertEqual(f["cycle"], {"isActive": {"eq": True}})
        self.assertEqual(f["team"], {"key": {"in": ["ENG"]}})

    def test_parse_claude_result(self):
        out = parse_claude_result('Here:\n```json\n[{"identifier":"ENG-9","priority":2}]\n```')
        self.assertEqual(out[0].identifier, "ENG-9")
        self.assertEqual(out[0].priority, 2)


class TestValues(Base):
    def test_branch_prefers_linear(self):
        v = ticket_values(self.cfg, issue("ENG-123", branch="user/eng-123-fix-the-thing"))
        self.assertEqual(v["branch"], "user/eng-123-fix-the-thing")
        self.assertEqual(v["terminal_name"], "eng-123")
        self.assertEqual(v["spec_filename"], "ENG-123-fix-the-thing.md")
        self.assertEqual(v["worktree_name"], "{repo}-eng-123")

    def test_branch_fallback(self):
        v = ticket_values(self.cfg, issue("ENG-123"))
        self.assertEqual(v["branch"], "eng-123-fix-the-thing")

    def test_prompt_renders_fully(self):
        v = ticket_values(self.cfg, issue("ENG-123"), "tbabc")
        text = render(Path(self.cfg.expand(self.cfg["agent"]["prompt"])).read_text(), v)
        self.assertNotIn("{{", text)
        self.assertIn("tbabc", text)
        self.assertNotIn("ticket-to-pr", text)  # personal hooks live in config, not the prompt

    def test_on_implement_is_rendered(self):
        self.cfg.data["agent"]["on_implement"] = "Use the build-it skill."
        v = ticket_values(self.cfg, issue("ENG-1"), "tb1")
        text = render(Path(self.cfg.expand(self.cfg["agent"]["prompt"])).read_text(), v)
        self.assertIn("Use the build-it skill.", text)

    def test_add_dir_is_last(self):
        v = ticket_values(self.cfg, issue("ENG-1"))
        argv = agent_argv(self.cfg, v, "instructions", "/tmp/s.json")
        i = argv.index("--add-dir")
        self.assertTrue(all(not a.startswith("-") for a in argv[i + 1:]))
        self.assertTrue(argv[len(self.cfg["agent"]["command"])].startswith("Draft the spec for ENG-1"))


class TestSettings(Base):
    TEMPLATE = Path(__file__).resolve().parent.parent / "settings" / "spec-drafter.settings.json"

    def test_fills_prefixes(self):
        self.cfg.data["connectors"] = {"linear": "mcp__linear", "notion": "mcp__notion", "slack": "mcp__slack"}
        perms = render_settings(self.cfg, self.TEMPLATE.read_text())["permissions"]
        self.assertIn("mcp__linear__get_issue", perms["allow"])
        self.assertIn("mcp__linear__save_comment", perms["ask"])
        self.assertIn("Bash(git push:*)", perms["ask"])
        self.assertFalse(any("{" in r for r in perms["allow"] + perms["ask"]))

    def test_drops_missing_connector(self):
        self.cfg.data["connectors"] = {"linear": "mcp__linear", "notion": "", "slack": ""}
        perms = render_settings(self.cfg, self.TEMPLATE.read_text())["permissions"]
        self.assertFalse(any("notion" in r or "slack" in r for r in perms["allow"] + perms["ask"]))
        self.assertIn("mcp__linear__get_issue", perms["allow"])


class TestPlan(Base):
    def test_cap_and_skips(self):
        self.state.tickets["ENG-1"] = {"terminal": "eng-1", "updated_at": "2026-11-01T00:00:00Z"}
        live = {"eng-1": {"state": "live", "status": "working"}}
        launch, ping, open_count = plan(
            self.cfg, self.state, [issue("ENG-1"), issue("ENG-2"), issue("ENG-3")], live.get)
        self.assertEqual(open_count, 1)
        self.assertEqual([i.identifier for i in launch], ["ENG-2"])  # cap 2, one open
        self.assertEqual(ping, [])

    def test_closed_tab_is_not_relaunched_and_frees_slot(self):
        self.state.tickets["ENG-1"] = {"terminal": "eng-1"}
        launch, _, open_count = plan(self.cfg, self.state, [issue("ENG-1"), issue("ENG-2")], {}.get)
        self.assertEqual(open_count, 0)
        self.assertEqual([i.identifier for i in launch], ["ENG-2"])

    def test_manual_terminal_skipped(self):
        live = {"eng-2": {"state": "live", "status": "idle"}}
        launch, _, _ = plan(self.cfg, self.state, [issue("ENG-2"), issue("ENG-3")], live.get)
        self.assertEqual([i.identifier for i in launch], ["ENG-3"])

    def test_ping_only_when_idle_and_newer(self):
        self.state.tickets["ENG-1"] = {"terminal": "eng-1", "updated_at": "2026-11-01T00:00:00Z"}
        newer = issue("ENG-1", updated="2026-11-05T00:00:00Z")
        _, ping, _ = plan(self.cfg, self.state, [newer], {"eng-1": {"state": "live", "status": "done"}}.get)
        self.assertEqual(len(ping), 1)
        _, ping, _ = plan(self.cfg, self.state, [newer], {"eng-1": {"state": "live", "status": "working"}}.get)
        self.assertEqual(ping, [])
        # hc get's real shape: status is an object
        real = {"eng-1": {"state": "live", "status": {"app": "claude-code", "state": "idle"}}}
        _, ping, _ = plan(self.cfg, self.state, [newer], real.get)
        self.assertEqual(len(ping), 1)


class TestConfig(unittest.TestCase):
    def test_load_merges_and_expands(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text('{"workspace_root": "%s", "linear": {"statuses": ["Todo"]}}' % d)
            cfg = Config.load(str(p))
            self.assertEqual(cfg["linear"]["statuses"], ["Todo"])
            self.assertEqual(cfg["linear"]["source"], "auto")  # default kept
            self.assertEqual(cfg.path("worktrees_dir"), os.path.abspath(os.path.join(d, "worktrees")))


if __name__ == "__main__":
    unittest.main()
