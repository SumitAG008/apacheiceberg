---
name: plan-update
description: Bring PROJECT_PLAN.md up to date after a discussion, decision or batch of work - status verified against tests, change-log entry added, drift between plan and git history reported.
argument-hint: [what changed, optional]
---

# Update the plan

Context from the founder (may be empty): $ARGUMENTS

1. Launch the `project-planner` agent with:
   - the context above plus a summary of what was decided or built in this conversation;
   - the list of DEC records created or changed since the plan's "Last updated" date;
   - an instruction to verify every status change by running its proving test.
2. When it returns, show the founder its status table and the plan diff (`git diff PROJECT_PLAN.md`).
3. If the planner flags a change of scope with no DEC record, offer to run `/decide`.

If `PROJECT_PLAN.md` doesn't exist yet, say so. The plan is being written on branch
`claude/elegant-dijkstra-393jn4` by another session. Don't create a new plan unless the founder asks.
