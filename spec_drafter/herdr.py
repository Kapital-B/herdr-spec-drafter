"""Thin wrappers over the `hc` (herdr-core) and `herdr-app` CLIs."""

import json
import secrets
import time
import subprocess


class HerdrError(RuntimeError):
    pass


def new_space_id():
    return "spa" + secrets.token_hex(16)


def new_tab_id():
    return "tb" + secrets.token_hex(16)


def _run(cmd, check=True):
    out = subprocess.run(cmd, capture_output=True, text=True)
    if check and out.returncode != 0:
        raise HerdrError("%s failed (%s): %s" % (" ".join(cmd[:3]), out.returncode, out.stderr.strip()))
    return out


def get(name):
    """A terminal's record, or None when no terminal has that name/address."""
    out = _run(["hc", "get", name, "--json"], check=False)
    if out.returncode == 3:  # not_found
        return None
    if out.returncode != 0:
        raise HerdrError("hc get %s failed: %s" % (name, out.stderr.strip()))
    return json.loads(out.stdout)


def agent_status(record):
    """An agent's status word (idle, working, done, blocked, error), or None.

    `hc get` reports it as {"app": ..., "state": ...}; older/plain records use a string or null.
    """
    st = (record or {}).get("status")
    if isinstance(st, dict):
        st = st.get("state")
    return st or None


def is_live(name):
    t = get(name)
    return bool(t and t.get("state") == "live"), t


def run_in_tab(name, cwd, argv, space_id, tab_id, labels=None):
    """Start a program in its own terminal, shown in the given Herdr space/tab.

    Ids Herdr doesn't know yet become a new space/tab, so we pick them ourselves.
    No parent: the agent outlives whatever started it.
    """
    cmd = ["hc", "run", "--bg", "--json", "--no-parent", "--no-notify",
           "--name", name, "--cwd", cwd,
           "--label", "herdr.space=" + space_id, "--label", "herdr.tab=" + tab_id]
    for k, v in (labels or {}).items():
        cmd += ["--label", "%s=%s" % (k, v)]
    cmd += ["--"] + list(argv)
    return json.loads(_run(cmd).stdout)


def send(name, text):
    _run(["hc", "send", name, text])


def kill(name):
    _run(["hc", "kill", name], check=False)
    _run(["hc", "rm", name], check=False)


def app_do(command, **args):
    """Run a herdr-app command. Returns False (not raising) when the window isn't reachable."""
    cmd = ["herdr-app", "do", command]
    for k, v in args.items():
        cmd += ["--" + k, v]
    out = _run(cmd, check=False)
    return out.returncode == 0


def _window_names(space_id, tab_id):
    """(space name, tab name) as the window shows them, or None until it has the tab."""
    out = _run(["herdr-app", "ls"], check=False)
    if out.returncode != 0:
        return None
    try:
        spaces = json.loads(out.stdout).get("spaces", [])
    except ValueError:
        return None
    for s in spaces:
        if s.get("id") == space_id:
            for t in s.get("tabs", []):
                if t.get("id") == tab_id:
                    return s.get("name"), t.get("name")
    return None


def name_space_and_tab(space_id, space_name, tab_id, tab_name, timeout=15.0):
    """Name the space and tab once the window has adopted the new terminal.

    Adoption is asynchronous, so a rename sent straight after `hc run` is lost.
    Returns False if the window is closed or never showed the tab.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        names = _window_names(space_id, tab_id)
        if names == (space_name, tab_name):
            return True
        if names is not None:
            app_do("space.rename", id=space_id, name=space_name)
            app_do("tab.rename", id=tab_id, name=tab_name)
        time.sleep(0.5)
    return False
