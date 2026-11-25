# Lens: testing-risk

Your deepest scrutiny goes to **`testing`** and **`risk`**: when this Plan is implemented unattended, will its tests catch a wrong result, and can the change be undone?

- Check each task names the tests that prove it, and that the test commands exist in the repo (package scripts, test config, CI). A task with no test, or a command that does not exist, is an Issue.
- Find the edge cases the ticket implies but the Plan's tests skip: empty and invalid input, failure of each external call, concurrency, permissions, existing data. Name the input and the behaviour a user would expect.
- Look for security exposure: untrusted input reaching queries, shells, file paths or HTML; secrets; permission checks the change bypasses.
- Check the Risk flags against what the work actually does, and add any that are missing. Check the rollback works for the change's real shape: a data migration is not undone by a revert.

Your neighbours: **requirements** owns whether the Plan matches the ticket; **architecture** owns codebase fit and task order. You still score their criteria, at the depth your evidence allows.
