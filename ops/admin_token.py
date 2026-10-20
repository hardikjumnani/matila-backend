"""Mint a short-lived admin Firebase ID token for the local AdminPanel gateway.

Local operator tool. Prints ONE line of JSON to stdout and exits 0 on success:

    {"id_token": "<jwt>", "expires_at": <unix seconds>, "email": "<admin email>"}

On failure it prints a single human-readable line to stderr (never a secret or a
stack trace) and exits non-zero.

It is fully non-interactive (no browser, no email link): it signs in as the admin
using the Firebase service account that is already on this machine, then exchanges
a custom token for an ID token via Firebase Identity Toolkit. The public Web API
key is auto-discovered via the Firebase Management API, so no extra config is
needed. The token is printed only to stdout; nothing is written to disk.

Config (environment, falling back to the Backend ``.env`` next to this repo):
  - FIREBASE_CREDENTIALS_PATH : service-account JSON (required).
  - MATILA_ADMIN_EMAIL        : admin email to sign in as (default below).
  - FIREBASE_WEB_API_KEY      : optional; auto-discovered when unset.
  - FIREBASE_PROJECT_ID       : optional; defaults to the service account's project.

Run with ``python -I`` for isolation. Intended to be invoked by the AdminPanel
gateway via ``MATILA_TOKEN_COMMAND`` (no shell).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_DEFAULT_ADMIN_EMAIL = "hardik.jumnani123@gmail.com"
_IDENTITY_TOOLKIT = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={key}"
)
_FIREBASE_MGMT = "https://firebase.googleapis.com/v1beta1/projects/{project}"
_HTTP_TIMEOUT = 20


class _HelperError(Exception):
    """A clean, user-facing failure (message is safe to show, carries no secret)."""


def _load_env_file(path: Path) -> dict[str, str]:
    """Minimal ``.env`` reader (KEY=VALUE lines). Never overrides real env vars."""
    values: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def _config(key: str, file_values: dict[str, str], default: str = "") -> str:
    return os.environ.get(key) or file_values.get(key) or default


def _http_json(url: str, *, data: dict | None = None, bearer: str = "") -> dict:
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
        detail = ""
        try:
            detail = json.loads(exc.read().decode()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            detail = ""
        suffix = f": {detail}" if detail else ""
        raise _HelperError(
            f"Google API HTTP {exc.code}{suffix} ({url.split('?')[0]})"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover
        reason = getattr(exc, "reason", exc)
        raise _HelperError(f"network error reaching Google: {reason}") from exc
    except json.JSONDecodeError as exc:  # pragma: no cover
        raise _HelperError("unexpected non-JSON response from Google") from exc


def _discover_web_api_key(project: str, access_token: str) -> str:
    base = _FIREBASE_MGMT.format(project=project)
    apps = _http_json(f"{base}/webApps", bearer=access_token).get("apps", [])
    if not apps:
        raise _HelperError(
            "no Firebase Web App registered on the project; set FIREBASE_WEB_API_KEY"
        )
    app_id = apps[0]["appId"]
    config = _http_json(f"{base}/webApps/{app_id}/config", bearer=access_token)
    key = config.get("apiKey")
    if not key:
        raise _HelperError("Web App config did not include an apiKey")
    return key


def _mint() -> dict:
    here = Path(__file__).resolve()
    env_values = _load_env_file(here.parent.parent / ".env")

    cred_path = _config("FIREBASE_CREDENTIALS_PATH", env_values)
    if not cred_path:
        raise _HelperError("FIREBASE_CREDENTIALS_PATH is not set")
    if not Path(cred_path).is_file():
        raise _HelperError(f"service-account file not found: {cred_path}")

    admin_email = _config("MATILA_ADMIN_EMAIL", env_values, _DEFAULT_ADMIN_EMAIL)

    # Imported lazily so a config error above fails fast with a clean message.
    try:
        import firebase_admin
        from firebase_admin import auth, credentials
        import google.auth.transport.requests
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover
        raise _HelperError("missing dependency; run this with the backend venv") from exc

    cred = credentials.Certificate(cred_path)
    app = firebase_admin.initialize_app(cred, name="admin_token_helper")
    try:
        try:
            user = auth.get_user_by_email(admin_email, app=app)
        except Exception as exc:  # noqa: BLE001 - firebase raises many subclasses
            raise _HelperError(f"no Firebase user for {admin_email}") from exc

        custom_token = auth.create_custom_token(user.uid, app=app).decode()
        project = _config("FIREBASE_PROJECT_ID", env_values) or app.project_id

        api_key = _config("FIREBASE_WEB_API_KEY", env_values)
        if not api_key:
            sa = service_account.Credentials.from_service_account_file(
                cred_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            sa.refresh(google.auth.transport.requests.Request())
            api_key = _discover_web_api_key(project, sa.token)

        exchanged = _http_json(
            _IDENTITY_TOOLKIT.format(key=api_key),
            data={"token": custom_token, "returnSecureToken": True},
        )
        id_token = exchanged.get("idToken")
        expires_in = int(exchanged.get("expiresIn", "3600"))
        if not id_token:
            raise _HelperError("token exchange did not return an idToken")

        return {
            "id_token": id_token,
            "expires_at": int(time.time()) + expires_in,
            "email": user.email or admin_email,
        }
    finally:
        firebase_admin.delete_app(app)


def main() -> int:
    try:
        result = _mint()
    except _HelperError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - never leak a stack trace to the caller
        print("unexpected error minting the admin token", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
