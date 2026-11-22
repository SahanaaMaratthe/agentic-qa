"""SharePoint / OneDrive source via Microsoft Graph (read-only).

Accepted inputs:
    any SharePoint / OneDrive sharing or browser link to a file or folder
        https://contoso.sharepoint.com/:x:/s/QA/EaBc...      https://contoso-my.sharepoint.com/...
        https://1drv.ms/...        https://onedrive.live.com/...
    sharepoint://<host>/sites/<site>/<library>/<path/to/file-or-folder>
        e.g. sharepoint://contoso.sharepoint.com/sites/QA/Shared Documents/BRDs

settings.yaml -> sources.sharepoint:
    auth: device_code     your own account: a code is shown, you sign in in the browser (token cached)
    auth: client_secret   app registration (client_id + secret_env), for unattended / CI runs
    auth: token_env / token_command
    tenant_id: <directory id or 'organizations'>
    client_id: <app registration id>
Permissions needed (read-only, delegated or application): Files.Read.All and/or Sites.Read.All
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import requests

from ..registry import register
from . import SUPPORTED_EXTS, Source, unique_path

GRAPH = "https://graph.microsoft.com/v1.0"
DELEGATED_SCOPES = ["Files.Read.All", "Sites.Read.All"]
HOST = re.compile(r"(\.sharepoint\.(com|us|de|cn)|onedrive\.live\.com|1drv\.ms)$", re.I)


def share_id(url: str) -> str:
    """Graph 'shares' id for a sharing URL: u! + unpadded base64url."""
    b = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return "u!" + b


@register("source", "sharepoint")
class SharePointSource(Source):
    priority = 20
    max_depth = 3

    def __init__(self, settings=None, session: requests.Session | None = None):
        super().__init__(settings)
        self._session = session

    def can_handle(self, uri: str) -> bool:
        if uri.startswith("sharepoint://"):
            return True
        try:
            return bool(HOST.search(urlparse(uri).hostname or ""))
        except ValueError:
            return False

    # ---------------------------------------------------------------- auth
    def _token(self) -> str:
        tok = self.static_token()
        if tok:
            return tok
        import msal

        s = self.settings
        authority = f"https://login.microsoftonline.com/{s.get('tenant_id', 'organizations')}"
        if s.get("auth") == "client_secret":
            app = msal.ConfidentialClientApplication(s["client_id"], authority=authority,
                                                     client_credential=os.environ.get(s.get("secret_env", "SP_CLIENT_SECRET")))
            res = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        else:
            cache_path = Path(s.get("token_cache", "~/.agentic_qa/msal_cache.json")).expanduser()
            cache = msal.SerializableTokenCache()
            if cache_path.exists():
                cache.deserialize(cache_path.read_text())
            app = msal.PublicClientApplication(s["client_id"], authority=authority, token_cache=cache)
            accounts = app.get_accounts()
            res = app.acquire_token_silent(DELEGATED_SCOPES, account=accounts[0]) if accounts else None
            if not res:
                flow = app.initiate_device_flow(scopes=DELEGATED_SCOPES)
                if "user_code" not in flow:
                    raise RuntimeError(f"SharePoint sign-in could not start: {flow}")
                print(flow["message"], flush=True)   # "To sign in, open https://microsoft.com/devicelogin and enter ..."
                res = app.acquire_token_by_device_flow(flow)
            if cache.has_state_changed:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(cache.serialize())
        if "access_token" not in res:
            raise RuntimeError(f"SharePoint sign-in failed: {res.get('error_description', res)}")
        return res["access_token"]

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers["Authorization"] = f"Bearer {self._token()}"
        return self._session

    def _get(self, url, stream=False):
        r = self.session.get(url, timeout=120, allow_redirects=True)
        if r.status_code == 404:
            raise RuntimeError("SharePoint: item not found, or your account has no access to it.")
        if r.status_code in (401, 403):
            raise RuntimeError(f"SharePoint: access denied ({r.status_code}). Check sign-in and the app's "
                               f"Files.Read.All / Sites.Read.All consent. {r.text[:200]}")
        r.raise_for_status()
        return r

    # ---------------------------------------------------------------- resolve
    def _resolve(self, uri: str) -> dict:
        sel = "?$select=id,name,folder,file,parentReference"
        if not uri.startswith("sharepoint://"):
            return self._get(f"{GRAPH}/shares/{share_id(uri)}/driveItem{sel}").json()
        rest = unquote(uri[len("sharepoint://"):])
        host, _, path = rest.partition("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) < 3 or parts[0] not in ("sites", "teams"):
            raise RuntimeError("Use sharepoint://<host>/sites/<site>/<library>/<path>")
        site = self._get(f"{GRAPH}/sites/{host}:/{parts[0]}/{parts[1]}").json()
        drives = self._get(f"{GRAPH}/sites/{site['id']}/drives").json().get("value", [])
        lib = parts[2]
        drive = next((d for d in drives if d["name"].lower() == lib.lower()
                      or unquote(d.get("webUrl", "")).rstrip("/").lower().endswith("/" + lib.lower())), None)
        if not drive:
            raise RuntimeError(f"SharePoint: library '{lib}' not found. Available: {[d['name'] for d in drives]}")
        inner = "/".join(parts[3:])
        url = f"{GRAPH}/drives/{drive['id']}/root" + (f":/{quote(inner)}:" if inner else "")
        return self._get(url + sel).json()

    def _children(self, drive_id, item_id):
        url, out = f"{GRAPH}/drives/{drive_id}/items/{item_id}/children?$select=id,name,folder,file,parentReference", []
        while url:
            data = self._get(url).json()
            out += data.get("value", [])
            url = data.get("@odata.nextLink")
        return out

    def fetch(self, uri: str, dest: Path) -> list[tuple[Path, str]]:
        dest.mkdir(parents=True, exist_ok=True)
        return self._fetch_item(self._resolve(uri), dest, "", 0)

    def _fetch_item(self, item, dest, prefix, depth):
        drive_id = item["parentReference"]["driveId"]
        if "folder" in item:
            if depth >= self.max_depth:
                return []
            got = []
            for child in sorted(self._children(drive_id, item["id"]), key=lambda c: c["name"]):
                child.setdefault("parentReference", {})["driveId"] = child.get("parentReference", {}).get("driveId", drive_id)
                got += self._fetch_item(child, dest, f"{prefix}{item['name']}/", depth + 1)
            return got
        if Path(item["name"]).suffix.lower() not in SUPPORTED_EXTS:
            return []
        data = self._get(f"{GRAPH}/drives/{drive_id}/items/{item['id']}/content").content
        path = unique_path(dest, item["name"])
        path.write_bytes(data)
        return [(path, f"SharePoint: {prefix}{item['name']}")]
