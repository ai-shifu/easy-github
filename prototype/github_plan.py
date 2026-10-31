"""Offline GitHub handoff contract. This module has no network or merge executor."""

import re


class ContractError(ValueError):
    pass


def publish_plan(repository, delivery, title, base="prototype-team", previous_head=None,
                 pull_number=None):
    """Describe publishing a frozen revision; never execute these operations.

    REST schema: https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request
    Reviews: https://docs.github.com/en/rest/pulls/reviews
    Checks: https://docs.github.com/en/rest/checks/runs
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ContractError("Expected owner/repository")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", delivery["work_id"]):
        raise ContractError("Invalid work identifier")
    for sha in (delivery["sha"], previous_head):
        if sha is not None and not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", sha):
            raise ContractError("Expected a full commit identifier")
    if pull_number is not None and (pull_number <= 0 or previous_head is None):
        raise ContractError("Updating a PR requires its previous frozen head")
    branch = "newgit/" + delivery["work_id"]
    endpoint = f"/repos/{repository}/pulls"
    metadata = {"title": title, "base": base,
                "body": f"Work {delivery['work_id']}, revision {delivery['revision']}.\n"
                        f"Frozen delivery: {delivery['sha']}\n"}
    steps = [{
        "operation": "git_push_with_lease",
        "repository": repository,
        "ref": "refs/heads/" + branch,
        "commit": delivery["sha"],
        "expected_old_sha": previous_head,
        "note": "A null old SHA means the remote ref must not exist.",
    }]
    if pull_number is None:
        steps.append({
            "operation": "github_request", "method": "POST", "path": endpoint,
            "body": {**metadata, "head": branch, "draft": False},
        })
    else:
        steps.append({"operation": "github_request", "method": "PATCH",
                      "path": endpoint + "/" + str(pull_number), "body": metadata})
    steps.append({
        "operation": "github_request", "method": "GET",
        "path": endpoint + "/" + (str(pull_number) if pull_number else "{created_number}"),
        "expected_head_sha": delivery["sha"],
    })
    return {
        "mode": "plan_only", "executed": False, "repository": repository,
        "base": base, "branch": branch, "delivery_sha": delivery["sha"],
        "pull_number": pull_number, "steps": steps,
        "review": "Human review through GitHub; no approval is synthesized by this plan.",
        "checks": "Fetch all pages for the actual candidate SHA; head checks do not prove a merge-group candidate.",
        "accept": "No merge operation in this prototype. GitHub policies remain authoritative.",
    }


def bind_pr_readback(plan, response):
    """Reject a changed PR head instead of pretending the frozen revision was published."""
    expected = (plan["delivery_sha"], plan["branch"], plan["base"], plan["repository"])
    actual = (response["head"]["sha"], response["head"]["ref"], response["base"]["ref"],
              response["base"]["repo"]["full_name"])
    if actual != expected:
        raise ContractError("PR readback does not match the frozen delivery and target")
    if plan["pull_number"] and response["number"] != plan["pull_number"]:
        raise ContractError("Unexpected pull request")
    if response["state"] != "open" or response.get("merged") or response.get("draft"):
        raise ContractError("Expected an open, ready-for-review PR")
    return {"pull_number": response["number"], "head_sha": response["head"]["sha"],
            "review_status": "not_evaluated", "merge_status": "not_evaluated"}
