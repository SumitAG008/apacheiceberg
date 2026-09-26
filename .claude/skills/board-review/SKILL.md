---
name: board-review
description: Convene the leadership board (CFO, CTO, GTM, Strategic Initiatives, chaired by the Chief Strategist) on a strategic question and produce a Proposed decision record for founder sign-off. Use for any "should we…", pivot, pricing, market, build-vs-buy or new-initiative question.
argument-hint: <question or proposal>
---

# Board review

Topic: $ARGUMENTS

If no topic was given, ask for one in a single sentence and stop.

## Steps

1. **Brief (you, the main conversation):** in 3–5 lines, state the decision to be made, the
   deadline, and the relevant existing DEC records, initiatives and risks (grep
   `docs/governance/`). Pass this brief to every agent below.

2. **Parallel assessments:** launch these four subagents in parallel, in one message, each
   with the brief and the topic:
   - `cfo`: cost, ROI, affordability; verdict first.
   - `cto`: feasibility, effort, technical risk, and whether the current code supports it
     (with `file:line`); verdict first.
   - `gtm-lead`: customer demand, positioning fit, claims we could honestly make; verdict first.
   - `strategic-initiatives`: portfolio fit, what it displaces, a proposed time box and kill
     criteria; verdict first.

3. **Synthesis:** launch `chief-strategist` with the brief and all four assessments verbatim.
   It drafts `docs/governance/decisions/DEC-NNNN-<slug>.md` with Status **Proposed** and adds the
   log row.

4. **Governance check:** run `python tools/governance/check_governance.py` and fix any error in the
   new DEC.

5. **Report to the founder:** give the recommendation in one sentence, then a table of the four
   verdicts, any dissent, the one-way or two-way door classification, and the DEC path. Ask for
   Accept, Reject or Revise. Do not mark it Accepted yourself.
