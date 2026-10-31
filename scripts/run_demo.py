#!/usr/bin/env python3
"""Run the two-person scenario on real Git and simulated external-tool file writes."""

import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototype"))
sys.path.insert(0, str(ROOT / "scripts"))

from newgit import Prototype, PrototypeError
from github_plan import publish_plan, bind_pr_readback, ContractError
from demo_support import PRICE, COUPON, COMBINED, seed_project, git, check_candidate


def run_scenario(root):
    root = Path(root).resolve()
    source = seed_project(root)
    original_source = git(source, "rev-parse", "HEAD")
    state = root / "state"
    controller = Prototype.initialize(source, state)
    events = []
    checks = []

    def checked(review, plain, coupon):
        report = check_candidate(state, review, plain, coupon)
        controller.record_check(review["id"], **report)
        if report["status"] != "passed":
            raise AssertionError(report)
        checks.append(report)

    lin = controller.start("xiaolin", "Codex (simulated)", "会员调价")
    zhou = controller.start("xiaozhou", "Claude Code (simulated)", "增加优惠券")
    assert lin["base"] == zhou["base"]
    assert lin["workspace"] != zhou["workspace"]
    events.append({"step": "start", "lin": lin, "zhou": zhou})

    # These writes simulate outputs from external coding tools; neither product is launched.
    (Path(lin["workspace"]) / "checkout.py").write_text(PRICE)
    (Path(zhou["workspace"]) / "checkout.py").write_text(COUPON)
    a1 = controller.submit(lin["id"], lin["attempt"], "会员价改为129元", handoff=True)
    b1 = controller.submit(zhou["id"], zhou["attempt"], "支持20元优惠券", handoff=True)
    events.append({"step": "deliver", "a1": a1, "b1": b1})

    # Continuing work after delivery must stay outside the submitted snapshot.
    draft_path = Path(zhou["workspace"]) / "next-task.txt"
    draft_path.write_text("Still editing a different idea.\n")
    original_zhou_head = git(zhou["workspace"], "rev-parse", "HEAD")
    review_a = controller.review(a1["id"], "xiaozhou")
    assert review_a["status"] == "ready"
    checked(review_a, 129, 129)
    accepted_a = controller.accept(review_a["id"], "xiaozhou")
    v2 = controller.status()["team_sha"]
    assert git(zhou["workspace"], "rev-parse", "HEAD") == original_zhou_head
    assert (Path(zhou["workspace"]) / "checkout.py").read_text() == COUPON
    events.append({"step": "accept_price", "review": review_a, "result": accepted_a})

    blocked = controller.review(b1["id"], "xiaolin")
    assert blocked["status"] == "needs_update"
    try:
        controller.accept(blocked["id"], "xiaolin")
    except PrototypeError as error:
        blocked_accept = str(error)
    else:
        raise AssertionError("A conflicting delivery was accepted")
    events.append({"step": "conflict", "review": blocked, "accept_rejected": blocked_accept})

    repair = controller.prepare_update(b1["id"])
    assert repair["id"] == zhou["id"] and repair["base"] == v2
    assert repair["workspace"] != zhou["workspace"]
    assert draft_path.read_text() == "Still editing a different idea.\n"
    assert not (Path(repair["workspace"]) / "next-task.txt").exists()
    assert Path(repair["context_file"]).exists()
    (Path(repair["workspace"]) / "checkout.py").write_text(COMBINED)
    b2 = controller.submit(repair["id"], repair["attempt"], "保留129元，接入优惠券", handoff=True)
    assert b2["revision"] == b1["revision"] + 1
    assert git(state / "repo.git", "show", b1["sha"] + ":checkout.py") == COUPON.strip()
    events.append({"step": "repair_delivery", "repair": repair, "b2": b2})

    review_b = controller.review(b2["id"], "xiaolin")
    assert review_b["status"] == "ready"
    try:
        controller.record_check(review_b["id"], b1["sha"], "old-result", "passed")
    except PrototypeError as error:
        stale_check = str(error)
    else:
        raise AssertionError("Evidence for an older snapshot was accepted")
    checked(review_b, 129, 109)
    accepted_b = controller.accept(review_b["id"], "xiaolin")
    final_sha = controller.status()["team_sha"]
    final_code = git(state / "repo.git", "show", final_sha + ":checkout.py")
    assert final_code == COMBINED.strip()
    assert git(source, "rev-parse", "HEAD") == original_source
    assert "refs/heads/main" not in git(state / "repo.git", "for-each-ref", "--format=%(refname)").splitlines()
    events.append({"step": "accept_coupon", "review": review_b, "result": accepted_b,
                   "old_evidence_rejected": stale_check})

    # Offline contract fixtures, not a call to GitHub or proof of a live integration.
    plan = publish_plan("example/membership", b2, "增加优惠券")
    response = {"number": 42, "state": "open", "draft": False, "merged": False,
                "head": {"sha": b2["sha"], "ref": plan["branch"]},
                "base": {"ref": plan["base"], "repo": {"full_name": plan["repository"]}}}
    bound = bind_pr_readback(plan, response)
    response["head"]["sha"] = a1["sha"]
    try:
        bind_pr_readback(plan, response)
    except ContractError:
        rejected_drift = True
    else:
        raise AssertionError("A changed remote head was treated as the submitted revision")
    return {
        "result": "passed", "mode": "real_local_git_simulated_coders_and_reviewers",
        "state_directory": str(state), "source_head_unchanged": True,
        "main_branch_created_or_updated": False, "checks": checks,
        "final": {"team_sha": final_sha, "code": final_code, "plain": 129, "with_coupon": 109},
        "events": events,
        "github": {"mode": "offline_contract_fixtures", "live_requests": 0,
                   "plan": plan, "readback": bound, "changed_head_rejected": rejected_drift},
        "limits": ["Codex and Claude Code were not launched", "Reviewer names are simulated identities",
                   "No GitHub PR, permission, CI, or merge was exercised", "No background autosave"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New or empty directory to retain fixtures and report")
    args = parser.parse_args()
    if args.output:
        root = args.output.resolve()
        if root.exists() and any(root.iterdir()):
            parser.error("--output must be a new or empty directory")
        root.mkdir(parents=True, exist_ok=True)
        report = run_scenario(root)
        (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"result": report["result"], "report": str(root / "report.json"),
                          "final": report["final"], "limits": report["limits"]}, ensure_ascii=False, indent=2))
    else:
        with tempfile.TemporaryDirectory(prefix="newgit-demo-") as directory:
            report = run_scenario(directory)
            report["fixture_retained"] = False
            print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
