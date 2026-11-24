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
  - `match`: a Jira key prefix (`PROJ-`), or `github:<owner>/<repo>#` for GitHub Issues.
  - `repo`: absolute path of the project checkout on the runner.
  - `base_branch`: the branch implementation branches start from and PRs target.
  - `upstream.type`: `jira` or `github`, per [trackers.md](trackers.md); `upstream.site` is the Jira site.
  - `policy`: optional project policy override, layered over the owner's.

No matching project, a missing `repo`, or an unknown `upstream.type` stops the run as **Blocked**, naming the reference that failed to match.

## Policy files

The gate's policy layers, each deep-merged over the one before ([gate defaults](../../alves-factory-review/assets/default-policy.json)):

1. the bundled default policy;
2. `~/.factory/policy.json`, when present;
3. the matched project's `policy`, when set.

Pass layers 2 and 3 to `alves-factory-review` as `--policy` files, in that order.
