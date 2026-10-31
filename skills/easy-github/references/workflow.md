# Local delivery and review

English | [简体中文](zh-CN/workflow.md) · [Skill instructions](../SKILL.md)

Below, `<skill-directory>` is the installation directory containing `SKILL.md`. Call its `scripts/` using absolute paths so commands do not depend on the current working directory. Use IDs, attempts, SHAs, and workspace paths returned by the program. Commands return JSON; a nonzero exit code means the operation did not complete.

## Initialize and resume

Python 3.11+ and Git are required. The state lock currently uses `fcntl`, supporting macOS/Linux. First confirm the user's chosen Git project and its current HEAD. Initialization imports **only the committed HEAD**: it does not include uncommitted changes or fetch remote updates. Do not commit, clean, or overwrite the original workspace just to initialize the state.

Keep the state directory outside both the source repository and the Skill installation directory. Record its location for a new task. To resume, read the existing `status` instead of initializing again:

```bash
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" init --source "<source-repository-root>"
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" status
```

The state repository is an independent copy of the source project. Its team version is `refs/heads/prototype-team`. Subsequent `start` calls use that version; it **does not automatically follow changes in the source repository or GitHub**. Skill files can be copied for installation. Runtime state contains absolute paths and Git worktree associations, so do not move the entire state directory or distribute it as part of the Skill.

## Start work and freeze a delivery

```bash
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" start --owner "<author-label>" --tool "<actual-tool-label>" --title "<work-intent>"
```

Give the returned `workspace`, `base`, `id`, and `attempt` to the user's chosen coding tool. The workspace is an independent, detached Git worktree; the user does not need to create a branch manually. See [coders.md](coders.md) for the coding-tool handoff.

Before delivery, confirm that AI tools, editors, and background processes have all stopped writing to that directory. The program's lock only coordinates its own calls. `--handoff` is a declaration by the caller, not a command that stops writers. If the handoff cannot be verified, do not claim that a reliable delivery has been frozen.

```bash
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" submit --work "<work-ID>" --attempt <current-attempt> --handoff --summary "<summary-of-actual-changes>"
```

Save the complete delivery JSON returned by the program. It freezes a new snapshot without moving the original workspace's HEAD or Git index. Later edits do not change that delivered snapshot. Submitting again creates a new revision; approval of the previous revision does not carry over. `submit` includes all files in the workspace that Git would include. Check the change scope before delivery to keep run logs, temporary files, and credentials out.

## Review and revise

```bash
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" review --delivery "<delivery-ID>" --reviewer "<intended-reviewer-label>"
```

The `reviewer` must differ from the author's label, but labels do not authenticate identity. `review` only prepares material, and `ready` only means there is a candidate available for checking. Do not claim that the named person has reviewed or approved it. Present the intent, actual diff, `candidate_sha`, `team_sha`, and checks that have actually run.

If the result is `needs_update`, read the reason. The current program handles changes to the same file conservatively: it requires external revision even when Git might merge them automatically. Without actual Git conflict evidence, do not describe overlapping file changes as a textual conflict.

```bash
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" update --delivery "<latest-delivery-ID>"
```

`update` retains the original directory and returns a new workspace, `attempt`, and `context_file`. The context includes the original delivery's diff and the team version's diff. An external coding tool rebuilds the intended change on the new base; the program does not generate business-code fixes. Submit only from the new directory and attempt, then review again. Once an update starts, the old attempt cannot be accepted.

### When neither change has been accepted

If B needs to be combined with pending A, do not accept A just to establish a base:

```bash
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" review --delivery "<B-delivery-ID>" --reviewer "<reviewer-label>" --onto-delivery "<A-delivery-ID>"
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" update --delivery "<latest-B-delivery-ID>" --onto-delivery "<A-delivery-ID>"
```

Run the second command only when revision is needed. `team_sha` remains the actual team version; `comparison_sha` is A's candidate version. Do not confuse `team_diff` with `comparison_diff`. While A has not been included in the local team version, the repair workspace and new delivery inherit `onto_delivery_id`; omitting the option does not remove that dependency. If A has a newer revision, explicitly select the current delivery and revise again instead of silently reusing old A. A review with `preview_only=true` can never be accepted with `accept`.

Once A has been accepted locally after its own review, checks, and human confirmation, B can be updated without specifying another dependency:

```bash
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" update --delivery "<latest-B-delivery-ID>"
```

The program checks whether A's fixed SHA is already in the current team version's history. If it is, the new workspace uses the **current team version** as its base and drops the pending dependency and `preview_only` flag. A later, unaccepted revision of A does not replace the version already included. Have the external tool restore B's intent in the new workspace, stop writing, and run `submit` and `review` again. Check the new exact candidate, then obtain human confirmation before accepting it. An old preview review does not automatically become an acceptable review; its checks and approval do not carry over. A merge on GitHub does not automatically update this independent local team version.

## Check the exact candidate

An external executor obtains an independent checkout of the candidate named in the review, verifies the actual SHA, and runs the project's required checks. Record a check only after it has actually run:

```bash
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" check --review "<review-ID>" --snapshot "<actual-candidate-SHA>" --name "<check-name>" --status passed --detail "<actual-command-result-and-evidence-location>"
```

Use `--status failed` for failures; do not hide them. Results from a workspace or an old delivery cannot be recorded against a different candidate. The program stores external reports and cannot prove that checks actually ran. The current gate requires at least one check and all recorded checks to pass; it has no production-grade list of mandatory checks.

## Accept locally after human confirmation

Run this only when the user has confirmed **this review and its exact candidate**, and that authorization is still valid. Do not ask again for confirmation that remains valid. AI recommendations, passing tests, or a general instruction to continue do not automatically authorize acceptance.

```bash
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" accept --review "<review-ID>" --reviewer "<reviewer-label-from-this-review>"
python3 "<skill-directory>/scripts/newgit.py" --state "<state-directory>" status
```

This operation **only advances the team version in the isolated state repository**. It does not update the source repository or GitHub and does not merge main. Report local inclusion only after successful readback. A newer delivery, an attempt being updated, failed checks, a changed team version, or mismatched labels blocks acceptance. Prepare a new review and any necessary revision instead of forcing repeated writes or reusing old approval. Never proactively merge main.

Acceptance first saves an intent record for the exact candidate. If the process is interrupted, the next operation holding the lock reconciles the Git ref and that record. If the ref update was applied, it completes the review record. If it was not applied, it clears the intent and still requires an explicit retry. A third version or mismatched metadata stops recovery without overwriting the current state; investigate first. The same reviewer can safely retry a completed acceptance while its candidate remains the current team version.
