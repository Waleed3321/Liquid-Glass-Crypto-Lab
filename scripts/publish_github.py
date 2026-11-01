"""Create the public GitHub repository and push the project.

Reads ``GITHUB_TOKEN`` from the environment (or ``.deploy.env``); the token is
never printed, never written to disk, and never placed in a remote URL.

Usage::

    uv run python scripts/publish_github.py --dry-run
    uv run python scripts/publish_github.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NAME = "liquid-glass-crypto-lab"


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True, env=env)


def git(*args: str) -> str:
    return run("git", *args).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(ROOT / ".deploy.env"))
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--description", default="Paper-only Solana + BNB Chain new-coin research lab")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    token = os.environ.get("GITHUB_TOKEN")
    if not token and not args.dry_run:
        raise SystemExit("GITHUB_TOKEN is not set.")

    if args.dry_run:
        print(json.dumps({"repository": args.name, "visibility": "public", "branch": "main"}, indent=2))
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(headers=headers, timeout=60.0) as client:
        me = client.get("https://api.github.com/user")
        if me.status_code != 200:
            raise SystemExit(f"GitHub token rejected ({me.status_code}).")
        login = me.json()["login"]
        lookup = client.get(f"https://api.github.com/repos/{login}/{args.name}")
        if lookup.status_code == 200:
            # GitHub names are case-insensitive; reuse the canonical name so a
            # pre-created repository does not need repository-creation rights.
            repo = lookup.json()["full_name"]
            print(f"reusing repository {repo}")
        else:
            created = client.post(
                "https://api.github.com/user/repos",
                json={
                    "name": args.name,
                    "description": args.description,
                    "private": False,
                    "has_issues": False,
                    "has_wiki": False,
                    "auto_init": False,
                },
            )
            if created.status_code not in (201, 422):
                raise SystemExit(f"Repository creation failed ({created.status_code}): {created.text[:300]}")
            repo = f"{login}/{args.name}"

    os.environ["GITHUB_REPO"] = repo

    if not (ROOT / ".git").is_dir():
        git("init")
        git("branch", "-M", "main")

    git("add", "-A")
    staged = git("status", "--porcelain")
    if staged:
        # Identity flags are per-command so the machine's git config is untouched.
        git(
            "-c",
            f"user.name={login}",
            "-c",
            f"user.email={login}@users.noreply.github.com",
            "commit",
            "-m",
            "Liquid Glass Crypto Lab: paper-only new-coin research platform",
        )
    else:
        print("nothing new to commit")

    helper = '!f() { echo username=x-access-token; echo "password=$GITHUB_TOKEN"; }; f'
    remote = f"https://github.com/{repo}.git"
    git("remote", "remove", "origin") if "origin" in git("remote") else None
    git("remote", "add", "origin", remote)
    git("-c", f"credential.helper={helper}", "push", "-u", "origin", "main")

    print(json.dumps({"repository": repo, "url": f"https://github.com/{repo}", "branch": "main"}, indent=2))


if __name__ == "__main__":
    main()
