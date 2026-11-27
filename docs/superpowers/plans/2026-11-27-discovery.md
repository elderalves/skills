# Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily Discovery pass per repo files scored improvement tickets in the owner's Linear Backlog. When the owner approves one by moving it to Ready, the planning run files it upstream once and plans it like any other ticket.

**Architecture:** A new skill `alves-factory-discover` drives one pass. Its scripts are `discovery.py` (prepare, check, score, file) and a default policy. The agent finds the candidates, an independent seat scores them, and the scripts decide what gets filed. `alves-factory-run` gains `upstream.py`, which files a Discovered ticket upstream and also serves Discovery's search of open Upstream tickets. It also gains new `linear.py` verbs and a resolver path from a Linear project to its prefix entry. The planning run calls `upstream.py file` right after it claims a Discovered ticket. Every stage after that is unchanged.

**Tech Stack:** Python 3 stdlib only, `unittest` with fake transports and runners (no network in tests), `acli` for Jira, `gh` for GitHub, and the Linear GraphQL API through `linear.py`.

**Spec:** [docs/factory/specs/2026-11-27-discovery.md](../../factory/specs/2026-11-27-discovery.md); also [ADR 0009](../../factory/adr/0009-approved-discovered-tickets-are-filed-upstream.md) and [the glossary](../../factory/GLOSSARY.md).

## Global Constraints

- Work on a branch `factory/discovery`, never on `master`. Commit subjects follow the repo's style: one plain sentence saying what changes and why (for example, "Let triage choose the repo when one Upstream prefix feeds several"), ending with the attribution line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Python stdlib only. Scripts run under Windows PowerShell 5.1, bash and zsh alike. Any multi-step command ships as a tested script (ADR 0004).
- Every JSON input is read whether it is UTF-8, UTF-8 with a BOM, or UTF-16, using the existing idiom: `data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")`.
- Exit codes follow the existing scripts: `0` ok, `1` API or tool error (`error: …` on stderr), `2` unusable config or arguments.
- A script that reaches GitHub takes `--account` and gets its token itself, by putting `GH_TOKEN` from `gh auth token --user <account>` in the command's environment. Jira goes through `acli`, after checking that `acli jira auth status` names `upstream.site`. On a mismatch it stops and names both sites, and it never switches sites.
- Nothing from the factory goes upstream: no Factory URL, no factory label, no score. The body ends with exactly `_Found by automated analysis._`.
- Discovery writes only to Linear. It never commits, never pushes, and never writes upstream.
- Linear priority values: `2` High, `3` Medium, `4` Low. Discovery never sets `1` (Urgent).
- Default values, copied from the spec: `max_new` 3, `max_open` 10, `max_candidates` 5. Weights: impact 30, engineering 25, reach 15, evidence 15, urgency 15. Bands: High ≥ 70, Medium ≥ 50, Low ≥ 30; below 30 is not filed. Effort is S, M or L. Default issue type `Task`.
- The default Lenses, in order: `architecture`, `testing`, `performance`, `ux-accessibility`, `security`, `maintainability`, `developer-experience`.
- Run each skill's tests with `python -m unittest discover -s skills/<skill>/scripts -p "test_*.py"` from the repo root. All existing tests must still pass.

## Review Focus

1. **The owner deleted the `## Factory notes` heading while editing the description.** The whole description goes upstream, with the closing line added, and nothing fails. (Task 3)
2. **The owner retitles the Factory ticket after the filing intent was posted, and the run dies before linking.** The restarted run searches by the title recorded in the intent, finds the ticket it already created, and never creates a second one. (Task 3)
3. **A title with `"` or `\` in it.** The JQL literal is escaped, and a fuzzy `summary ~` hit only counts on an exact title match with a creation time at or after `Since` (both compared as UTC, whatever timezone Jira uses). (Task 3)
4. **More Discovered tickets in Backlog than `max_open`.** Room is 0, never negative, and the pass stops before looking. (Task 4)
5. **The scorer returns a criterion out of 0–10, a missing criterion, a non-integer, or the wrong seat.** `--check` names each problem, and nothing is scored until the scores are valid. (Task 5)

---

### Task 1: `linear.py` files without an Upstream link, lists every status, links and renames

**Files:**
- Modify: `skills/alves-factory-run/scripts/linear.py` (`ISSUE_FIELDS`, `Linear.create`, new `list_all`, `link`, `update`, `main`)
- Test: `skills/alves-factory-run/scripts/test_linear.py`

**Interfaces:**
- Produces:
  - `Linear.create(team, title, upstream_url=None, upstream_title=None, state=None, description=None, project=None, labels=(), priority=None) -> dict`. With no `upstream_url`, there is no `attachmentLinkURL` call. `labels` are names resolved through `label_id`, and `priority` is an int from 0 to 4.
  - `Linear.list_all(team, project) -> list[dict]`: every issue of the project in any status, oldest first, each as `{id, identifier, url, title, description, state, labels: [name], priority, attachment_urls: [url], comments: [{created_at, author, from_factory, body}]}`.
  - `Linear.link(ref, url, title) -> dict` (the issue after linking).
  - `Linear.update(ref, title=None, description=None) -> dict`.
  - CLI changes:
    - `create`: `--upstream-url` becomes optional; it gains `--label` (repeatable) and `--priority {0,1,2,3,4}`.
    - New verbs: `list-all --team --project`, `link <issue> --url --title`, `update <issue> [--title] [--description-file]`.
  - `ISSUE_FIELDS` gains `priority`.

- [ ] **Step 1: Write the failing tests** in `test_linear.py`, using its existing `Fake` and `issue()` helpers:
  - `test_create_without_upstream_url_attaches_nothing`: `create("Alves", "Add labels", state="Backlog", project="Explore")` makes no call whose query contains `attachmentLinkURL`.
  - `test_create_sends_labels_and_priority`: with `labels=("discovered", "quick-win")` and `priority=2`, the `issueCreate` input has `labelIds == ["l-discovered", "l-quick-win"]` (the fake answers `issueLabels` by name) and `priority == 2`.
  - `test_list_all_has_no_state_filter_and_keeps_canceled`: the query has no `state: { name`. A Canceled node with label `discovered` and an owner comment comes back with `state == "Canceled"`, `labels == ["discovered"]` and `comments[0]["from_factory"] is False`.
  - `test_link_attaches_url_with_title`: `link("ALV-9", "https://x.atlassian.net/browse/RTP-1", "RTP-1")` sends `attachmentLinkURL` with that `url` and `title`.
  - `test_update_sets_only_given_fields`: `update("ALV-9", title="RTP-1: Add labels")` sends an `issueUpdate` input equal to `{"title": "RTP-1: Add labels"}`.
  - `test_cli_create_without_upstream_url`: `main(["create", "--team", "Alves", "--title", "t", "--label", "discovered", "--priority", "3"], linear=fake_linear)` returns `0`.

- [ ] **Step 2: Run them and see them fail**
  Run: `python -m unittest discover -s skills/alves-factory-run/scripts -p "test_linear.py" -v`
  Expected: the six new tests FAIL or ERROR, and the existing ones pass.

- [ ] **Step 3: Implement.** `list_all` reuses `list_issues`' query shape without the `state` filter, and adds `title description priority labels { nodes { name } }` and `comments { nodes { createdAt body user { name } } }`. Keep `list_issues` as it is, since the sweep uses it. `create` calls `label_id(team_id, name)` for each label before `issueCreate`.

- [ ] **Step 4: Run the tests again and see them pass**
  Run: the same command as Step 2. Expected: everything passes.

- [ ] **Step 5: Commit**: "Let linear.py file a ticket with no Upstream link, list every status, link and rename".

### Task 2: A Linear project alone resolves its prefix entry

**Files:**
- Modify: `skills/alves-factory-run/scripts/project.py` (`find`, the module docstring, the `--linear-project` help text)
- Test: `skills/alves-factory-run/scripts/test_project.py`

**Interfaces:**
- Produces: `find(config, linear_project=name)`:
  - returns the Native entry `linear-project:<name>` when there is one;
  - otherwise returns the one non-Native entry whose `linear_project` equals `name` (using `same_name`);
  - with two or more such entries, raises `ProjectError("<n> entries file tickets in Linear project <name>; …")`.

  This is how a Discovered ticket, which has no ref yet, finds its repo.

- [ ] **Step 1: Write the failing tests**:
  - `test_linear_project_alone_finds_prefix_entry`: in a config with an `RTP-` entry whose `linear_project` is "Explore Frontend", `find(config, linear_project="explore frontend")["match"] == "RTP-"`.
  - `test_native_entry_wins_over_prefix_entry`: a Native "X" entry and a prefix entry with `linear_project` "X"; the Native one is returned.
  - `test_two_entries_one_linear_project_refuses`: raises `ProjectError` with the message containing `2 entries`.

- [ ] **Step 2: Run them and see them fail**
  Run: `python -m unittest discover -s skills/alves-factory-run/scripts -p "test_project.py" -v`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement it in the `else` branch of `find`.**

- [ ] **Step 4: Run the tests and see them pass.** Then run the whole `alves-factory-run` suite. Expected: everything passes.

- [ ] **Step 5: Commit**: "Resolve a Discovered ticket's repo from its Linear project alone".

### Task 3: `upstream.py` files a Discovered ticket upstream exactly once

**Files:**
- Create: `skills/alves-factory-run/scripts/upstream.py`
- Create: `skills/alves-factory-run/scripts/test_upstream.py`
- Modify: `skills/alves-factory-run/references/trackers.md` (the opening sentence now lists three touches; add a **Filing a Discovered ticket** section with the operations table below and the ordering from the spec)

**Interfaces:**
- Consumes:
  - Task 1's `Linear.issue`, `comments`, `comment`, `link`, `update`;
  - Task 2's `project.find(config, ref=None, linear_project=…)`;
  - `github_account.run(args, env=None, cwd=None) -> str` as the default runner.
- Produces:
  - `class UpstreamError(Exception)`.
  - `FILING_HEADING = "## Filing upstream"` and `CLOSING_LINE = "_Found by automated analysis._"`.
  - `public_part(description: str) -> str`: the text before the first line that is exactly `## Factory notes`, stripped, then a blank line and `CLOSING_LINE`. A description without that heading is filed whole.
  - `jql_string(text: str) -> str`: a double-quoted JQL literal, with `\` and `"` escaped by a backslash.
  - `class Upstream(entry, account=None, run=github_account.run)`, with these methods:
    - `check_site() -> None`
    - `search_open(text) -> list[{ref, title, url}]`
    - `find_filed(title, since_iso) -> {ref, url} | None`
    - `create(title, body) -> {ref, url}`, which leaves the ticket unassigned
    - `assign_owner(ref) -> None`

    `entry.upstream.type` is `jira` or `github`. Any other type raises `UpstreamError`.
  - `file_discovered(linear, upstream, issue_ref, now_iso) -> {"ref", "url", "reused": bool, "already_linked": bool}`.
  - CLI `python upstream.py file <factory-ticket> --linear-project <p> [--account A] [--config F]`, and `python upstream.py search --linear-project <p> --text <words> [--account A] [--config F]`. Both print JSON.

Commands. Verify the flags with `acli jira workitem create --help`, `… search --help` and `… assign --help` before writing the fixtures, and pin what they print:

| Operation | Jira (`acli`) | GitHub (`gh`, `R` = `owner/repo` from `match`) |
|---|---|---|
| search_open | `jira workitem search --jql 'project = <project_key> AND statusCategory != Done AND text ~ <jql_string(text)> ORDER BY updated DESC' --limit 20 --json` | `issue list --repo R --state open --search <text> --json number,title,url --limit 20` |
| find_filed | `jira workitem search --jql 'reporter = currentUser() AND summary ~ <jql_string(title)> AND created >= "<since date − 1 day, YYYY-MM-DD>"' --limit 50 --json`, then keep exact summary matches whose `created` is ≥ `since` in UTC | `issue list --repo R --author @me --state all --search 'in:title <title>' --json number,title,url,createdAt --limit 50`, with the same filter |
| create | `jira workitem create --project <project_key> --type <issue_type or Task> --summary <title> --description-file <tmp> [--label <labels,…>] --json` | `issue create --repo R --title <title> --body-file <tmp>`, where stdout is the issue URL |
| assign_owner | `jira workitem assign --key <ref> --assignee @me` | `issue edit <n> --repo R --add-assignee @me` |

Refs and URLs:
- Jira: the ref is the key, and the URL is `https://<site>/browse/<key>`.
- GitHub: the ref is `github:<owner>/<repo>#<n>`, and the URL is the one `gh` prints.

`file_discovered` order. The test asserts this order:
1. Read the issue. If an attachment URL starts with the entry's upstream URL root (`https://<site>/browse/` or `https://github.com/<R>/issues/`), return it with `already_linked: true`, and make no other call.
2. Find the latest factory comment containing `FILING_HEADING`, and parse its `- **Title:** …` and `- **Since:** …` lines. If there is none, post `## Filing upstream\n\n- **Title:** <issue title>\n- **Since:** <now_iso>` and use those values.
3. Call `find_filed(intent title, since)`. If nothing is found, call `create(intent title, public_part(issue description))`.
4. Call `linear.link(issue_ref, url, ref)`, then `linear.update(issue_ref, title=f"{ref}: {intent title}")`.
5. Call `upstream.assign_owner(ref)`.

- [ ] **Step 1: Write the failing tests** with a fake runner that records the argv lists and answers by subcommand, and a fake Linear object:
  - `test_public_part_cuts_at_factory_notes`: for `"## Problem\nx\n\n## Factory notes\nscore 80"`, the result is `"## Problem\nx\n\n_Found by automated analysis._"`.
  - `test_public_part_without_heading_files_whole_description` (Review Focus 1).
  - `test_jql_string_escapes_quotes_and_backslashes`: `jql_string('a "b" \\c')` returns `'"a \\"b\\" \\\\c"'`.
  - `test_file_posts_intent_then_creates_unassigned_then_links_then_assigns`: the order of recorded calls is comment, search, create, link, update, assign. The create argv has no assignee flag, and the body file's text ends with `CLOSING_LINE` and has no `linear.app`.
  - `test_file_restart_reuses_ticket_found_by_intent_title` (Review Focus 2): an existing intent with Title `Old title` and the issue retitled `New title`. Search returns `Old title` created after Since. Then there is no create, `reused` is true, and the update title is `RTP-7: Old title`.
  - `test_find_filed_ignores_fuzzy_and_earlier_matches` (Review Focus 3): there are three hits, one with a near-identical summary, one created before `since` by a `-03:00` offset, and one exact. Only the exact one is returned.
  - `test_already_linked_does_nothing_else`.
  - `test_github_ref_and_url_from_create_stdout`: stdout `https://github.com/acme/widgets/issues/12\n` gives ref `github:acme/widgets#12`.
  - `test_jira_site_mismatch_stops_naming_both_sites`.
  - `test_cli_search_prints_matches`: `main(["search", "--linear-project", "Explore Frontend", "--text", "aria label"], …)` prints JSON with a `ref`, and exits `0`.

- [ ] **Step 2: Run them and see them fail**
  Run: `python -m unittest discover -s skills/alves-factory-run/scripts -p "test_upstream.py" -v`. Expected: an ImportError or failures.

- [ ] **Step 3: Implement `upstream.py`.** The body goes to a temp file, so the description never passes through shell quoting. `main` takes `linear=None, run=None` for tests, as `linear.main` does.

- [ ] **Step 4: Run the tests and see them pass.** Then run the whole `alves-factory-run` suite.

- [ ] **Step 5: Document the filing section in `trackers.md`**, linking ADR 0009.

- [ ] **Step 6: Commit**: "File an approved Discovered ticket upstream once, with nothing of the factory on it".

### Task 4: `discovery.py prepare`: settings, Lens, room and scorer seat

**Files:**
- Create: `skills/alves-factory-discover/scripts/discovery.py`
- Create: `skills/alves-factory-discover/scripts/test_discovery.py`
- Create: `skills/alves-factory-discover/assets/default-policy.json`, containing `weights`, `bands` (`{"high": 70, "medium": 50, "low": 30}`), `max_candidates` (5), and `lenses` (the seven defaults)

**Interfaces:**
- Consumes:
  - `project.find`, `project.read_config` (Task 2);
  - `council.resolve(config, match, linear_project=…)`;
  - `gate.model_identity` (imported through `council`'s `sys.path` setup);
  - `Linear.list_all` (Task 1).

  Import these as `sweep.py` does: `RUN_SCRIPTS = Path(__file__).resolve().parents[2] / "alves-factory-run" / "scripts"`, then `sys.path.insert`.
- Produces:
  - `class DiscoveryError(Exception)`.
  - `load_policy(paths: list[Path]) -> dict`: the default, deep-merged with each path in order.
  - `settings(entry: dict, policy: dict) -> {"lenses", "max_new", "max_open", "scorer_target" | None}`. It raises `DiscoveryError` when the entry has no `discovery`, or when `upstream.type` is `jira` or `github` and there is no `upstream.file` (or, for Jira, no `upstream.file.project_key`).
  - `lens_for(day: date, lenses: list[str]) -> str`, which returns `lenses[day.toordinal() % len(lenses)]`.
  - `room(max_new: int, max_open: int, open_backlog: int) -> int`, which returns `max(0, min(max_new, max_open - open_backlog))`.
  - `scorer_seat(config, entry, discoverer_model) -> dict` (a target). It is `entry.discovery.scorer.target` when set, else the resolved Council's `testing-risk` target. When `model_identity` matches `discoverer_model`, it raises `DiscoveryError`, naming both.
  - CLI `prepare --linear-project <p> --discoverer-model <m> --date YYYY-MM-DD --out <dir> [--config F]`:
    - writes `<dir>/tickets.json` (from `list_all`) and `<dir>/prepare.json` = `{match, linear_project, team, lens, room, open_backlog, max_candidates, since, scorer, policy, upstream_type}`, where `since` is `date − 1 day` at the same clock time in ISO;
    - prints `prepare.json`;
    - counts `open_backlog` as tickets in Backlog with label `discovered`;
    - exits `2` on `DiscoveryError` or `ProjectError`, and `1` on `LinearError`.

- [ ] **Step 1: Write the failing tests**:
  - `test_lens_rotates_by_date`: consecutive dates give consecutive Lenses, and a date seven days later gives the same one.
  - `test_room_never_negative` (Review Focus 4): `room(3, 10, 12) == 0`, `room(3, 10, 8) == 2`, `room(3, 10, 0) == 3`.
  - `test_settings_refuses_jira_without_upstream_file`.
  - `test_settings_defaults_caps_and_lenses`: `{"discovery": {}}` on a Native entry gives `max_new` 3, `max_open` 10 and the seven Lenses.
  - `test_scorer_defaults_to_testing_risk_seat`.
  - `test_scorer_same_model_as_discoverer_refuses`: seat `claude-opus-5.5` against discoverer `claude-opus-5-5` raises.
  - `test_prepare_counts_only_discovered_backlog`: the tickets are Backlog/discovered, Backlog/unlabelled and Canceled/discovered, so `open_backlog == 1`.

- [ ] **Step 2: Run them and see them fail**
  Run: `python -m unittest discover -s skills/alves-factory-discover/scripts -p "test_*.py" -v`.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests and see them pass.**

- [ ] **Step 5: Commit**: "Prepare a Discovery pass: Lens by date, room in Backlog, an independent scorer".

### Task 5: `discovery.py check | score | file`: the Value score decides what is filed

**Files:**
- Modify: `skills/alves-factory-discover/scripts/discovery.py`
- Modify: `skills/alves-factory-discover/scripts/test_discovery.py`
- Create: `skills/alves-factory-discover/references/candidate-schema.md`, which documents both schemas below exactly
- Modify: `skills/alves-factory-run/references/linear-record.md`. Add a **Discovered ticket** subsection covering the title without a ref, the description template, the `discovered` and `quick-win` labels, and the priority. In the Statuses table, Canceled becomes "dropped; on a Discovered ticket, rejected, and Discovery reads the owner's comment there as the reason".

**Interfaces:**
- Consumes: `prepare.json` (Task 4) and `Linear.create(..., labels, priority)` (Task 1).
- Inputs in the work dir:
  - `candidates.json`: `[{"id": "c1", "title": str, "problem": str, "why": str, "acceptance_criteria": [str], "evidence": [str], "closest": {"identifier": str | null, "why_different": str}, "regression_of": str | null}]`.
  - `scores/<id>.json`: `{"scores": {"impact": int, "engineering": int, "reach": int, "evidence": int, "urgency": int}, "effort": "S" | "M" | "L", "rationale": {<the same five keys>: str}, "seat": {"providerInstanceId": str, "model": str}}`.
- Produces:
  - `check(work_dir: Path) -> list[str]`, the problems found (empty when all is well).
  - `value_score(scores: dict, weights: dict) -> int`, which returns `round(sum(weights[c] * scores[c] for c in weights) / 10)`.
  - `band(score: int, bands: dict) -> "High" | "Medium" | "Low" | None`.
  - `PRIORITY = {"High": 2, "Medium": 3, "Low": 4}`.
  - `select(candidates, scores_by_id, policy, room) -> list[dict]`: each item is the candidate plus `value_score`, `band`, `effort`, `quick_win`, `breakdown`. Bands of `None` are dropped, the rest sorted by `value_score` descending (ties keep candidate order), and the first `room` kept.
  - `render_description(item) -> str`: `## Problem`, `## Why it matters`, `## Acceptance criteria` (a bullet list), then `## Factory notes`, holding the Lens, Evidence (bullets), the Value score `<n>/100 (<band>)` with a table of criterion, weight, score and rationale, the Effort, and the closest ticket with `why_different`.
  - CLI:
    - `check <work-dir>` prints `ok` or one problem per line, exit `1` on problems;
    - `score <work-dir>` writes `selected.json` and prints it;
    - `file <work-dir> [--dry-run]`, which for each selected item calls `create(team, title, state="Backlog", project=linear_project, description=render_description(item), labels=["discovered"] + (["quick-win"] if quick_win else []), priority=PRIORITY[band])`. It prints `[{identifier, title, value_score, band, effort}]`. A dry run writes `record/NN-ticket.md` instead.

- [ ] **Step 1: Write the failing tests**:
  - `test_check_names_each_bad_score` (Review Focus 5): urgency 11, reach missing, impact `"8"`, effort `"XL"`, and a seat model that differs from `prepare.json`'s scorer. Each of the five problems appears once, naming the candidate id.
  - `test_check_refuses_more_than_max_candidates`.
  - `test_check_requires_closest_why_different`.
  - `test_value_score_uses_weights`: the spec's example scores 9, 8, 7, 9, 8 give `83`.
  - `test_band_edges`: 70 is High, 69 Medium, 50 Medium, 49 Low, 30 Low, 29 `None`.
  - `test_select_drops_below_low_and_keeps_room`: four candidates scoring 92, 81, 38 and 25 with `room=2` give the 92 and 81 ones.
  - `test_quick_win_only_high_and_small`.
  - `test_render_description_public_part_has_no_scores`: the text before `## Factory notes` has no `/100` and no `Effort`.
  - `test_file_sends_labels_priority_and_backlog`: a fake Linear records `create(..., state="Backlog", labels=["discovered", "quick-win"], priority=2)`.

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement.** Write `candidate-schema.md`, then update `linear-record.md`.

- [ ] **Step 4: Run both skills' suites and see them pass.**

- [ ] **Step 5: Commit**: "Score Discovery's candidates with the rubric and file the best as Discovered tickets".

### Task 6: The `alves-factory-discover` skill

**Files:**
- Create: `skills/alves-factory-discover/SKILL.md`
- Create: `skills/alves-factory-discover/references/scorer-brief.md`
- Create: `skills/alves-factory-discover/references/lenses.md`, one short paragraph per default Lens on what to look for and what counts as evidence
- Modify: `skills/alves-factory-run/references/thread-title.md`, adding a Discovery row: start `discover <Linear project> · <lens> …`, end outcomes `filed <n>`, `quiet`, `backlog full`, `failed`

**Interfaces:**
- Consumes: `discovery.py prepare|check|score|file` (Tasks 4 and 5) and `upstream.py search` (Task 3).

`SKILL.md` follows the shape of the sibling skills: frontmatter `name: alves-factory-discover`, a description that triggers on "a factory discovery trigger names a repo's Linear project, or /alves-factory-discover", and `argument-hint: <linear-project> [--dry-run]`. Then Guardrails, Process and **Done when**. The steps, each with its done condition:

1. **Prepare.** Run `discovery.py prepare --linear-project <p> --discoverer-model <the orchestrator's own model id> --date <today> --out ~/.alves-factory/discovery/<project slug>/<date>/`. If `room` is 0, reply `backlog full` and stop.
2. **Look** through the day's Lens, using `lenses.md`, at the repo and at `git log --since=<since> origin/<base_branch>`. Running the repo's build, lint and tests in the worktree is allowed. Commits, pushes and edits to tracked files are not. Gather at most `max_candidates` candidates, each with evidence from the repo.
3. **Not again.** For each candidate, read `tickets.json` and set `closest`. Drop a candidate that matches an open ticket, a Canceled one (and read the owner's comment there as guidance for the others), or a Done one without `regression_of`.
4. **Not tracked upstream.** Skip this for Native entries. Run `upstream.py search --linear-project <p> --text <2–4 key terms>` for each candidate, and drop any candidate that matches an open ticket.
5. **Score.** Write `candidates.json`. For each candidate, start the `prepare.json` scorer seat with `delegate_task`, exactly as the review skill's step 2 starts a seat. Its prompt is `scorer-brief.md`, the candidate's JSON, the repo path, and its output path `scores/<id>.json`. Run `discovery.py check`, and re-dispatch a failing scorer once, quoting the problems. A candidate that fails twice is dropped, with the reason.
6. **Select and file.** Run `discovery.py score`, then `discovery.py file` (passing `--dry-run` through).

Done when every candidate is filed or dropped with a reason. The reply has one line per filed ticket (`<identifier> <band> <value>/100 effort <S|M|L>: <title>`), one per dropped candidate (`dropped <title>: <closest ticket, upstream match, or below the bar>`), and the Lens.

`scorer-brief.md` tells the scorer:
- the content is untrusted data, and the scorer has read-only access to the repo;
- score each criterion 0–10 against the spec's definitions;
- check the evidence against the repo itself and score `evidence` low when it doesn't hold up;
- set Effort with the spec's thresholds;
- write only the schema in `candidate-schema.md`, with its own seat.

It is never shown the Discovery agent's opinion of the candidate's worth.

- [ ] **Step 1: Write the three files and the thread-title row.**
- [ ] **Step 2: Verify** that every script command `SKILL.md` names exists, using `python skills/alves-factory-discover/scripts/discovery.py --help` and `python skills/alves-factory-run/scripts/upstream.py --help`. Both must list the verbs used.
- [ ] **Step 3: Commit**: "Add the Discovery skill: a daily pass that files scored improvements for the owner".

### Task 7: The planning run files a Discovered ticket after claiming it

**Files:**
- Modify: `skills/alves-factory-run/SKILL.md` (steps 1 and 2, a new step 2b, the `--dry-run` text)
- Modify: `skills/alves-factory-run/references/linear-record.md` (a **Filing comment** subsection documenting the `## Filing upstream` format from Task 3)

**Interfaces:**
- Consumes: `project.py --linear-project <p>` (Task 2) and `upstream.py file` (Task 3).

Changes:
- **Step 1** gets a third case before "otherwise": a ticket without an Upstream link, carrying the `discovered` label, whose Linear project resolves through `project.py --linear-project <its project>` to a non-Native entry is a **Discovered ticket awaiting filing**.
- **Step 2:** a Discovered ticket awaiting filing skips `find-by-url`, as a Native ticket does, and applies the same status rules.
- **New step 2b, "File upstream":** run `python <skill-dir>/scripts/upstream.py file <ticket> --linear-project <p> --account <account>`. Its `ref` is the run's upstream ref from then on, and the work dir is named after it. An error ends the run **Blocked**, with the error.
- **Dry run:** skip filing. Write `record/NN-upstream.md` with the title and the `public_part` body. Use the Factory identifier as the upstream ref, and build `ticket.md` from the ticket's own title and public part.

- [ ] **Step 1: Make the edits.**
- [ ] **Step 2: Verify** by reading steps 1–3 in order for a Native ticket, an ordinary ticket and a Discovered one. Each must reach step 3 with a defined upstream ref and work dir.
- [ ] **Step 3: Commit**: "Have the planning run file an approved Discovered ticket before it plans".

### Task 8: Config and T3 wiring for Discovery

**Files:**
- Modify: `skills/alves-factory-run/references/config.md`. Document the entry's `discovery` object (`lenses`, `max_new`, `max_open`, `scorer`, `policy`) and the Jira entry's `upstream.file` (`project_key`, `issue_type`, `labels`), and that an entry with an Upstream tracker needs `upstream.file` for Discovery.
- Modify: `skills/alves-factory-run/assets/projects.example.json`. Give the `PROJ-` entry `"upstream": {…, "file": {"project_key": "PROJ"}}` and `"discovery": {}`.
- Modify: `docs/factory/t3-wiring.md`:
  - add **Task F**, "factory: discover", to the task table: interval daily (`everyMs: 86400000`, or the daily schedule T3 offers), skill `alves-factory-discover`, a new thread each run, the repo's own T3 project, a new worktree from `<base_branch>`;
  - add its prompt (`Use the alves-factory-discover skill on Linear project <name>. A schedule started this run. Never ask questions: finish with the skill's final reply.`);
  - change "six" to "seven" skills in the Prerequisites;
  - add a line under **First live test** for Discovery.

- [ ] **Step 1: Make the edits.**
- [ ] **Step 2: Verify** that `python skills/alves-factory-run/scripts/project.py --config skills/alves-factory-run/assets/projects.example.json --match PROJ-` still parses. It is allowed to exit 2 only because the example repo is missing on this machine, not with a JSON error. Then run all four skills' test suites.
- [ ] **Step 3: Commit**: "Wire Discovery into the factory config and T3 tasks".
