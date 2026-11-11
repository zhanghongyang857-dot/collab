<!-- collab-templates: large v5 -->
# {{project}}
[← NOW]({{now_path}})

Goal: … | Due: … | Status: Active | Started {{date}}

> The Lead's entry point; members work from their context packs instead. The Lead writes only "▶ Next" and "Status"; flow-marked blocks come from `core/flow.py`. Rules: [protocol.md](protocol.md); log: [log.md](log.md).

## ▶ Next
<one item the Owner can start on right away>

## Status
<≤5 lines; link to details>

## Blockers / Needs your decision
<!-- flow:decisions project view@3 sha=da39a3ee -->
<!-- /flow -->

## Active decisions
<!-- flow:active_decisions project view@3 sha=da39a3ee -->
<!-- /flow -->

## Goals
<!-- flow:goals project view@3 sha=da39a3ee -->
<!-- /flow -->

## Tasks
<!-- flow:tasks project view@3 sha=da39a3ee -->
<!-- /flow -->

## Loading map
<!-- Fixed template block; don't edit -->
| Command | Read |
|---|---|
| continue / start | This file only |
| build plan / change plan G00x | protocol.md "Lead", "Goals and stages" + goal card |
| pick people and dispatch | members.md "Capabilities" + protocol.md "Dispatch"; the dispatch script builds the context pack |
| check on a task or goal | `flow.py next <ID>`, `flow.py context <ID> --to <member> --list` |
| goal acceptance G00x | protocol.md "Review" + goal card + deliverables |
| hold council / close I00x | protocol.md "4. Meetings" + `flow context I00x --to lead` |
| decided / record a decision | protocol.md "Changing decisions" + decisions.md |
| wrap up | protocol.md "Wrap-up checklist" |
| look up history | Search log.md and archive/; read only the matches |
