# Each repo pins its GitHub account in its git config

A machine holds several `gh` accounts (`elderalves`, `elderalves-gridx`, `Michael-Alves_fust`), and only some can reach a given repo. The factory's skills already handle this per command: `github_account.py` resolves the entry's `github_account`, and every network `git` or `gh` call of a run carries `GH_TOKEN=$(gh auth token --user <account>)`. That covers everything a skill runs, but not what T3 runs before the skill starts. A worktree task (A, B, D) prepares its worktree with a plain `git fetch`, which goes through the global helper `gh auth git-credential`, and that helper only gives out the **active** account's token: asked for any other user, it returns nothing. So every repo whose account is not the active one failed at "Workspace preparation failed … Git could not authenticate with the remote" before a skill could run: AgileKit (`Michael-Alves_fust`) on the Windows runner, and the GridX repos (`elderalves-gridx`) in waiting.

So each repo **pins its account** in its own git config. `github_account.py <repo> --account <account> --pin` writes an empty `credential.https://<host>.helper`, which resets the global helpers, then a helper that prints `gh auth token --hostname <host> --user <account>` (the absolute path of `gh`, quoted), and the mark `alves-factory.githubaccount=<account>`. Then it proves a plain `git ls-remote origin` works with no token in the environment. Worktrees share the repo's config, so the pin covers T3's fetch and every git command after it. `gh auth token --user` reads the keyring and ignores `GH_TOKEN`, so the pin holds in any shell.

The **sweep** keeps the pins: each pass checks every entry's repo and emits a `pin_account` action when the pin is missing or names another account, which `apply` writes. A new clone, a re-clone or a changed `github_account` is fixed within one pass without anyone remembering to do it. The sweep itself runs in the `alves-factory` project with no worktree ([ADR 0007](0007-triage-chooses-the-repo.md)), so it never depends on the pin it repairs.

## Considered Options

- A username in the remote URL (`https://<account>@github.com/…`): rejected because `gh auth git-credential` ignores the requested username and returns nothing for an account that is not active.
- An SSH host alias for each account, with the remote rewritten to `git@github-<account>:…`: rejected because it needs SSH keys per account on every runner, and the factory's `gh` calls would still need the token.
- `gh auth switch` before each run: rejected, as already for runs ([config.md](../../../skills/alves-factory-run/references/config.md#github-account)), because it changes the machine's active account under concurrent runs and in the owner's own terminal.
- Re-pinning at the start of each planning or implementation run: rejected because those runs start after T3's fetch, so a pin written there only helps the next run, which the sweep already covers.

## Consequences

- The skills keep their per-command `GH_TOKEN`, so a run works with or without the pin; the pin only adds T3's own fetch.
- The pin is a write to the repo's local git config, the only change the sweep makes outside Linear. It never touches a helper without the factory's mark: a repo with the owner's own local helper, or an SSH `origin`, is noted and left alone.
- A repo named by two entries with different `github_account` values is not pinned; the sweep notes the conflict.
- A pin names `gh` by its absolute path on that machine; when `gh` moves, the pin is stale and the next sweep rewrites it.
