"""Vault: secrets in the OS keychain, consent before each use.

Block 5 of roadmap/07-autonomy.md.

A thin wrapper over the ``keyring`` library (Q4 A).  The recommended
backends map to the platform stores:

* macOS  → Keychain
* Linux  → Secret Service (GNOME Keyring / KDE Wallet)
* Windows → Credential Manager

For tests the fake backend is activated so the real keychain is never
touched.  Values never go to disk under ``APP_DIR``, never into
``widget.json``, never into logs, never into the bubble, and never into
a model prompt.

Usage::

    set_secret("github-token", "ghp_...")          # stores the secret
    value = get_secret("github-token", decision)    # needs decision
    delete_secret("github-token", decision)         # needs decision
    ids = list_secret_ids()                         # ["github-token"]
"""

import json
import os
import threading
from typing import TYPE_CHECKING

import keyring
from keyring.backend import KeyringBackend

from botwidget.config import APP_DIR
from botwidget.confirm import Decision

if TYPE_CHECKING:
    pass

# ── Fake backend for tests ──────────────────────────────────────────

class _FakeKeyring(KeyringBackend):
    """In-memory keyring that stores values in a dict.

    Thread-safe: every access is protected by ``_lock``.
    """

    priority = 1

    def __init__(self):
        super().__init__()
        self._store: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def set_password(self, service: str, username: str, password: str) -> None:
        with self._lock:
            self._store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        with self._lock:
            return self._store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        with self._lock:
            self._store.pop((service, username), None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Module-level fake; tests activate it via ``_activate_fake``.
_fake = _FakeKeyring()
_real_backend: keyring.backend.KeyringBackend | None = None


def _activate_fake() -> None:
    """Swap in the fake backend so tests never touch the OS keychain."""
    global _fake, _real_backend
    _real_backend = keyring.get_keyring()
    keyring.set_keyring(_fake)


def _restore_real() -> None:
    """Restore the real backend (for live smoke or teardown)."""
    global _fake, _real_backend
    if _real_backend is not None:
        keyring.set_keyring(_real_backend)
        _real_backend = None
    _fake = _FakeKeyring()


# ── Secret ID tracking ──────────────────────────────────────────────

# We keep a lightweight index of secret IDs under APP_DIR so
# ``list_secret_ids`` works without scanning the keyring.
# The file is never committed (it lives in APP_DIR).
# Never the working directory: an empty BOT_WIDGET_APP_DIR once left vault_ids.json in the checkout.
_SECRET_IDS_PATH = os.path.join(os.environ.get("BOT_WIDGET_APP_DIR") or APP_DIR, "vault_ids.json")

_ids_lock = threading.Lock()


def _load_ids() -> set[str]:
    try:
        with open(_SECRET_IDS_PATH) as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return {str(item) for item in data if item}
    except (OSError, ValueError):
        pass
    return set()


def _save_ids(ids: set[str]) -> None:
    try:
        folder = os.path.dirname(_SECRET_IDS_PATH)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(_SECRET_IDS_PATH, "w") as fh:
            json.dump(sorted(ids), fh)
    except OSError:
        pass


def _register_id(secret_id: str) -> None:
    with _ids_lock:
        ids = _load_ids()
        ids.add(secret_id)
        _save_ids(ids)


def _unregister_id(secret_id: str) -> None:
    with _ids_lock:
        ids = _load_ids()
        ids.discard(secret_id)
        _save_ids(ids)


# ── Public API ──────────────────────────────────────────────────────

VAULT_SERVICE = "botwidget.vault"


def set_secret(secret_id: str, value: str) -> None:
    """Store *value* under *secret_id* in the keychain.

    No confirm is needed for setting — the caller (usually the face)
    is responsible for having obtained consent through the confirm
    primitive before calling this.
    """
    keyring.set_password(VAULT_SERVICE, secret_id, value)
    _register_id(secret_id)


def get_secret(secret_id: str, decision: Decision | None = None) -> str | None:
    """Return the secret value, but only if a matching ``vault`` confirm was accepted.

    *decision* is the ``Decision`` returned by ``ConfirmBoard.decide``.
    The confirm payload must reference *secret_id* (e.g. ``"Read secret github-token"``),
    and the secret is only returned when the secret_id matches what the user agreed to read.
    Without an accepted decision the secret is not returned (``None``).

    A declined or expired request is logged (by the confirm board)
    without the secret value.
    """
    if decision is None or not decision.accepted:
        return None
    req = decision.request
    if req is None or req.kind != "vault":
        return None
    # The confirm payload should name the secret id — e.g. "Read secret my-key".
    # Only return the secret when the payload mentions this secret_id.
    if secret_id not in req.payload:
        return None
    try:
        return keyring.get_password(VAULT_SERVICE, secret_id)
    except Exception:
        return None


def delete_secret(secret_id: str, decision: Decision | None = None, *, confirmed: bool = False) -> None:
    """Delete the secret, but only if a ``vault`` confirm decision was accepted.

    *confirmed* is a flag for callers that have already obtained consent
    through the confirm primitive (e.g. an ``on_yes`` callback).  When
    *confirmed* is ``True`` the decision gate is skipped.
    """
    if not confirmed and (decision is None or not decision.accepted):
        return
    keyring.delete_password(VAULT_SERVICE, secret_id)
    _unregister_id(secret_id)


def list_secret_ids() -> list[str]:
    """Return the secret IDs stored in the vault.

    Only IDs are returned — no values, no secrets, no tokens.
    """
    with _ids_lock:
        return sorted(_load_ids())
