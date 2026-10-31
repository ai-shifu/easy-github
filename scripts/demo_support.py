"""Fixture code and an external candidate checker for the local prototype."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


INITIAL = "def checkout_total(coupon_discount=0):\n    return 99\n"
PRICE = "def checkout_total(coupon_discount=0):\n    return 129\n"
COUPON = "def checkout_total(coupon_discount=0):\n    return max(0, 99 - coupon_discount)\n"
COMBINED = "def checkout_total(coupon_discount=0):\n    return max(0, 129 - coupon_discount)\n"


def git(directory, *args):
    result = subprocess.run(["git", "-C", str(directory), *args], text=True,
                            capture_output=True, check=True)
    return result.stdout.strip()


def seed_project(root):
    source = Path(root) / "source"
    source.mkdir(parents=True)
    git(source, "init", "-b", "seed")
    git(source, "config", "user.name", "Prototype Fixture")
    git(source, "config", "user.email", "fixture@example.invalid")
    git(source, "config", "commit.gpgsign", "false")
    git(source, "config", "core.hooksPath", "/dev/null")
    (source / "checkout.py").write_text(INITIAL)
    (source / "README.md").write_text("Local membership fixture.\n")
    (source / ".gitignore").write_text("*.env\n__pycache__/\n")
    git(source, "add", "--all")
    git(source, "commit", "-m", "Initial fixture")
    return source


def check_candidate(state, review, expected_plain, expected_coupon):
    """Run outside the management program against bytes read from the exact Git commit."""
    repo = Path(state) / "repo.git"
    code = git(repo, "show", review["candidate_sha"] + ":checkout.py") + "\n"
    with tempfile.TemporaryDirectory(prefix="newgit-check-") as directory:
        module = Path(directory) / "checkout.py"
        module.write_text(code)
        checker = (
            "import json,runpy,sys; "
            "f=runpy.run_path(sys.argv[1])['checkout_total']; "
            "actual=[f(),f(20)]; expected=[int(sys.argv[2]),int(sys.argv[3])]; "
            "print(json.dumps({'actual':actual,'expected':expected})); "
            "sys.exit(0 if actual==expected else 1)"
        )
        result = subprocess.run([sys.executable, "-I", "-c", checker, str(module),
                                 str(expected_plain), str(expected_coupon)],
                                text=True, capture_output=True)
    return {"snapshot_sha": review["candidate_sha"], "name": "checkout-behavior",
            "status": "passed" if result.returncode == 0 else "failed",
            "detail": result.stdout.strip() + result.stderr.strip()}


def attach_check(controller, review, plain, coupon):
    check = check_candidate(controller.state, review, plain, coupon)
    controller.record_check(review["id"], **check)
    return check
