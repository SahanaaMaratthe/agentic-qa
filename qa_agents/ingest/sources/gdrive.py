"""Google Drive source (files, folders, shared drives, Google Docs/Sheets exported to .docx/.xlsx).

Accepted inputs:
    https://drive.google.com/file/d/<id>/view
    https://drive.google.com/open?id=<id>
    https://drive.google.com/drive/folders/<id>
    https://docs.google.com/document/d/<id>/edit     (exported as .docx)
    https://docs.google.com/spreadsheets/d/<id>/edit (exported as .xlsx)
    gdrive://<id>

settings.yaml -> sources.gdrive.auth:
    adc              Application Default Credentials. Your own account:
                       gcloud auth application-default login --scopes=https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform
    oauth            Browser sign-in with an OAuth client file (client_secrets: path); token cached locally
    service_account  key_file: path to a service-account JSON key (files must be shared with that account)
    token_env / token_command   bring your own access token
Only the read-only scope is ever requested.
"""
from __future__ import annotations

import re
from pathlib import Path

import requests

from ..registry import register
from . import SUPPORTED_EXTS, Source, unique_path

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
API = "https://www.googleapis.com/drive/v3"
FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
}

_PATTERNS = [
    re.compile(r"^gdrive://(?P<id>[\w-]{10,})"),
    re.compile(r"drive\.google\.com/(?:file/d|drive/(?:u/\d+/)?folders)/(?P<id>[\w-]{10,})"),
    re.compile(r"drive\.google\.com/(?:open|uc)\?(?:.*&)?id=(?P<id>[\w-]{10,})"),
    re.compile(r"docs\.google\.com/(?:document|spreadsheets|presentation)/d/(?P<id>[\w-]{10,})"),
]


def parse_drive_id(uri: str) -> str | None:
    for p in _PATTERNS:
        m = p.search(uri)
        if m:
            return m.group("id")
    return None


@register("source", "gdrive")
class GoogleDriveSource(Source):
    priority = 10
    max_depth = 3

    def __init__(self, settings=None, session: requests.Session | None = None):
        super().__init__(settings)
        self._session = session

    def can_handle(self, uri: str) -> bool:
        return parse_drive_id(uri) is not None

    # ---------------------------------------------------------------- auth
    def _token(self) -> str:
        tok = self.static_token()
        if tok:
            return tok
        mode = self.settings.get("auth", "adc")
        from google.auth.transport.requests import Request

        if mode == "service_account":
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(self.settings["key_file"], scopes=SCOPES)
        elif mode == "oauth":
            creds = self._oauth_creds()
        else:
            import google.auth

            creds, _ = google.auth.default(scopes=SCOPES)
        if not creds.valid:
            creds.refresh(Request())
        return creds.token

    def _oauth_creds(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        cache = Path(self.settings.get("token_cache", "~/.agentic_qa/gdrive_token.json")).expanduser()
        creds = None
        if cache.exists():
            creds = Credentials.from_authorized_user_file(str(cache), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds or not creds.valid:
            from google_auth_oauthlib.flow import InstalledAppFlow

            flow = InstalledAppFlow.from_client_secrets_file(self.settings["client_secrets"], SCOPES)
            creds = flow.run_local_server(port=0)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(creds.to_json(), encoding="utf-8")
        return creds

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers["Authorization"] = f"Bearer {self._token()}"
        return self._session

    # ---------------------------------------------------------------- API
    def _get(self, url, **params):
        params.setdefault("supportsAllDrives", "true")
        r = self.session.get(url, params=params, timeout=120)
        if r.status_code == 404:
            raise RuntimeError("Google Drive: file not found, or your account has no access to it.")
        if r.status_code in (401, 403):
            raise RuntimeError(f"Google Drive: access denied ({r.status_code}). Check sign-in / sharing. {r.text[:200]}")
        r.raise_for_status()
        return r

    def _meta(self, fid):
        return self._get(f"{API}/files/{fid}", fields="id,name,mimeType,shortcutDetails").json()

    def _children(self, fid):
        token, out = None, []
        while True:
            params = {"q": f"'{fid}' in parents and trashed=false", "fields": "nextPageToken,files(id,name,mimeType,shortcutDetails)",
                      "pageSize": 200, "includeItemsFromAllDrives": "true"}
            if token:
                params["pageToken"] = token
            data = self._get(f"{API}/files", **params).json()
            out += data.get("files", [])
            token = data.get("nextPageToken")
            if not token:
                return out

    def fetch(self, uri: str, dest: Path) -> list[tuple[Path, str]]:
        dest.mkdir(parents=True, exist_ok=True)
        return self._fetch_item(self._meta(parse_drive_id(uri)), dest, "", 0)

    def _fetch_item(self, meta, dest, prefix, depth):
        mime = meta.get("mimeType", "")
        if mime == SHORTCUT:
            meta = self._meta(meta["shortcutDetails"]["targetId"])
            mime = meta.get("mimeType", "")
        name = meta["name"]
        if mime == FOLDER:
            if depth >= self.max_depth:
                return []
            got = []
            for child in sorted(self._children(meta["id"]), key=lambda c: c["name"]):
                got += self._fetch_item(child, dest, f"{prefix}{name}/", depth + 1)
            return got
        if mime in EXPORTS:
            export_mime, ext = EXPORTS[mime]
            data = self._get(f"{API}/files/{meta['id']}/export", mimeType=export_mime).content
            filename = name + ext
        else:
            if Path(name).suffix.lower() not in SUPPORTED_EXTS:
                return []
            data = self._get(f"{API}/files/{meta['id']}", alt="media").content
            filename = name
        path = unique_path(dest, filename)
        path.write_bytes(data)
        return [(path, f"Drive: {prefix}{filename}")]
