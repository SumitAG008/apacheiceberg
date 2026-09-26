---
name: decide
description: Record a decision the founder has made (or accept/reject a Proposed one) as a DEC record in docs/governance/decisions/ and the decision log. Use whenever a direction, scope, pricing, architecture or initiative decision is made in conversation.
argument-hint: <decision> | accept DEC-NNNN | reject DEC-NNNN
---

# Record a decision

Input: $ARGUMENTS

## If the input is `accept DEC-NNNN` or `reject DEC-NNNN`
Set that record's Status to Accepted or Rejected, update its row in
`docs/governance/DECISION_LOG.md`, and append a line under "## Decision" noting the date and that
the founder confirmed it in this conversation. Then go to the final step.

## Otherwise (a new decision)
1. Find the next free number: the highest `DEC-NNNN` in `docs/governance/decisions/` plus 1.
2. Copy `docs/governance/decisions/DEC-0000-template.md` to `DEC-NNNN-<kebab-slug>.md` and fill in
   every field from the conversation:
   - Context, with evidence cited (files, commits, test results, sources).
   - At least two options plus "do nothing".
   - The decision, consequences, measurable success or kill criteria, and a review date
     (default: 30 days out).
   - Assumptions labelled **ASSUMPTION**.
   Status is **Accepted** only if the founder stated the decision explicitly in this conversation;
   otherwise **Proposed**.
3. If the decision supersedes an earlier one, set the old record's status to "Superseded by
   DEC-NNNN" (the only edit ever made to a past record) and update both log rows.
4. Add the row to `DECISION_LOG.md`.
5. If it changes scope or sequencing, run the `project-planner` agent to update `PROJECT_PLAN.md`.

## Final step
Run `python tools/governance/check_governance.py`, fix any errors, and reply with the DEC path and
a one-line summary.
