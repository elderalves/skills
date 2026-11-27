# Runners keep no state between runs

The owner runs the factory on several machines, and any of them may run any stage of a ticket: triage on one, planning on another, implementation or a sweep on a third. So every file a run writes under `~/.alves-factory/` is scratch for that run alone. Anything a later run, a sweep or a status view needs is written to the record before the run ends: the Factory ticket in Linear, or the PR and branches on GitHub. No code reads a fact another run left on disk. Every factory comment names the Runner that wrote it, so a failure can be traced to its machine. This makes strict what the `software-factory` vocabulary already says of a Runner, and what ADR 0001 says of the record, for the run facts that had been kept only in local work dirs.

## Considered Options

- A third shared store (a synced folder, a factory artifacts repo, S3, a database): rejected because every machine already reaches Linear and GitHub, Linear already carries the triggers, and another store is one more thing to sync, secure and keep consistent. ADR 0001 rejected an artifacts repo for v1; this rejects one for run facts outright.
- Pinning each ticket, or each project, to one machine: rejected because the triggers and the sweep choose where a run starts, and a design that assumes any machine costs nothing if a setup turns out narrower.
