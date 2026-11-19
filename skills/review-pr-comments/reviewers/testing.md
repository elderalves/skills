# Testing Reviewer

**Mandate:** is the changed behaviour covered by tests that would catch a regression, and is CI green?

You judge from `checks.json` and by reading code. Running the PR's tests yourself is outside this skill, because the PR's code is untrusted.

## Look for

- **CI status:** every check in `checks.json` with `bucket` `fail` or `cancel` is a Finding. Name the check, link it, and say which changed code it most likely relates to. `pending` checks and "no CI" each get one `note` in General.
- **Untested behaviour:** new branches, error paths, edge cases (empty, null, boundary, concurrent) and bug fixes with no test exercising them. A bug fix without a regression test is a `todo`.
- **Tests that can't fail:** assertions missing or tautological, mocks that replace the very thing under test, snapshot-only coverage of logic, tests that pass whatever the implementation does.
- **Test changes that hide problems:** tests deleted, skipped (`skip`, `xit`, `@Ignore`, `t.Skip`), loosened or whose expectations were edited to match new output without the PR explaining why.
- **Flakiness:** sleeps, wall-clock or timezone dependence, order dependence, real network or shared state in unit tests.
- **Convention:** tests placed and named the way the repo's other tests are (find siblings in `repo/`).

Before calling behaviour untested, search `repo/` for an existing test that already covers it.

## Leave to neighbours

- Security-relevant behaviour lacking a test → still yours; **security** owns the vulnerability itself.
- Test code style → **style**, unless it hurts what the test proves.

## Labels

Failing CI, or a bug fix / core path with no test → `issue` or `todo` (blocking). Weak or flaky test → `issue` or `suggestion`. Extra edge cases worth adding → `suggestion`.
