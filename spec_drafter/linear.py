"""Fetch the issues to draft specs for: assigned to me, current cycle, chosen statuses."""

import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import REPO_DIR

API_URL = "https://api.linear.app/graphql"

QUERY = """
query($filter: IssueFilter, $after: String) {
  viewer {
    assignedIssues(first: 100, after: $after, filter: $filter) {
      nodes {
        identifier title url priority sortOrder updatedAt branchName
        state { name }
        team { key }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


@dataclass
class Issue:
    identifier: str
    title: str
    url: str
    priority: int  # Linear: 0 none, 1 urgent ... 4 low
    sort_order: float
    updated_at: str
    branch_name: str
    state: str
    team: str


def rank(issues):
    """Most important first: priority (none last), then the manual order in Linear."""
    return sorted(issues, key=lambda i: (i.priority or 5, i.sort_order, i.identifier))


def build_filter(lcfg):
    f = {"state": {"name": {"in": lcfg["statuses"]}}}
    if lcfg.get("current_cycle_only"):
        f["cycle"] = {"isActive": {"eq": True}}
    if lcfg.get("team_keys"):
        f["team"] = {"key": {"in": lcfg["team_keys"]}}
    return f


def api_key(lcfg):
    key = os.environ.get(lcfg.get("api_key_env") or "LINEAR_API_KEY")
    if key:
        return key.strip()
    path = lcfg.get("api_key_file")
    if path:
        p = Path(os.path.expanduser(path))
        if p.exists():
            return p.read_text().strip()
    return None


def fetch(lcfg, connector=""):
    lcfg = dict(lcfg, _connector=connector)
    source = lcfg.get("source", "auto")
    if source == "api" or (source == "auto" and api_key(lcfg)):
        return rank(fetch_api(lcfg))
    if source in ("claude", "auto"):
        return rank(fetch_claude(lcfg))
    raise ValueError("linear.source must be api, claude or auto, not %r" % source)


def fetch_api(lcfg):
    key = api_key(lcfg)
    if not key:
        raise RuntimeError(
            "No Linear API key: set $%s or write it to %s"
            % (lcfg.get("api_key_env"), lcfg.get("api_key_file"))
        )
    issues, after = [], None
    while True:
        body = json.dumps({"query": QUERY, "variables": {"filter": build_filter(lcfg), "after": after}})
        req = urllib.request.Request(
            API_URL,
            data=body.encode(),
            headers={"Content-Type": "application/json", "Authorization": key},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
        if payload.get("errors"):
            raise RuntimeError("Linear API error: %s" % payload["errors"])
        conn = payload["data"]["viewer"]["assignedIssues"]
        for n in conn["nodes"]:
            issues.append(
                Issue(
                    identifier=n["identifier"],
                    title=n["title"],
                    url=n["url"],
                    priority=n.get("priority") or 0,
                    sort_order=n.get("sortOrder") or 0.0,
                    updated_at=n.get("updatedAt") or "",
                    branch_name=n.get("branchName") or "",
                    state=(n.get("state") or {}).get("name", ""),
                    team=(n.get("team") or {}).get("key", ""),
                )
            )
        if not conn["pageInfo"]["hasNextPage"]:
            return issues
        after = conn["pageInfo"]["endCursor"]


LINEAR_READ_TOOLS = ["list_issues", "list_cycles", "list_teams", "get_issue", "whoami"]


def fetch_claude(lcfg):
    """Ask a one-shot Claude to list the issues through the Linear connector."""
    prefix = lcfg.get("_connector")
    if not prefix:
        raise RuntimeError("No Linear connector configured (connectors.linear) and no API key")
    prompt = (REPO_DIR / "prompts" / "linear-query.md").read_text()
    prompt = (
        prompt.replace("{{statuses}}", ", ".join(lcfg["statuses"]))
        .replace("{{current_cycle_only}}", "yes" if lcfg.get("current_cycle_only") else "no")
        .replace("{{team_keys}}", ", ".join(lcfg.get("team_keys") or []) or "any team")
    )
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", lcfg.get("claude_model") or "haiku",
        "--permission-mode", "dontAsk",
        "--allowedTools", ",".join("%s__%s" % (prefix, t) for t in LINEAR_READ_TOOLS),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError("claude -p failed (%s): %s" % (out.returncode, out.stderr[-2000:]))
    result = json.loads(out.stdout).get("result", "")
    return parse_claude_result(result)


def parse_claude_result(text):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise RuntimeError("claude did not return a JSON list: %s" % text[-1000:])
    rows = json.loads(m.group(0))
    return [
        Issue(
            identifier=r["identifier"],
            title=r.get("title", ""),
            url=r.get("url", ""),
            priority=int(r.get("priority") or 0),
            sort_order=float(r.get("sortOrder") or 0.0),
            updated_at=r.get("updatedAt") or "",
            branch_name=r.get("branchName") or "",
            state=r.get("state", ""),
            team=r.get("team", ""),
        )
        for r in rows
    ]
