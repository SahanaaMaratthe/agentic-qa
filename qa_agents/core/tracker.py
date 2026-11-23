"""Bug-tracker adapters used by Defect Manager.

    tracker:
      type: markdown | jira
      file_bugs: false     # false = draft only (always written locally); true = create tickets

Add Azure DevOps / GitHub Issues / ServiceNow by subclassing BugTracker.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from .models import BugReport


def render_markdown(b: BugReport) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(b.steps_to_reproduce, 1))
    checks = "\n".join(f"- {c}" for c in b.failed_checks)
    cites = f"\n**Citations returned:** {', '.join(b.citations_returned)}\n" if b.citations_returned else ""
    shots = "\n".join(f"![{Path(a).name}]({Path(a).as_posix()})" for a in b.attachments)
    evidence = f"\n## Evidence (screenshots)\n{shots}\n" if shots else ""
    return f"""# {b.id}: {b.title}

| Field | Value |
|---|---|
| Severity | {b.severity} |
| Classification | {b.classification.value} |
| Suspected root cause | {b.suspected_root_cause} |
| Use case | {b.usecase_id} |
| Test case(s) | {', '.join(b.test_ids)} |
| Persona | {b.persona} |
| Tracker key | {b.tracker_key or '-'} |

## Summary
{b.summary}

## Steps to reproduce
{steps}

## Expected
{b.expected}

## Actual
{b.actual}
{cites}
## Failed checks
{checks}

## Recommendation
{b.recommendation}
{evidence}"""


class BugTracker:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def find_duplicate(self, bug: BugReport) -> str | None:
        return None

    def create(self, bug: BugReport) -> str | None:
        raise NotImplementedError


class MarkdownTracker(BugTracker):
    """Default: no external system, bug drafts are the markdown files written by Defect Manager."""

    def create(self, bug):
        return None


class JiraTracker(BugTracker):
    """Jira Cloud or Server/DC via REST API v2.

    tracker:
      type: jira
      base_url: https://yourorg.atlassian.net
      project_key: QA
      issue_type: Bug
      email_env: JIRA_EMAIL          # Cloud: email + API token (basic auth)
      token_env: JIRA_API_TOKEN      # Server/DC: set email_env to null to use Bearer PAT
      severity_to_priority: {Critical: Highest, High: High, Medium: Medium, Low: Low}
      extra_fields: {components: [{name: "Gemini Agents"}]}
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.base = cfg["base_url"].rstrip("/")
        self.s = requests.Session()
        token = os.environ.get(cfg.get("token_env", "JIRA_API_TOKEN"), "")
        email_env = cfg.get("email_env", "JIRA_EMAIL")
        if email_env:
            self.s.auth = (os.environ.get(email_env, ""), token)
        else:
            self.s.headers["Authorization"] = f"Bearer {token}"
        self.s.headers["Content-Type"] = "application/json"

    def find_duplicate(self, bug):
        # fingerprint label = test id; an open bug with the same label is a duplicate
        jql = (f'project = "{self.cfg["project_key"]}" AND labels = "{bug.test_ids[0]}" '
               f'AND statusCategory != Done')
        params = {"jql": jql, "maxResults": 1, "fields": "key"}
        # Jira Cloud: /rest/api/3/search/jql ; Server/DC (and older Cloud): /rest/api/2/search
        for path in ("/rest/api/3/search/jql", "/rest/api/2/search"):
            r = self.s.get(f"{self.base}{path}", params=params)
            if r.ok:
                issues = r.json().get("issues") or []
                return issues[0]["key"] if issues else None
        raise RuntimeError(f"Jira duplicate search failed ({r.status_code}): {r.text[:300]}")

    def create(self, bug):
        dup = self.find_duplicate(bug)
        if dup:
            self.s.post(f"{self.base}/rest/api/2/issue/{dup}/comment",
                        json={"body": f"Reproduced again by agentic-qa run ({bug.id}).\n\nActual:\n{bug.actual}"})
            return dup
        prio_map = self.cfg.get("severity_to_priority") or {}
        fields = {
            "project": {"key": self.cfg["project_key"]},
            "issuetype": {"name": self.cfg.get("issue_type", "Bug")},
            "summary": f"[{bug.usecase_id}] {bug.title}"[:250],
            "description": render_markdown(bug),
            "labels": sorted(set(bug.labels + bug.test_ids + ["agentic-qa"])),
            **(self.cfg.get("extra_fields") or {}),
        }
        if bug.severity in prio_map:
            fields["priority"] = {"name": prio_map[bug.severity]}
        r = self.s.post(f"{self.base}/rest/api/2/issue", json={"fields": fields})
        if not r.ok:
            raise RuntimeError(f"Jira create failed {r.status_code}: {r.text[:500]}")
        key = r.json()["key"]
        self.attach(key, bug.attachments)
        return key

    def attach(self, key: str, files: list[str]) -> None:
        """Upload screenshots to the ticket (Jira needs the X-Atlassian-Token header for uploads)."""
        for f in files[: int(self.cfg.get("max_attachments", 5))]:
            p = Path(f)
            if not p.exists():
                continue
            with p.open("rb") as fh:
                self.s.post(f"{self.base}/rest/api/2/issue/{key}/attachments",
                            headers={"X-Atlassian-Token": "no-check", "Content-Type": None},
                            files={"file": (p.name, fh, "image/png")})


TRACKERS = {"markdown": MarkdownTracker, "jira": JiraTracker}


def build_tracker(cfg: dict) -> BugTracker:
    t = cfg.get("type", "markdown")
    if t not in TRACKERS:
        raise ValueError(f"Unknown tracker '{t}'. Options: {list(TRACKERS)}")
    return TRACKERS[t](cfg)
