"""Resolve real GitHub PRs/branches to immutable commit SHAs. Public repos sufficient."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.config import get_settings

GITHUB_API = "https://api.github.com"


@dataclass
class ResolvedRepo:
    owner: str
    repo: str
    ref: str
    commit_sha: str
    pr_number: Optional[int]
    clone_url: str
    html_url: str
    raw: dict[str, Any]


class GitHubError(RuntimeError):
    pass


def parse_github_url(url: str) -> dict[str, Any]:
    """
    Accept:
      https://github.com/org/repo
      https://github.com/org/repo/tree/branch
      https://github.com/org/repo/commit/sha
      https://github.com/org/repo/pull/123
      https://github.com/org/repo/pull/123/files
    """
    u = url.strip().rstrip("/")
    # strip query/fragment
    parsed = urlparse(u)
    if parsed.netloc not in ("github.com", "www.github.com"):
        raise GitHubError(f"Not a github.com URL: {url}")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise GitHubError(f"Incomplete GitHub URL: {url}")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    info: dict[str, Any] = {"owner": owner, "repo": repo, "pr_number": None, "ref": None, "commit": None}
    if len(parts) >= 4 and parts[2] == "pull":
        info["pr_number"] = int(re.sub(r"\D", "", parts[3]) or "0") or None
    elif len(parts) >= 4 and parts[2] == "tree":
        info["ref"] = "/".join(parts[3:])
    elif len(parts) >= 4 and parts[2] == "commit":
        info["commit"] = parts[3]
    elif len(parts) >= 4 and parts[2] == "blob":
        info["ref"] = parts[3]
    return info


def _headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ProofPay/0.1",
    }
    token = get_settings().github_token
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _gh(method: str, path: str, **kwargs) -> Any:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(method, f"{GITHUB_API}{path}", headers=_headers(), **kwargs)
        if resp.status_code == 404:
            raise GitHubError(f"GitHub 404: {path}")
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            raise GitHubError(
                "GitHub API rate limited. Set GITHUB_TOKEN in .env for higher limits."
            )
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub {resp.status_code}: {resp.text}")
        return resp.json()


async def resolve_github_url(url: str, default_ref: str = "main") -> ResolvedRepo:
    info = parse_github_url(url)
    owner, repo = info["owner"], info["repo"]
    pr_number = info["pr_number"]
    commit_sha: Optional[str] = info.get("commit")
    ref = info.get("ref") or default_ref

    raw: dict[str, Any] = {"parsed": info}

    if pr_number:
        pr = await _gh("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")
        raw["pr"] = pr
        commit_sha = pr["head"]["sha"]
        ref = pr["head"]["ref"]
        # Fork support: clone head repo if different
        head_repo = pr["head"]["repo"]
        if head_repo:
            owner = head_repo["owner"]["login"]
            repo = head_repo["name"]
            clone_url = head_repo["clone_url"]
            html_url = head_repo["html_url"]
        else:
            clone_url = f"https://github.com/{owner}/{repo}.git"
            html_url = f"https://github.com/{owner}/{repo}"
    else:
        if not commit_sha:
            ref_data = await _gh("GET", f"/repos/{owner}/{repo}/commits/{ref}")
            raw["commit"] = ref_data
            commit_sha = ref_data["sha"]
        clone_url = f"https://github.com/{owner}/{repo}.git"
        html_url = f"https://github.com/{owner}/{repo}"

    assert commit_sha
    return ResolvedRepo(
        owner=owner,
        repo=repo,
        ref=ref,
        commit_sha=commit_sha,
        pr_number=pr_number,
        clone_url=clone_url,
        html_url=html_url,
        raw=raw,
    )
