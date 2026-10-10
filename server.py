
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP


# --------------------------------------------------
# 1. ENVIRONMENT CONFIGURATION
# --------------------------------------------------

# Load .env from the same directory as this file.
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
API_BASE = "https://api.github.com"
API_VERSION = os.getenv("GITHUB_API_VERSION", "2026-03-10")

# Choose "stdio" for local clients or "http" for remote hosting.
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio").lower()

mcp = FastMCP("GitHub Repository Assistant")


# --------------------------------------------------
# 2. GITHUB API HELPER
# --------------------------------------------------

def github_get(path: str, params: dict | None = None):
    """Make an authenticated GitHub API GET request."""

    if not GITHUB_TOKEN:
        raise ValueError(
            "GITHUB_TOKEN is missing. Configure it in your "
            "local .env file or your cloud environment variables."
        )

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": API_VERSION,
    }

    try:
        response = httpx.get(
            f"{API_BASE}{path}",
            headers=headers,
            params=params,
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code

        if status == 401:
            message = "Authentication failed. Check your GitHub token."
        elif status == 403:
            message = (
                "Access denied or API rate limit reached. "
                "Check token permissions and rate limits."
            )
        elif status == 404:
            message = (
                "Repository or resource not found. Check its owner, "
                "name, and access permissions."
            )
        else:
            message = f"GitHub API returned HTTP {status}."

        raise ValueError(message) from exc

    except httpx.RequestError as exc:
        raise ValueError(f"Could not connect to GitHub: {exc}") from exc


# --------------------------------------------------
# 3. REPOSITORY VALIDATION
# --------------------------------------------------

def repository_path(owner: str, repo: str) -> str:
    """Validate repository identifiers before creating an API path."""

    pattern = re.compile(r"^[A-Za-z0-9_.-]+$")

    if (
        not pattern.fullmatch(owner)
        or not pattern.fullmatch(repo)
        or owner in {".", ".."}
        or repo in {".", ".."}
    ):
        raise ValueError("Invalid GitHub owner or repository name.")

    return f"/repos/{owner}/{repo}"


# --------------------------------------------------
# 4. MCP TOOL: REPOSITORY INFORMATION
# --------------------------------------------------

@mcp.tool
def get_repository_info(owner: str, repo: str) -> dict:
    """Get repository description, URL, language, stars and open issue count."""

    data = github_get(repository_path(owner, repo))

    return {
        "name": data["full_name"],
        "description": data.get("description"),
        "url": data["html_url"],
        "language": data.get("language"),
        "stars": data["stargazers_count"],
        "open_issues_count": data["open_issues_count"],
        "default_branch": data["default_branch"],
        "private": data["private"],
    }


# --------------------------------------------------
# 5. MCP TOOL: LIST ISSUES
# --------------------------------------------------

@mcp.tool
def list_issues(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 10,
) -> list[dict]:
    """List repository issues. State can be open, closed, or all."""

    if state not in {"open", "closed", "all"}:
        raise ValueError("State must be open, closed, or all.")

    if not 1 <= limit <= 50:
        raise ValueError("Limit must be between 1 and 50.")

    data = github_get(
        f"{repository_path(owner, repo)}/issues",
        {
            "state": state,
            "per_page": limit,
            "sort": "created",
            "direction": "desc",
        },
    )

    # GitHub's issues endpoint also returns pull requests.
    return [
        {
            "number": issue["number"],
            "title": issue["title"],
            "state": issue["state"],
            "author": issue["user"]["login"],
            "labels": [label["name"] for label in issue["labels"]],
            "url": issue["html_url"],
            "created_at": issue["created_at"],
        }
        for issue in data
        if "pull_request" not in issue
    ]


# --------------------------------------------------
# 6. MCP TOOL: LIST PULL REQUESTS
# --------------------------------------------------

@mcp.tool
def list_pull_requests(
    owner: str,
    repo: str,
    state: str = "open",
    limit: int = 10,
) -> list[dict]:
    """List pull requests with their source and target branches."""

    if state not in {"open", "closed", "all"}:
        raise ValueError("State must be open, closed, or all.")

    if not 1 <= limit <= 50:
        raise ValueError("Limit must be between 1 and 50.")

    data = github_get(
        f"{repository_path(owner, repo)}/pulls",
        {
            "state": state,
            "per_page": limit,
            "sort": "created",
            "direction": "desc",
        },
    )

    return [
        {
            "number": pr["number"],
            "title": pr["title"],
            "state": pr["state"],
            "author": pr["user"]["login"],
            "source_branch": pr["head"]["ref"],
            "target_branch": pr["base"]["ref"],
            "draft": pr["draft"],
            "url": pr["html_url"],
            "created_at": pr["created_at"],
        }
        for pr in data
    ]


# --------------------------------------------------
# 7. MCP TOOL: RECENT COMMITS
# --------------------------------------------------

@mcp.tool
def list_recent_commits(
    owner: str,
    repo: str,
    limit: int = 10,
) -> list[dict]:
    """List recent commits with SHA, message, author and date."""

    if not 1 <= limit <= 50:
        raise ValueError("Limit must be between 1 and 50.")

    data = github_get(
        f"{repository_path(owner, repo)}/commits",
        {"per_page": limit},
    )

    return [
        {
            "sha": commit["sha"],
            "short_sha": commit["sha"][:7],
            "message": commit["commit"]["message"].splitlines()[0],
            "author": (
                commit["commit"]["author"] or {}
            ).get("name"),
            "date": (
                commit["commit"]["author"] or {}
            ).get("date"),
            "url": commit["html_url"],
        }
        for commit in data
    ]


# --------------------------------------------------
# 8. SERVER STARTUP: LOCAL OR REMOTE
# --------------------------------------------------

if __name__ == "__main__":
    if MCP_TRANSPORT == "http":
        # Remote deployment: Render, another cloud host, etc.
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "8000"))

        mcp.run(
            transport="http",
            host=host,
            port=port,
        )

    elif MCP_TRANSPORT == "stdio":
        # Local MCP clients: Claude Desktop and MCP Inspector.
        mcp.run(transport="stdio")

    else:
        raise ValueError(
            "Invalid MCP_TRANSPORT. Choose 'stdio' or 'http'."
        )
