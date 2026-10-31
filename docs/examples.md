# Usage examples

[English](examples.md) | [简体中文](zh-CN/examples.md)

These examples describe intended actions and expected workflows. They do not claim that any action has succeeded in your current project. `$easy-github` is the Codex invocation syntax; use `/easy-github` in Claude Code.

Easy GitHub manages versions and handoffs. Your chosen coding tool still writes the application code. Final reports should distinguish actual results, AI recommendations, and human decisions.

## Start a task on your own

In a local project with a committed version, request a workspace:

```text
Use $easy-github to prepare an isolated workspace for adding coupons to checkout.
I'll use my current coding tool to write the code. First tell me the workspace path and starting version.
```

The Skill checks the current project and any existing state. On first use, it imports only the committed HEAD, creates a state repository outside the source project, and prepares an isolated workspace. Existing uncommitted changes do not automatically enter the new workspace. It will not commit or clean up the source project without authorization to make that happen.

Complete the application changes and checks in the returned workspace. Confirm that tools using that directory have stopped writing, then say:

```text
Use $easy-github to hand off these changes. The coding tool has stopped writing.
Summarize the actual changes, checks that ran, and decisions I need to make. Do not accept the delivery yet.
```

The program freezes a delivery and prepares review materials. Checks must correspond to the exact candidate under review. A coding tool saying it has finished does not mean all verification has passed.

## Two people, two tools, one feature

Suppose the original membership price is CNY 99:

- Lin uses Codex to change the price to CNY 129.
- Zhou uses GitHub Copilot CLI to add coupon discounts, still calculating from CNY 99.

Prepare separate workspaces so that both tools work independently from the same project version. After both tools stop writing, hand off both deliveries and ask:

```text
Use $easy-github to check whether these two deliveries can work together.
Neither the price change nor the coupon change has been accepted. If revisions are needed, prepare a new workspace for the coupon fix and preserve both original workspaces.
```

The Skill should use the frozen price-change delivery as the comparison target and produce a combination preview. It should not first accept the price change and thereby change the team's version.

The prototype takes a conservative approach when two deliveries touch the same file: it requests an external revision. Call it a Git text conflict only when actual Git output establishes one.

When a fix is needed, the program creates a new workspace based on the price-change candidate and provides the diffs and original intent of both deliveries. Hand that directory back to the original coding tool:

```text
Restore the coupon feature in the new revision workspace while keeping the price at CNY 129.
With no coupon, the total should be CNY 129. A CNY 20 coupon should reduce it to CNY 109. An excessive discount must not reduce the total below CNY 0.
Run the relevant checks, stop writing when finished, and hand the result back to Easy GitHub.
```

These values are requirements to verify. After the fix, freeze a new delivery, prepare review materials, and check the exact candidate. Checks and approvals for the old version do not carry over automatically. A combination preview still does not mean either delivery has been accepted.

Later, once the price change has passed its own review and checks and a person has confirmed its local acceptance into the team's version, ask:

```text
Use $easy-github to update the coupon work to the current local team version.
The price change has been accepted locally. Prepare a new workspace so the coding tool can restore the coupon feature, then hand it off and review it again. Do not accept it yet.
```

This ordinary `update` does not need a new dependency. After confirming that the frozen price-change version is in the local team's history, the program prepares a new workspace from the current team version. The new delivery and review are no longer marked as combination previews. The original workspaces, old deliveries, and old preview reviews remain available. Recheck the CNY 129, CNY 109, and CNY 0 minimum behaviors on the new candidate, then let a person decide whether to accept it locally. Merging the price change only on GitHub does not automatically update the separate local team version.

## Send changes to GitHub for review without merging

The GitHub adapter currently supports only private test repositories on `github.com` whose names start with `newgit-integration-`. The target baseline must already exist and match the delivery baseline. The adapter cannot manage arbitrary production repositories.

Once these conditions are met and `gh` is authenticated, specify the target explicitly:

```text
Use $easy-github to send this frozen delivery to my specified test repository for review.
Check the target repository, baseline, and any existing PR first to avoid duplicates.
Create a ready, non-draft PR. Record AI reviews as COMMENT only. Do not approve or merge.
```

If the coupon fix is based on the unmerged price-change delivery, its PR can target the price-change delivery branch so that both PRs remain unmerged. Reviews must bind to the head, base branch, and base SHA that were actually examined.

Afterward, the report should show each of the following separately:

- The PR link, current version, and whether it remains open and unmerged.
- The exact version CI ran against and its actual results.
- The AI review's tool, scope, findings, and COMMENT link.
- Whether a person has actually confirmed the change.

Creating a PR does not mean CI has passed. An AI review finding no issues does not mean a person has approved. Easy GitHub provides no GitHub merge or `APPROVE` operation and never proactively merges into `main`.

## When a tool is temporarily unavailable

```text
The current coding tool is not responding correctly. Use $easy-github to preserve the completed changes and failure record, then continue with the alternative tool I specify.
```

The Skill should first confirm that the old tool has stopped writing, then record the tool change and new handoff location. It will not present simulated output as real execution by the new tool or change global authentication settings without authorization just to keep going.

## What does local acceptance mean?

The local `accept` operation updates only the team version inside the isolated state repository. It does not update the source project or GitHub. A `preview_only` candidate cannot be accepted.

If you decide to accept a local candidate, explicitly confirm the exact review and where it should be accepted. The Skill must recheck that the versions and authorization still match, then read back the result. It must not report a candidate as already incorporated when it is only ready for review.

See the [Skill workflow reference](../skills/easy-github/references/workflow.md) for the detailed machine interface.
