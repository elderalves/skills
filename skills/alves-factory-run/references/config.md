# Factory config

The owner's factory config lives outside every project repo, in `~/.factory/`. Client repos carry no factory config.

## `~/.factory/projects.json`

Maps an Upstream ticket to the project the factory works in. Example: [projects.example.json](../assets/projects.example.json).

```json
{
  "linear_team": "Alves",
  "projects": [
    {
      "match": "PROJ-",
      "repo": "C:/code/proj",
      "base_branch": "main",
      "upstream": { "type": "jira", "site": "example.atlassian.net" },
      "policy": "~/.factory/policies/proj.json"
    }
  ]
}
```

- `linear_team`: the Factory tracker team whose statuses match [linear-record.md](linear-record.md).
- `projects`: tried in order; the first whose `match` is a prefix of the Upstream reference wins.
  - `match`: a Jira key prefix (`PROJ-`), `github:<owner>/<repo>#` for GitHub Issues, or `linear-project:<Linear project name>` for **Native tickets**. A `linear-project:` entry matches a Factory ticket in that Linear project with no Upstream link; it never matches by prefix.
  - `repo`: absolute path of the project checkout on the runner.
  - `base_branch`: the branch implementation branches start from and PRs target.
  - `upstream.type`: `jira`, `github` or `linear` (Native tickets), per [trackers.md](trackers.md); `upstream.site` is the Jira site.
  - `policy`: optional project policy override, layered over the owner's.
  - `github_account`: optional; the gh account that can reach the repo. See **GitHub account** below.

## GitHub account

A machine may hold several gh accounts, and only some can reach a given repo. Resolve the run's account once, at the start of each run:

```sh
python <run-skill-dir>/scripts/github_account.py <repo> [--account <github_account>]
```

It prints `{"account", "source", "host"}`: `pinned` when `github_account` is set and works, `detected` when found by trying every logged-in account with a read-only `git ls-remote`. Exit 1 (no account reaches the repo, or the pinned one cannot) stops the run **Blocked**, naming the accounts tried. When the account was `detected`, say so in the run's final reply so the owner can pin it.

Use the account **per command**, on every network git or gh command of the run (fetch, push, `gh pr …`):

```sh
GH_TOKEN=$(gh auth token --hostname <host> --user <account>) git push …
```

Never `gh auth switch`: it changes the machine's active account under concurrent runs and the owner's own terminal.

No matching project, a missing `repo`, or an unknown `upstream.type` stops the run as **Blocked**, naming the reference that failed to match.

## Policy files

The gate's policy layers, each deep-merged over the one before ([gate defaults](../../alves-factory-review/assets/default-policy.json)):

1. the bundled default policy;
2. `~/.factory/policy.json`, when present;
3. the matched project's `policy`, when set.

Pass layers 2 and 3 to `alves-factory-review` as `--policy` files, in that order.
