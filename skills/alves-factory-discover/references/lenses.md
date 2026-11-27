# Lenses

What a Discovery pass looks for through each default Lens, and what counts as evidence. Every Lens holds candidates to one bar: evidence a reader can check in the repo (a path with lines, a commit, the output of a command you ran in the worktree) that shows the problem itself, not a general best practice the repo could follow. The day's change set (`git log --since=<since>`) is the first place to look, then the repo as a whole. A repo's `discovery.lenses` may name a Lens not listed here: take its name as the angle, and hold it to the same bar.

## architecture

Look for module boundaries the code crosses (a layer reaching into another's internals, an import cycle), one concept implemented twice in diverging ways, a module that everything depends on and that changes with every feature, and abstractions with one caller that cost more than they hide. Evidence: the import or call sites that cross the boundary, the two implementations side by side, `git log` showing how often a file changes alongside unrelated ones.

## testing

Look for risky code no test reaches (error branches, parsing, money, permissions, concurrency), tests that pass whatever the code does (no assertion, an assertion on a mock), flaky or skipped tests, and a recent change that shipped without a test. Evidence: the untested lines and a search showing no test names them, a coverage report you ran, the skipped test with its skip reason, the commit that added the code without one.

## performance

Look for work repeated per item that could be done once (a query or request inside a loop, an N+1 read), unbounded growth (a cache with no eviction, a list read whole into memory), blocking calls on a hot or user-facing path, and oversized assets or bundles. Evidence: the loop and the call inside it, the code path that makes it hot, a measurement or build output you ran (timings, bundle sizes, query counts).

## ux-accessibility

Look for interactive elements with no accessible name, controls unreachable by keyboard, missing labels on form fields, low colour contrast, images without alternative text, error states the user never sees, and copy that contradicts what the code does. Evidence: the component and the markup it renders, an accessibility linter or audit you ran, the error path that swallows the message.

## security

Look for input that reaches a query, a shell, a file path or HTML without validation or escaping, secrets in the repo or in logs, missing authorization checks beside routes that have them, outdated dependencies with known advisories, and permissive defaults (CORS, cookies, TLS). Evidence: the path from input to sink with its lines, the route missing the check beside one that has it, the audit tool's output (`npm audit`, `pip-audit`) you ran. Describe the weakness; write no working exploit.

## maintainability

Look for dead code, functions too long or too nested to change safely, duplicated logic that has already drifted, misleading names, TODOs and workarounds that outlived their reason, and configuration scattered where one source would do. Evidence: the code with its lines, a search showing nothing calls it, the two copies and the difference between them, `git blame` showing how old the workaround is.

## developer-experience

Look for setup steps the README omits or gets wrong, scripts that fail on a clean checkout, slow or noisy builds and test runs, lint or type errors left standing, and missing or misleading error messages from the repo's own tooling. Evidence: the command you ran in the worktree and its output, the README step that does not match the scripts, the build time you measured.
