# Conventional Comments rules

How a Verified Finding is rendered as a Comment. Based on https://conventionalcomments.org/, narrowed for this skill.

## Shape

```
<label> (<blocking|non-blocking>, <reviewer>[, <reviewer>...]): <subject>

<discussion>

<!-- review-pr-comments:<reviewers>:<hash> -->
```

- **subject**: one line, under ~80 characters, stating the problem or proposal itself.
- **discussion**: why it matters and what to do, concrete enough to act on without asking back. Quote the code it refers to when the anchor alone is ambiguous. Optional only for `praise` and `nitpick`.
- The marker is always the last line.

## Labels

Only these nine:

| Label | Use for | Blocking allowed |
|---|---|---|
| `issue` | a concrete defect: bug, vulnerability, broken contract, unmet requirement | yes |
| `todo` | a small, necessary change: missing doc entry, missing test case | yes |
| `suggestion` | a proposed improvement the author may decline | no |
| `question` | something the reviewer could not determine from the code | no |
| `nitpick` | trivial, preference-level | never |
| `praise` | something genuinely good; at most 2 per Review | no |
| `thought` | an idea worth considering, not a request | no |
| `chore` | a process step: changelog, migration, regenerate artifact | no |
| `note` | information the author should know, no action needed | no |

## Decorations

1. First decoration is `blocking` or `non-blocking`, always present. `blocking` only on `issue` and `todo`.
2. Then the Reviewer name(s) that raised it: `security`, `performance`, `style`, `docs`, `testing`, `architecture`, `spec`. A merged Comment lists each Reviewer, in that order.

Example: `issue (blocking, security): SQL query built from request parameters`

## Suggestion blocks

When the fix is a concrete replacement of the anchored lines, put it in a GitHub suggestion block so the author can apply it in one click:

````
```suggestion
<full replacement text for lines start_line..line, indentation preserved>
```
````

Use it only when all anchored lines sit inside one diff hunk on the PR's new side, and the block replaces exactly those lines. Otherwise show the code in a plain fenced block with its language.

## Marker

The last line of every Comment, invisible on GitHub, used to skip Comments already posted on a re-run:

```
<!-- review-pr-comments:<reviewers>:<hash> -->
```

- `<reviewers>`: the decoration's Reviewer names joined with `+`, e.g. `security+performance`.
- `<hash>`: first 8 hex chars of `sha1("<reviewers>|<path>|<label>|<subject lowercased, whitespace collapsed>")`. `<path>` is empty for General Comments. Line numbers are excluded so the marker survives rebases that shift lines.

## Examples

```
suggestion (non-blocking, performance): Hoist the regex compile out of the loop

`re.compile` runs once per row here; on the 50k-row import that is measurable.

```suggestion
    pattern = re.compile(r"^\d{4}-\d{2}$")
    for row in rows:
        if pattern.match(row.period):
```

<!-- review-pr-comments:performance:3fa91c0e -->
```

```
todo (blocking, docs): Document the new `RETRY_LIMIT` env var

The README's configuration table lists every other env var `config.py` reads; this one is missing.

<!-- review-pr-comments:docs:9b17d2a4 -->
```
