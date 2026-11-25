# Plan rubric

Every reviewer scores every criterion as an integer from 0 to 100. The gate weights the scores (weights live in the policy, [default-policy.json](../assets/default-policy.json)); reviewers never compute a total.

## Criteria

**`requirements`: requirements completeness**
Every requirement and acceptance criterion in the Upstream ticket maps to a task in the Plan, and the Plan adds no requirement the ticket does not support. Scope matches the ticket: nothing missing, nothing invented.

**`architecture`: architectural correctness**
The approach fits the repo's existing patterns, module boundaries, glossary and ADRs, and is the simplest one that meets the requirements. Alternatives were weighed where the choice was not obvious.

**`grounding`: codebase grounding**
Every file, function, interface, command and convention the Plan relies on exists in the repo as the Plan describes it. Score only what you verified.

**`feasibility`: implementation feasibility**
The tasks are ordered so each builds on finished work, sized so each is independently verifiable, and complete: an implementer unfamiliar with the repo could follow them without inventing missing steps.

**`testing`: testing and acceptance**
Each task names the tests that prove it, every acceptance criterion has a check, and the verification commands exist and fit the repo's test setup.

**`risk`: risk and rollback**
The Plan names what could go wrong and how to undo it, declares every Risk flag the work carries, and its Assumptions are reversible and stated.

## Score bands

| Score | Meaning |
|---|---|
| 95–100 | Nothing to add: an implementer would not need to ask anything. |
| 85–94 | Minor gaps that would not change what gets built. |
| 70–84 | Gaps the implementer would have to resolve themselves. |
| 50–69 | Significant parts missing or wrong. |
| 0–49 | The criterion is unmet or the Plan contradicts the repo or ticket. |

Anchor each score to a band and write one to three sentences of evidence for it in `rationale`. A score below 85 needs at least one major Issue or a Blocker under that criterion.

**Verdict from scores.** Vote `approve` when every criterion scores 85 or more and every Issue is minor; `revise` when any criterion is below 85 or any Issue is major; `escalate` when you raised a Blocker. Leave the weighted total to the gate.
