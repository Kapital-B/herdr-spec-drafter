"""Decide which tickets get a spec agent, and launch them into Herdr."""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import herdr
from .config import fill, slugify
from .linear import Issue, fetch
from .state import State

DISPATCHER_NAME = "spec-dispatcher"


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M"), msg), flush=True)


# ---------------------------------------------------------------- ticket values

def ticket_values(cfg, issue, tab_id=""):
    ticket = issue.identifier
    lower = ticket.lower()
    slug = slugify(issue.title) if issue.title else "spec"
    base = dict(ticket=ticket, ticket_lower=lower, slug=slug)
    if issue.branch_name:
        branch = fill(cfg["branch"], linear_branch=issue.branch_name, **base)
    else:
        branch = fill(cfg["branch_fallback"], **base)
    drafts = str(Path(cfg.path("drafts_dir")) / ticket)
    return dict(
        base,
        title=issue.title or "(read it from Linear)",
        url=issue.url or "(look it up in Linear)",
        branch=branch,
        workspace_root=cfg.path("workspace_root"),
        worktrees_dir=cfg.path("worktrees_dir"),
        worktree_name=fill(cfg["worktree_name"], **base),  # {repo} stays for the agent
        spec_dir=cfg["spec_dir"],
        spec_filename=fill(cfg["spec_filename"], **base),
        ticket_drafts_dir=drafts,
        tab_id=tab_id,
        tab_name=fill(cfg["herdr"]["tab_name"], **base),
        terminal_name=fill(cfg["herdr"]["terminal_name"], **base),
        on_implement=cfg["agent"].get("on_implement") or "",
    )


def render(template, values):
    for k, v in values.items():
        template = template.replace("{{%s}}" % k, str(v))
    return template


def render_settings(cfg, template_text):
    """The permissions profile with {linear}/{notion}/{slack} filled in.

    Rules for a connector set to "" are dropped.
    """
    conns = cfg["connectors"]
    data = json.loads(template_text)
    for kind in ("allow", "ask", "deny"):
        rules = data.get("permissions", {}).get(kind)
        if rules is None:
            continue
        out = []
        for rule in rules:
            names = re.findall(r"\{(\w+)\}", rule)
            if any(not conns.get(n) for n in names):
                continue
            out.append(fill(rule, **conns))
        data["permissions"][kind] = out
    return data


def write_settings(cfg):
    data = render_settings(cfg, Path(cfg.expand(cfg["agent"]["settings"])).read_text())
    path = Path(cfg.path("state_file")).parent / "agent-settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    return str(path)


def agent_argv(cfg, values, instructions, settings_path):
    a = cfg["agent"]
    first = "Draft the spec for %s: %s (%s)" % (values["ticket"], values["title"], values["url"])
    argv = list(a["command"]) + [first,
                                 "--settings", settings_path,
                                 "--name", values["tab_name"],
                                 "--append-system-prompt", instructions]
    dirs = [cfg.path("worktrees_dir"), cfg.path("drafts_dir")] + [cfg.expand(d) for d in a["extra_dirs"]]
    # --add-dir takes several values, so it goes last.
    return argv + ["--add-dir"] + dirs


# ---------------------------------------------------------------- planning

def plan(cfg, state, issues, lookup):
    """Work out what to do this round.

    lookup(name) -> terminal record or None. Returns (launch, ping, open_count):
    launch: issues to start agents for (within the cap); ping: (issue, record)
    pairs whose ticket changed while their agent sat idle.
    """
    open_names, ping = set(), []
    by_id = {i.identifier: i for i in issues}
    for ticket, rec in state.tickets.items():
        t = lookup(rec["terminal"])
        if not (t and t.get("state") == "live"):
            continue
        open_names.add(rec["terminal"])
        issue = by_id.get(ticket)
        if (issue and issue.updated_at and rec.get("updated_at")
                and issue.updated_at > rec["updated_at"]
                and herdr.agent_status(t) in ("idle", "done")):
            ping.append((issue, rec))

    slots = max(0, cfg["max_open_agents"] - len(open_names))
    launch = []
    for issue in issues:
        if len(launch) >= slots:
            break
        if issue.identifier in state.tickets:
            continue
        name = ticket_values(cfg, issue)["terminal_name"]
        t = lookup(name)
        if t and t.get("state") == "live":
            continue  # started by hand; leave it alone
        launch.append(issue)
    return launch, ping, len(open_names)


# ---------------------------------------------------------------- actions

def ensure_space(state):
    if not state.data.get("space_id"):
        state.data["space_id"] = herdr.new_space_id()
        state.save()
    return state.data["space_id"]


def launch(cfg, state, issue, dry_run=False):
    tab_id = herdr.new_tab_id()
    values = ticket_values(cfg, issue, tab_id)
    instructions = render(Path(cfg.expand(cfg["agent"]["prompt"])).read_text(), values)
    if dry_run:
        log("would launch %s (%s) as %s" % (issue.identifier, issue.title, values["terminal_name"]))
        return
    drafts = Path(values["ticket_drafts_dir"])
    drafts.mkdir(parents=True, exist_ok=True)
    (drafts / "instructions.md").write_text(instructions)

    space_id = ensure_space(state)
    rec = herdr.run_in_tab(
        values["terminal_name"], values["workspace_root"], agent_argv(cfg, values, instructions, write_settings(cfg)),
        space_id, tab_id, labels={"spec-drafter.ticket": issue.identifier},
    )
    if not herdr.name_space_and_tab(space_id, cfg["herdr"]["space_name"], tab_id, values["tab_name"]):
        log("could not name the tab for %s (is the Herdr window open?)" % issue.identifier)
    state.tickets[issue.identifier] = {
        "terminal": values["terminal_name"],
        "address": rec.get("address"),
        "tab_id": tab_id,
        "title": issue.title,
        "url": issue.url,
        "updated_at": issue.updated_at,
        "drafts": str(drafts),
        "launched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    state.save()
    log("launched %s -> %s" % (issue.identifier, rec.get("address")))


def ping(state, issue, rec, dry_run=False):
    msg = ("The Linear ticket %s was updated (%s). Re-read it, including new comments and "
           "linked documents. If it answers open questions, update the spec or questions, "
           "then report what changed." % (issue.identifier, issue.updated_at))
    if dry_run:
        log("would tell %s the ticket changed" % rec["terminal"])
        return
    herdr.send(rec["terminal"], msg)
    rec["updated_at"] = issue.updated_at
    state.save()
    log("told %s that %s changed" % (rec["terminal"], issue.identifier))


def run_once(cfg, dry_run=False):
    state = State(cfg.path("state_file"))
    issues = fetch(cfg["linear"], cfg["connectors"]["linear"])
    to_launch, to_ping, open_count = plan(cfg, state, issues, herdr.get)
    log("%d matching issues, %d agents open (cap %d), launching %d"
        % (len(issues), open_count, cfg["max_open_agents"], len(to_launch)))
    for issue, rec in to_ping:
        try:
            ping(state, issue, rec, dry_run)
        except herdr.HerdrError as e:
            log("could not ping %s: %s" % (rec["terminal"], e))
    for issue in to_launch:
        try:
            launch(cfg, state, issue, dry_run)
        except herdr.HerdrError as e:
            log("could not launch %s: %s" % (issue.identifier, e))


def launch_one(cfg, ticket, dry_run=False):
    """Launch a specific ticket now, ignoring status/cycle filters and the cap."""
    state = State(cfg.path("state_file"))
    issue = Issue(identifier=ticket.upper(), title="", url="", priority=0, sort_order=0,
                  updated_at="", branch_name="", state="", team="")
    try:
        match = [i for i in fetch(cfg["linear"], cfg["connectors"]["linear"]) if i.identifier == issue.identifier]
        issue = match[0] if match else issue
    except Exception as e:  # the agent can still read the ticket itself
        log("could not look up %s in Linear (%s); launching with the id only" % (ticket, e))
    launch(cfg, state, issue, dry_run)


def loop(cfg):
    minutes = cfg["interval_minutes"]
    log("dispatcher started: every %s min, cap %s, config %s"
        % (minutes, cfg["max_open_agents"], cfg.source or "(defaults)"))
    while True:
        try:
            run_once(cfg)
        except Exception as e:  # keep the loop alive; the error is on screen
            log("round failed: %s" % e)
        time.sleep(minutes * 60)


def start_dispatcher(cfg, script, config_arg=None):
    live, _ = herdr.is_live(DISPATCHER_NAME)
    if live:
        log("dispatcher is already running (%s)" % DISPATCHER_NAME)
        return
    state = State(cfg.path("state_file"))
    space_id = ensure_space(state)
    tab_id = herdr.new_tab_id()
    state.data["dispatcher_tab_id"] = tab_id
    state.save()
    argv = ["python3", script] + (["--config", config_arg] if config_arg else []) + ["loop"]
    rec = herdr.run_in_tab(DISPATCHER_NAME, cfg.path("workspace_root"), argv, space_id, tab_id)
    herdr.name_space_and_tab(space_id, cfg["herdr"]["space_name"], tab_id,
                             cfg["herdr"]["dispatcher_tab_name"])
    log("dispatcher started as %s" % rec.get("address"))


def stop_dispatcher():
    herdr.kill(DISPATCHER_NAME)
    log("dispatcher stopped")


def status(cfg):
    state = State(cfg.path("state_file"))
    if not state.tickets:
        print("No tickets launched yet.")
        return
    for ticket, rec in sorted(state.tickets.items()):
        t = herdr.get(rec["terminal"])
        where = (t or {}).get("state", "gone")
        agent_status = herdr.agent_status(t) or "-"
        result = "-"
        sfile = Path(rec["drafts"]) / "status.json"
        if sfile.exists():
            try:
                result = json.loads(sfile.read_text()).get("result", "-")
            except ValueError:
                result = "unreadable"
        print("%-10s %-8s %-8s %-8s %s" % (ticket, where, agent_status, result, rec.get("title", "")))


def forget(cfg, ticket):
    state = State(cfg.path("state_file"))
    if state.tickets.pop(ticket.upper(), None) is None:
        print("%s is not tracked." % ticket.upper())
        return
    state.save()
    print("Forgot %s; the next round may launch it again." % ticket.upper())
