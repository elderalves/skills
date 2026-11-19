# Build the GitHub "create review" payload from $WORK/comments.json.
# Usage: jq --arg sha <headRefOid> -f review-payload.jq comments.json
[.comments[] | select(.placement == "general") | .body] as $g
| {
    commit_id: $sha,
    event: .event,
    body: (.summary
           + (if ($g | length) > 0 then "\n\n### General\n\n" + ($g | join("\n\n---\n\n")) else "" end)
           + "\n\n_Posted by review-pr-comments._"),
    comments: [ .comments[] | select(.placement == "inline")
                | {path, line, side: "RIGHT", body}
                  + (if .start_line then {start_line, start_side: "RIGHT"} else {} end) ]
  }
