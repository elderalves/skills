# A factory PR stays a draft until proven safe

Every factory PR opens as a draft, and becomes ready for review only through promotion: by the ready check, on a project whose `pr_ready` is `auto`, or by the owner moving the Factory ticket to Team Review. The factory works in repos it does not own, and a ready PR requests review from a team that does not know the factory exists, so the factory spends that team's attention only on facts a script checked or on the owner's word. The ready check promotes only when every condition holds: a Council approval without Escalation, no Risk flags, CI that ran and passed on the first push, every screenshot captured, and every local check green, even one that already failed on the base branch. The Upstream comment waits for promotion, so the team hears only of ready PRs.

## Considered Options

- Every PR a draft, always: rejected because a low-risk change that passed every check still waits on the owner for a click that adds nothing.
- Ready at creation when the Plan looked safe: rejected because CI can still fail and need fix pushes after the team was already asked to review.
- Letting the implementing agent judge safety: rejected because it would grade its own work; the decision comes from `ready.py`, which is tested like the gate.
- Tunable conditions per project: rejected for now; only the on/off switch is per project, so "ready" means the same thing in every repo.
