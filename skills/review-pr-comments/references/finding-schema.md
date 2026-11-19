# Finding schema

The exact shape every Reviewer returns, and every verifier receives. Return a single JSON object and nothing else.

```json
{
  "reviewer": "security",
  "skipped": false,
  "skip_reason": null,
  "findings": [
    {
      "label": "issue",
      "blocking": true,
      "subject": "SQL query built from request parameters",
      "discussion": "`build_query` interpolates `request.args['sort']` into the ORDER BY clause ...",
      "path": "api/reports.py",
      "start_line": null,
      "line": 42,
      "suggestion": null,
      "evidence": "query = f\"SELECT * FROM reports ORDER BY {sort}\"",
      "confidence": "high",
      "severity": "high"
    }
  ]
}
```

## Fields

- `reviewer`: the Reviewer's name, one of `security`, `performance`, `style`, `docs`, `testing`, `architecture`, `spec`.
- `skipped` / `skip_reason`: `true` plus a one-line reason when the Reviewer could not run (e.g. Spec with no spec source); `findings` is then empty.
- `findings`: at most 5, most severe first. An empty list is a valid, expected result.
  - `label`, `blocking`, `subject`, `discussion`: as defined in [conventional-comments.md](conventional-comments.md). `blocking: true` only with `issue` or `todo`.
  - `path`: repo-relative file path, or `null` when the Finding concerns the PR as a whole (e.g. "no changelog entry").
  - `line`: the line number in the PR's head version of `path`; `null` when `path` is `null`. May point outside the diff: placement is decided at aggregation.
  - `start_line`: first line of a multi-line range ending at `line`, else `null`.
  - `suggestion`: full replacement text for `start_line..line` (or `line`), indentation preserved, or `null`.
  - `evidence`: the exact code or text quoted from the checkout, diff, ticket or CI output that supports the Finding. Required; a Finding without evidence is rejected.
  - `confidence`: `high` | `medium` | `low`: how sure the Reviewer is the Finding is real.
  - `severity`: `critical` | `high` | `medium` | `low`: impact if it is real.
