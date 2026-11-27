# Candidate and score schemas

The exact shapes of the two inputs a Discovery pass writes into its work dir, beside `prepare.json`. `discovery.py check` names every way they break these rules, and `discovery.py score` scores nothing until they pass. `discovery.py prepare` starts each pass clean: it deletes `candidates.json`, `scores/`, `scored.json`, `selected.json`, `filed.json` and `record/` from the work dir, and nothing else.

## `candidates.json`

Written by the Discovery agent: a list of at most `max_candidates` (from `prepare.json`) candidates.

```json
[
  {
    "id": "c1",
    "title": "Cover the CSV importer's encoding fallback with tests",
    "problem": "importer/csv.py falls back to latin-1 on a decode error, and no test reaches that branch.",
    "why": "A regression there corrupts customer names silently; the last two importer bugs were encoding bugs.",
    "acceptance_criteria": [
      "A test feeds a latin-1 file and checks the decoded names.",
      "A test feeds an undecodable file and checks the error message."
    ],
    "evidence": [
      "importer/csv.py:48-61: the except UnicodeDecodeError branch",
      "coverage run -m pytest: importer/csv.py lines 48-61 not covered"
    ],
    "closest": { "identifier": "ALV-31", "why_different": "ALV-31 added the fallback; it shipped without tests." },
    "regression_of": null
  }
]
```

| Field | Rule |
|---|---|
| `id` | Letters, digits, `-` or `_`, unique in the file. It names the score file `scores/<id>.json`. |
| `title` | Non-empty text. The Discovered ticket's title, with no ref: the planning run adds the ref once it files the ticket upstream. |
| `problem`, `why` | Non-empty text. They become **Problem** and **Why it matters**, which go upstream. |
| `acceptance_criteria` | A non-empty list of non-empty text. It becomes **Acceptance criteria**, which goes upstream. |
| `evidence` | A non-empty list of non-empty text: paths with lines, command output. It stays in Linear. |
| `closest` | The closest Factory ticket in the repo's Linear project, any status: `identifier` (or `null` when nothing comes close) and `why_different`, non-empty text saying why this candidate is not that ticket again. |
| `regression_of` | The Done ticket this candidate shows a regression of, or `null`. It is required (as `null`) when there is none. |

## `scores/<id>.json`

Written by the scorer seat, one file per candidate.

```json
{
  "title": "Cover the CSV importer's encoding fallback with tests",
  "scores": { "impact": 9, "engineering": 8, "reach": 7, "evidence": 9, "urgency": 8 },
  "effort": "S",
  "rationale": {
    "impact": "Silent data corruption on import.",
    "engineering": "Two focused tests around an existing branch.",
    "reach": "Every CSV import passes through this code.",
    "evidence": "Checked importer/csv.py:48-61 and ran the coverage command; both hold.",
    "urgency": "Two importer encoding bugs in the last quarter."
  },
  "seat": { "providerInstanceId": "codex", "model": "gpt-6.1-sol" }
}
```

| Field | Rule |
|---|---|
| `title` | The `title` of the candidate it scored, exactly as `candidates.json` has it, so a score left from another candidate with the same id is caught. |
| `scores` | Exactly `impact`, `engineering`, `reach`, `evidence` and `urgency`, each an integer from 0 to 10 (not a string, float or boolean). |
| `effort` | `S` (under half a day), `M` (up to two days) or `L` (more). It never lowers the Value score. |
| `rationale` | Non-empty text for each of the five criteria. |
| `seat` | The scorer's own `providerInstanceId` and `model`. They must be `prepare.json`'s `scorer` (the model compared as `model_identity` does, so `claude-opus-5.5` and `claude-opus-5-5` are one model). |

## What `score` and `file` do with them

- **Value score** = Σ weight × score / 10, rounded half up; the weights are `prepare.json`'s `policy.weights` (default impact 30, engineering 25, reach 15, evidence 15, urgency 15).
- **Band:** High at `bands.high` (70) or more, Medium at `bands.medium` (50), Low at `bands.low` (30); below Low the candidate is not filed.
- **Selected:** the banded candidates by Value score, best first, ties in `candidates.json` order, at most `room`. Each item in `selected.json` is the candidate plus `value_score`, `band`, `effort`, `quick_win` (High and Effort `S`), `breakdown` (`[{criterion, weight, score, rationale}]`) and `lens`. `file` reads only `selected.json`.
- **Scored:** `scored.json` lists every candidate in the same order, as `{id, title, value_score, band, effort, quick_win, outcome}`: `band` is `null` below Low, and `outcome` is `selected`, `below the bar` (no band) or `past the room` (banded, beyond the first `room`). `score` prints these entries as `{"selected": [...], "dropped": [...]}`, split by `outcome`; the pass's reply names each dropped one from there.
- **Filed:** in Backlog of the Linear project, label `discovered` (plus `quick-win` on a Quick win), Linear priority 2 (High), 3 (Medium) or 4 (Low), never 1 (Urgent). The description is the template in [linear-record.md](../../alves-factory-run/references/linear-record.md), **Discovered ticket**.
- **Filed once:** after each create, `file` appends `{number, identifier, title}` (the item's position in `selected.json`, from 1) to `filed.json`, and a rerun skips every item recorded there, so a `file` that failed part-way is simply rerun. The one case a rerun can duplicate: `Linear.create` creates the issue and then reads it back, and when that read fails the ticket exists but is not in `filed.json`. Before rerunning after such an error, look in the Linear project's Backlog for the title the error was about. A `--dry-run` neither reads nor writes `filed.json`.
