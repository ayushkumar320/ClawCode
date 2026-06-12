"""Idempotent PR creation against GitHub via PyGithub."""

from __future__ import annotations

import asyncio
import logging

from github import Github, GithubException
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from gh.exceptions import PRError

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=1),
    retry=retry_if_exception_type(PRError),
    reraise=True,
)
async def open_pr(
    slug: str,
    *,
    head: str,
    base: str,
    title: str,
    body: str,
    token: str,
) -> str:
    """Open a PR; if one already exists for ``head`` → ``base``, return its URL."""
    if not token:
        raise PRError("missing GitHub token")
    if head == base:
        raise PRError(f"head and base are identical: {head!r}")

    def _open() -> str:
        gh = Github(token)
        repo = gh.get_repo(slug)
        existing = list(repo.get_pulls(state="open", head=_qualified_head(slug, head), base=base))
        if existing:
            logger.info("PR already open for %s -> %s: %s", head, base, existing[0].html_url)
            return existing[0].html_url
        pr = repo.create_pull(title=title, body=body, head=head, base=base)
        logger.info("opened PR %s for %s -> %s", pr.html_url, head, base)
        return pr.html_url

    try:
        return await asyncio.to_thread(_open)
    except GithubException as exc:
        raise PRError(f"GitHub API error opening PR for {slug}: {exc.data}") from exc


def _qualified_head(slug: str, head: str) -> str:
    """Return the ``owner:branch`` form GitHub's API expects for the head filter."""
    owner = slug.split("/", 1)[0]
    return head if ":" in head else f"{owner}:{head}"
