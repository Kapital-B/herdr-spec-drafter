List my Linear issues with the Linear tools. Read only: do not change anything in Linear.

Include an issue only if all of these hold:
- it is assigned to me ("me");
- its status is one of: {{statuses}};
- in the current (active) cycle of its team: {{current_cycle_only}};
- team: {{team_keys}}.

Reply with only a JSON array, no prose and no code fence. One object per issue:

[{"identifier": "ENG-123", "title": "...", "url": "https://linear.app/...", "priority": 2,
  "sortOrder": 0, "updatedAt": "2026-01-01T00:00:00.000Z", "branchName": "...",
  "state": "Todo", "team": "ENG"}]

priority is Linear's number (0 none, 1 urgent, 2 high, 3 medium, 4 low). Use 0, "" or null
for anything the tools don't give you. If there are no matching issues, reply [].
