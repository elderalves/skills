# The sweep restarts runs through the triggers, and starts at most one itself

The factory's triggers are webhooks into one runner, so work can fall through: Linear stops redelivering after three tries, a run can die mid-stage and leave a status that says it is still running, and nothing watches a PR after it opens. A scheduled **sweep** catches these from facts `sweep.py` reads: statuses, when each was entered, factory comment headings and PR states. It fixes a stuck run by moving its ticket back to the trigger status (Ready or Plan Approved), so the existing webhook starts the new run with the same claim checks as any other. It restarts a ticket only once in a row, so a run that keeps dying reaches the owner as Blocked instead of looping. When a trigger never fired, the sweep starts that run in its own thread, one per pass, so a backlog drains at the runner's pace instead of all at once. It closes the Factory ticket of a merged PR and only comments on a closed one, since a close can mean the owner replaced the PR.

## Considered Options

- Webhooks on the client repos for PR events: rejected because creating a repo webhook needs admin rights there, and the factory works in repos it does not own (ADR 0001).
- Launching a new T3 thread for every dropped run: rejected for now because it needs a T3 project id per repo in the config, and a burst of dropped work would start every run at once.
- Marking every stuck run Blocked: rejected because most deaths (the runner sleeping, a transient API error) succeed on a retry, and the owner would restart them by hand.
- `watch_pull_request` per factory PR: rejected because it keeps a thread alive per PR, against "a run never waits"; it remains an option for reacting faster than the sweep's interval.
