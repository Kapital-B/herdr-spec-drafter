"""Configuration: defaults, loading, and path/template expansion."""

import copy
import json
import os
import re
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG_PATH = "~/.config/herdr-spec-drafter/config.json"

DEFAULTS = {
    # Folder that holds your repos. Agents start here so they can pick the main repo.
    "workspace_root": "~/workspace",
    # Shared folder for all spec worktrees.
    "worktrees_dir": "{workspace_root}/worktrees",
    # Per-ticket scratch output that is not committed (questions for Linear, status.json, notes).
    "drafts_dir": "{workspace_root}/.spec-drafts",
    # Dispatcher bookkeeping (which tickets were launched, the Herdr space id).
    "state_file": "~/.local/state/herdr-spec-drafter/state.json",
    # Where the spec goes inside the main repo, and its file name.
    "spec_dir": "docs/specs",
    "spec_filename": "{ticket}-{slug}.md",
    # Worktree folder name inside worktrees_dir.
    "worktree_name": "{repo}-{ticket_lower}",
    # Branch for the worktree. {linear_branch} is Linear's suggested branch name,
    # which makes Linear link the eventual PR to the ticket. Falls back to branch_fallback.
    "branch": "{linear_branch}",
    "branch_fallback": "{ticket_lower}-{slug}",
    # At most this many spec agents open at once. Closing a tab frees a slot.
    "max_open_agents": 12,
    "interval_minutes": 60,
    # Tool-name prefixes of your Linear/Notion/Slack MCP servers in Claude Code.
    # claude.ai connectors look like "mcp__claude_ai_Linear"; a server added with
    # `claude mcp add linear ...` is "mcp__linear". Use "" for one you don't have.
    # Tool names after the prefix assume the official hosted servers.
    "connectors": {
        "linear": "mcp__claude_ai_Linear",
        "notion": "mcp__claude_ai_Notion",
        "slack": "mcp__claude_ai_Slack",
    },
    "linear": {
        # "api" (needs a personal API key), "claude" (asks `claude -p` to use the
        # Linear connector), or "auto" (api when a key is available, else claude).
        "source": "auto",
        "api_key_env": "LINEAR_API_KEY",
        "api_key_file": "~/.config/herdr-spec-drafter/linear-api-key",
        "statuses": ["Backlog", "Todo"],
        "current_cycle_only": True,
        # Limit to these team keys, e.g. ["Y"]. Empty: all teams.
        "team_keys": [],
        "claude_model": "haiku",
    },
    "herdr": {
        "space_name": "Specs",
        "tab_name": "{ticket}",
        "dispatcher_tab_name": "dispatcher",
        # Terminal name in hc (must be a-z 0-9 - _).
        "terminal_name": "{ticket_lower}",
    },
    "agent": {
        "command": ["claude", "--model", "opus", "--permission-mode", "auto"],
        "settings": "{repo_dir}/settings/spec-drafter.settings.json",
        "prompt": "{repo_dir}/prompts/spec-drafter.md",
        # Extra folders the agent may read/write besides workspace_root.
        "extra_dirs": [],
        # Extra instruction for when you ask the agent to implement, e.g. a skill to use.
        "on_implement": "",
    },
}


def _merge(base, override):
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    def __init__(self, data, source=None):
        self.data = data
        self.source = source

    @classmethod
    def load(cls, path=None):
        path = path or os.environ.get("HERDR_SPEC_DRAFTER_CONFIG") or DEFAULT_CONFIG_PATH
        p = Path(os.path.expanduser(path))
        override = {}
        if p.exists():
            override = json.loads(p.read_text())
        override.pop("$comment", None)
        return cls(_merge(DEFAULTS, override), str(p) if p.exists() else None)

    def __getitem__(self, key):
        return self.data[key]

    def path(self, key):
        """A top-level path setting, with {workspace_root}/{repo_dir} and ~ expanded."""
        return expand_path(self.data[key], self)

    def expand(self, value):
        return expand_path(value, self)


def expand_path(value, cfg):
    root = os.path.expanduser(cfg.data["workspace_root"])
    value = value.replace("{workspace_root}", root).replace("{repo_dir}", str(REPO_DIR))
    return os.path.abspath(os.path.expanduser(value))


def slugify(title, max_len=50):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "spec"


def fill(pattern, **values):
    """Fill {placeholders}; unknown ones are left as they are."""
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), pattern)
