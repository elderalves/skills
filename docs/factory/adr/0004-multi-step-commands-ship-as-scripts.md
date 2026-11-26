# Multi-step commands ship as tested scripts

The factory's references were written for a POSIX shell, but its runs execute in whatever shell the runner has, often Windows PowerShell 5.1, and the agent quietly translates any snippet it is given. The PCS-6113 run turned the evidence branch's `for … | git mktree` loop into PowerShell. PowerShell ends every line it pipes to a native program with CRLF, so `git mktree` stored each screenshot name with a trailing carriage return, and every image in PR #62 rendered broken. In the same step a failed fetch left `$commit` empty, and `git push origin ":refs/heads/<branch>"` deleted the evidence branch. Neither failure was visible, because nothing read back what had been pushed.

So any command longer than one line ships as a script in the skill's `scripts/`, with tests, and the reference calls it. Inline commands are single commands. When the syntax differs between bash and PowerShell (an inline `VAR=value` prefix, line continuations), the reference shows both forms. A script that reaches the network takes the run's `--account` and fetches the token itself. Every factory script reads its JSON inputs whether a shell wrote them as UTF-8, UTF-8 with a BOM or UTF-16. A script that publishes reads its result back from the host before reporting success, as `publish_evidence.py` does with the evidence tree.

## Considered Options

- Snippets in both bash and PowerShell: rejected because two hand-kept copies drift, and the next runner may have a third shell.
- Requiring Git Bash for every snippet: rejected because it depends on every runner having it and every model obeying it; this run's model translated on its own initiative.
- Fixing only the evidence snippet: rejected because the same translation risk sits in every multi-step snippet, and the cost of a script is one file and its tests.
