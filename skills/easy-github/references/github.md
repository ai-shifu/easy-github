# GitHub test-repository adapter

English | [简体中文](zh-CN/github.md) · [Skill instructions](../SKILL.md)

`scripts/github_live.py` is currently a restricted experimental adapter. It only supports an explicitly specified **private repository on `github.com` whose name starts with `newgit-integration-`**. Allowed base branches are `prototype-team` and `newgit/<work_id>`; delivery heads use `newgit/<work_id>`. Do not describe it as supporting arbitrary production repositories. Do not rename or copy repositories, or disable checks, without authorization to bypass these limits.

It requires an authenticated `gh` and the local bare Git directory containing the fixed delivery. Write scope must come from the user's current task or existing authorization that remains valid. The Skill's presence and earlier experiments do not grant write access to any repository. The adapter has no operations for creating repositories, initializing remote bases, `APPROVE`, or merging.

## Before publishing

- Retain the complete delivery JSON from the management program and use the state repository's returned `repo` as `--git-dir`. Before publication, the adapter verifies the complete delivery record in the sibling `state.json` and the immutable delivery ref in `repo.git`. An arbitrary commit or manually altered JSON cannot replace a delivered version.
- The remote target base must already exist, and its SHA must exactly equal `delivery.base`. Establishing the base is a separate preparation step; do not merge main or bypass validation to do it.
- Read back the repository, base/head, existing PRs, reviews, and CI to avoid creating duplicates or posting the same review again. The GitHub actor is the actual authenticated account; do not describe local author/reviewer labels as separate real people.

## Create or update a PR

Write the PR body to a file, then run:

```bash
python3 "<skill-directory>/scripts/github_live.py" --repository "<owner/newgit-integration-name>" --git-dir "<state-directory>/repo.git" --evidence-dir "<run-record-directory>/github" publish --delivery-file "<complete-delivery-JSON-file>" --title "<change-title>" --body-file "<body-file>" --base "prototype-team"
```

Describe the concrete problem, behavior change, actual implementation tool, verification performed, and dependencies. Clearly distinguish checks that have not run. The adapter creates a non-draft PR and verifies that both its head and base belong to the specified repository.

For an initial publication, the delivery branch must not already exist. To update an existing PR, provide both options in the same `publish` command:

```text
--previous-head <full-old-head-SHA-just-read-back> --pull-number <actual-PR-number>
```

The program pushes the fixed SHA using an exact lease and verifies the remote branch and PR through readback. If head/base has changed, investigate and prepare the delivery or review again. Do not retry blindly and overwrite someone else's updates.

If B was repaired on top of pending A, B's `delivery.base` should be A's fixed SHA. Use `--base "newgit/<A-work_id>"`. This keeps both stacked PRs unmerged. If A's branch has moved, stop reusing old B. See [workflow.md](workflow.md) for candidate combination steps.

## Post an AI review

After completing the review, use the head, base ref, and base SHA that were actually reviewed:

```bash
python3 "<skill-directory>/scripts/github_live.py" --repository "<owner/newgit-integration-name>" --git-dir "<state-directory>/repo.git" --evidence-dir "<run-record-directory>/github" review --number <PR-number> --commit "<reviewed-head-SHA>" --base "<reviewed-base-branch>" --base-sha "<reviewed-base-SHA>" --body-file "<review-body-file>"
```

State the actual review tool, scope, actionable findings, whether tests were run by the reviewer or reported externally, and anything left unverified. The adapter only posts `COMMENT`; do not call it human approval or `APPROVE`.

The program verifies the exact head/base before and after posting, then reads back the review ID, author, state, body, and commit. Failed writes are not automatically retried. If the response is uncertain, read the remote state first to determine whether the action happened and avoid duplicate posts.

## Final readback

Report separately whether the PR was created and its current head/base, whether it remains open and unmerged, the exact SHA and result of CI, whether the AI `COMMENT` exists, and whether a human has actually approved it. Successful PR publication does not mean CI succeeded or that anyone has reviewed it. Evidence JSON is saved in the specified `--evidence-dir`; keep it out of the Skill package and business-code commits.

Regardless of tests, reviews, or human recommendations, never proactively merge main. This adapter performs no merges.
