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
      "linear_project": "Proj",
      "policy": "~/.factory/policies/proj.json"
    }
  ]
}
```

- `linear_team`: the Factory tracker team whose statuses match [linear-record.md](linear-record.md).
- `council`: optional shared Council seats for every project. See **Council targets** below.
- `councils`: optional named Councils that project entries refer to by name. See **Council targets** below.
- `projects`: tried in order; the first whose `match` is a prefix of the Upstream reference wins.
  - `match`: a Jira key prefix (`PROJ-`), `github:<owner>/<repo>#` for GitHub Issues, or `linear-project:<Linear project name>` for **Native tickets**. A `linear-project:` entry matches a Factory ticket in that Linear project with no Upstream link; it never matches by prefix.
  - `repo`: absolute path of the project checkout on the runner.
  - `base_branch`: the branch implementation branches start from and PRs target.
  - `upstream.type`: `jira`, `github` or `linear` (Native tickets), per [trackers.md](trackers.md); `upstream.site` is the Jira site, which `acli` must be signed in to.
  - `linear_project`: the Linear project the factory files this entry's Factory tickets in (`linear.py create --project`), so per-project T3 triggers see them. Native entries leave it out: their `match` names the project.
  - `policy`: optional project policy override, layered over the owner's.
  - `github_account`: optional; the gh account that can reach the repo. See **GitHub account** below.
  - `pr_ready`: optional; `draft` (the default) leaves every PR a draft until the owner promotes it, and `auto` lets the implementation run promote it when the ready check passes ([ready-check.md](../../alves-factory-implement/references/ready-check.md)). Only this switch is per project: the ready check's conditions are fixed.
  - `council`: optional; this project's Council seats, as the name of an entry in `councils` or an inline object.

## Council targets

Each Council has three lenses: `requirements`, `architecture` and `testing-risk`. Each lens has a **seat**: the T3 connection and the exact model that review it. Seats resolve in this order, each layer replacing whole lenses and leaving the others as they were:

1. The [bundled default Council](../../alves-factory-review/assets/default-council.json): `gpt-6.2-sol` via `codex` for requirements, `claude-opus-5-5` via `claudeAgent` for architecture, `opencode-go/muse-spark-1.3-contributor` via `opencode` for testing/risk.
2. The top-level `council` in `~/.factory/projects.json`, for every project.
3. The matched project entry's `council`: either the name of an entry in the top-level `councils`, or an inline object.

A named Council lets several entries share one set of seats, such as the three Jira prefixes of one repo. It may set only some lenses; the rest come from the layers below. A name missing from `councils` stops the run Blocked; it never falls back to the default. A seat's options are replaced with it, so a new connection never inherits the previous one's options.

```json
{
  "councils": {
    "metronome": {
      "requirements": { "target": { "providerInstanceId": "claudeAgent", "model": "claude-opus-5-5" } },
      "architecture": { "target": { "providerInstanceId": "claudeAgent", "model": "claude-sonnet-5-5" } },
      "testing-risk": { "target": { "providerInstanceId": "acpRegistry_github_copilot", "model": "claude-opus-5.5" } }
    },
    "agilekit": {
      "testing-risk": {
        "target": { "providerInstanceId": "codex", "model": "gpt-6.1-sol", "options": { "reasoningEffort": "high" } }
      }
    }
  },
  "projects": [
    { "match": "DXPX-", "council": "metronome" },
    { "match": "RTP-", "council": "metronome" },
    { "match": "PCS-", "council": "agilekit" }
  ]
}
```

The example omits unrelated project fields. Metronome seats Opus twice (through Claude and through Copilot) and Sonnet once; AgileKit changes only testing/risk and keeps the default requirements and architecture seats.

| Field | Meaning |
|---|---|
| `target.providerInstanceId` | The T3 connection, such as `codex`, `claudeAgent`, `opencode` or `acpRegistry_github_copilot`. |
| `target.model` | Required. The exact model ID in that connection's catalog. IDs differ between connections: Claude's `claude-opus-5-5` is Copilot's `claude-opus-5.5`. |
| `target.options` | Optional model settings, using that model's T3 option IDs and string or boolean values. When omitted, the reviewer chooses high reasoning with the model's own option ID. `{}` uses provider defaults. |

A seat names nothing else: the old `provider` label is gone, and a config that still has it stops the run Blocked with a message saying so. List a connection's models and option IDs with T3's `orchestrator_capabilities`.

**OpenCode Go:** the bundled Muse seat uses the Go subscription. Keep `providerInstanceId: "opencode"` and the full `model: "opencode-go/muse-spark-1.3-contributor"`; the `opencode-go/` prefix selects Go billing. A model under `opencode/` uses separate credit-based billing. It is allowed, but the resolver prints a `warning:` line on stderr naming the layer and lens that select it.

The resolver snapshots the merged seats for one run and checks them against the policy:

```sh
python <run-skill-dir>/scripts/council.py --project "PROJ-" [--policy <file> ...] --out <work-dir>/council.json
```

`--project` is the exact `match` value of the entry already selected by the run. `--policy` takes the same layers the run passes to the review (see **Policy files**). `--config <file>` overrides the default `~/.factory/projects.json`. Exit `2` identifies an unreadable file, an invalid seat, an unknown Council name, a missing project, or a Council that cannot reach the policy's `min_models`. The resolver validates structure; the review checks each connection, model and option against T3's catalog before dispatch, and an unavailable seat stops the run Blocked.

The run passes `--council <work-dir>/council.json` to every review round. Each round writes the seats with the options actually sent to `round-<N>/council.json`, and the gate checks every review against it. Config edits affect new runs; an active run keeps its snapshot.

These settings choose Council reviewers only. The triage, planning and implementation threads run on the model set on the T3 scheduled task that starts them.

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

### Council fidelity and model floor

The gate checks two things about who reviewed, and neither one selects models:

- **Fidelity**, always on: every review must come from its lens's seat, the same `provider_instance` and `model`. A review from anything else escalates with `council-mismatch`. A seat that cannot run stops the run Blocked; only the owner changes a seat.
- **Model floor**, `min_models`: the minimum number of distinct models among the completed reviews. It defaults to `1`, so the Council you configure decides diversity: Opus/Sonnet/Haiku, Opus/Sonnet/Opus and Opus three times all pass. One model reached through two connections counts once: IDs are compared without their routing prefix (`opencode-go/`), lowercased, with `.` read as `-`. A round below the floor escalates with `too-few-models`, and the resolver stops a run whose seats cannot reach it before any review runs.

`min_reviews` (default `3`) still requires all three reviews. Older decision records may show `too-few-providers` or `single-provider`, from the provider count `min_models` replaced; a policy file that still sets `min_providers` stops the run Blocked.

To keep one model from reviewing every lens of one project, put the floor in a project policy file, such as `~/.factory/policies/metronome.json`, and set that project's `policy` field to its path:

```json
{
  "min_models": 2
}
```

Set it in `~/.factory/policy.json` to apply it to every project; a project file wins over the owner's. Preserve other fields when editing either file. Each `decision.json` includes the effective merged `policy` and the distinct `models`, which explain the applied floor.
