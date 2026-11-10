# herdr-spec-drafter

Drafts specifications for your Linear tickets in the background, in Claude Code
agents you can see and steer in Herdr.

Every hour, a small dispatcher finds Linear issues that are **assigned to you**, in
the **current cycle**, with status **Backlog** or **Todo**. For each one, up to a
cap (default 12 open at once), it opens a Claude Code agent in its own tab named
after the ticket (`ENG-123`) in a **Specs** space. Each agent:

1. reads the ticket, its comments, linked issues and attached documents (Notion,
   plus anything else Claude can reach);
2. decides whether there's enough detail (`ready`, `partial` or `insufficient`);
3. picks the main repo, creates a worktree in a shared folder on Linear's
   suggested branch, and commits a spec to `docs/specs/`;
4. drafts any questions as a Linear comment for you to review, without posting it;
5. renames its tab (`ENG-123 ✓ spec`, `◐ spec + questions`, `? needs info`) and waits.

Nothing is implemented, pushed or posted until you say so in the agent's tab.
After you review the spec there, ask it to post the questions or to implement.

## Requirements

- Herdr, with `hc` and `herdr-app` on `PATH`
- Claude Code (`claude`) with a Linear MCP server, and optionally Notion and Slack.
  These can be claude.ai connectors or servers you added with `claude mcp add`; see
  `connectors` below.
- Python 3.9+ (standard library only)

## Setup

```sh
./install.sh            # or: ./install.sh /some/bin/dir
```

The installer:
- links `herdr-spec-drafter` into `~/.local/bin` and warns if that isn't on your `PATH`;
- creates `~/.config/herdr-spec-drafter/config.json` from `config.example.json`, if
  you don't have one (edit at least `workspace_root`);
- checks for `python3` 3.9+, `claude`, `hc`, `herdr-app` and `git`, and for a Linear key.

It's safe to re-run, and never overwrites your config or an unrelated file. The
command is a symlink to this repo, so a `git pull` updates it.

**Linear access.** With `"source": "auto"`, it uses a Linear personal API key if
it finds one in `$LINEAR_API_KEY` or `~/.config/herdr-spec-drafter/linear-api-key`.
That's fast and exact. Otherwise it asks `claude -p` (Haiku) to list the issues
through your Linear connector. That needs no key, but is slower (about 20s) and
less predictable.

## Use

```sh
herdr-spec-drafter once --dry-run   # what would launch now
herdr-spec-drafter start            # hourly dispatcher, in a "dispatcher" tab in Specs
herdr-spec-drafter once             # one round now, without waiting for the hour
herdr-spec-drafter launch ENG-123   # one ticket now (ignores filters and cap)
herdr-spec-drafter status           # launched tickets: live?, agent status, result
herdr-spec-drafter issues           # matching issues in launch order
herdr-spec-drafter forget ENG-123   # allow a ticket to be launched again
herdr-spec-drafter stop             # stop the dispatcher; agents keep running
```

**Closing a ticket's tab frees its slot.** A ticket is launched only once. Use
`forget` to run it again. If a ticket changes in Linear while its agent is idle,
the dispatcher tells that agent to re-read it.

## Configuration

Everything is in `~/.config/herdr-spec-drafter/config.json` (or `--config`, or
`$HERDR_SPEC_DRAFTER_CONFIG`). Set only what differs from the defaults in
[`spec_drafter/config.py`](spec_drafter/config.py). Paths may use `~`,
`{workspace_root}` and `{repo_dir}` (this repo).

| Key | Default | Meaning |
| --- | --- | --- |
| `workspace_root` | `~/workspace` | Folder holding your repos; agents start here and pick the main repo |
| `worktrees_dir` | `{workspace_root}/worktrees` | Shared folder for spec worktrees |
| `worktree_name` | `{repo}-{ticket_lower}` | Worktree folder name |
| `branch` / `branch_fallback` | `{linear_branch}` / `{ticket_lower}-{slug}` | Worktree branch |
| `spec_dir` / `spec_filename` | `docs/specs` / `{ticket}-{slug}.md` | Spec location in the main repo |
| `drafts_dir` | `{workspace_root}/.spec-drafts` | Uncommitted output per ticket: `linear-questions.md`, `status.json`, `notes.md`, `instructions.md` |
| `state_file` | `~/.local/state/herdr-spec-drafter/state.json` | Dispatcher bookkeeping |
| `max_open_agents` | `12` | Cap on open spec agents |
| `interval_minutes` | `60` | Time between rounds |
| `connectors.linear` / `.notion` / `.slack` | `mcp__claude_ai_Linear` / `…Notion` / `…Slack` | Tool-name prefix of each MCP server; `""` if you don't have it |
| `linear.source` | `auto` | `api`, `claude` or `auto` |
| `linear.statuses` | `["Backlog", "Todo"]` | Status names to pick up |
| `linear.current_cycle_only` | `true` | Only issues in an active cycle |
| `linear.team_keys` | `[]` | Limit to teams, e.g. `["ENG"]` |
| `herdr.space_name` / `herdr.tab_name` | `Specs` / `{ticket}` | Where agents appear |
| `agent.command` | `claude --model opus --permission-mode auto` | Agent program and flags |
| `agent.prompt` | `prompts/spec-drafter.md` | Agent instructions (`{{placeholders}}`) |
| `agent.settings` | `settings/spec-drafter.settings.json` | Claude permissions profile |
| `agent.extra_dirs` | `[]` | More folders the agent may use |
| `agent.on_implement` | `""` | Extra instruction for when you say "implement", e.g. `"Use the build-feature skill."` |

## Permissions

Agents run unattended, so `settings/spec-drafter.settings.json` allows the reads
they need (code, git, worktree creation, and Linear and Notion read tools). It
puts outward actions behind an **ask** rule: `git push`, PR creation, Linear
comments and issue edits, Notion writes, and Slack messages. If an agent tries one
before you've asked for it, it stops as *blocked* in Herdr and waits for you.

The file is a template. `{linear}`, `{notion}` and `{slack}` are replaced with
your `connectors` prefixes, and rules for a connector set to `""` are dropped.
The result is written to `agent-settings.json` next to the state file on each
launch. The tool names after the prefix are those of the official hosted Linear
and Notion MCP servers. If your server names its tools differently, edit the
template or point `agent.settings` at your own copy.

**Find your prefix:** in Claude Code, run `/mcp`. A server named `linear` has
tools `mcp__linear__…`; a claude.ai connector named "Linear" has tools
`mcp__claude_ai_Linear__…`.

## How it works

The dispatcher is a plain Python script; only the spec work uses agents. It
starts each agent with `hc run --no-parent` and the labels `herdr.space` and
`herdr.tab`, which makes Herdr show it in that space and tab. It then names them
with `herdr-app do space.rename` and `tab.rename`. Ticket instructions are passed
with `--append-system-prompt`, so the "don't implement until asked" rule lasts the
whole session.

## Tests

```sh
python3 -m unittest discover -s tests -t .
```
