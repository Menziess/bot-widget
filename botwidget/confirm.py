"""Confirm primitive: show the exact payload, act only after an explicit yes for that hash.

Toolkit-free logic. No PySide6 import.

Kinds: feedback, action, vault, routine.
feedback and vault never get Always allow.

Usage::

    board = ConfirmBoard()
    req = board.put(bot_id, "action", payload, ttl=600)
    decision = board.decide(bot_id, "yes", payload=payload, request_id=req.id)
    if decision.accepted:
        callback()
    blocks = board.blocks(req)  # -> list of bubble blocks
"""

import hashlib
import json
import os
import time

from botwidget.markdown import actions_block, code_block, plain_block, text_block

# The kinds that must never record always-allow.
_NO_ALWAYS_KINDS = frozenset(("feedback", "vault"))


def payload_hash(payload: str) -> str:
    """SHA-256 hex digest of the UTF-8 payload."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ConfirmRequest:
    """A pending confirm request stored on the board."""

    __slots__ = ("id", "bot_id", "kind", "payload", "hash", "callback",
                 "ttl", "expires", "always_allowed", "settled")

    def __init__(self, id: str, bot_id: str, kind: str, payload: str,
                 hash: str, callback: str | None, ttl: int,
                 expires: float, always_allowed: bool):
        self.id = id
        self.bot_id = bot_id
        self.kind = kind
        self.payload = payload
        self.hash = hash
        self.callback = callback
        self.ttl = ttl
        self.expires = expires
        self.always_allowed = always_allowed
        self.settled = False

    def expired(self, now: float | None = None) -> bool:
        return (now or time.monotonic()) >= self.expires

    def __repr__(self) -> str:
        return f"ConfirmRequest({self.id!r}, {self.kind!r}, {self.payload!r})"


class Decision:
    """Result of a decide call."""

    __slots__ = ("accepted", "reason", "always_allowed", "request")

    def __init__(self, accepted: bool, reason: str,
                 always_allowed: bool = False, request: ConfirmRequest | None = None):
        self.accepted = accepted
        self.reason = reason
        self.always_allowed = always_allowed
        self.request = request

    def __repr__(self) -> str:
        return f"Decision(accepted={self.accepted}, reason={self.reason!r})"


class ConfirmBoard:
    """One pending confirm per bot id."""

    def __init__(self, record_path: str | None = None):
        self._requests: dict[str, ConfirmRequest] = {}  # request_id -> request
        self._by_bot: dict[str, ConfirmRequest] = {}    # bot_id -> current request
        self.record_path = record_path  # if set, log here; otherwise harness.approvals

    # ── Public API ──────────────────────────────────────────────

    def put(self, bot_id: str, kind: str, payload: str,
            *, ttl: int = 600, always: bool = False,
            now: float | None = None) -> ConfirmRequest:
        """Store a confirm request for *bot_id*, replacing any existing one.

        *always* is silently ignored for *feedback* and *vault* kinds.
        """
        now_ts = now or time.monotonic()
        # Settle any existing request for this bot before replacing it.
        existing = self._by_bot.get(bot_id)
        if existing and not existing.settled:
            self._settle(existing, "replaced")
            self._record(existing, "replaced", bot_id)
        h = payload_hash(payload)
        # Determine always-allow: forbidden for feedback/vault.
        allowed = always and kind not in _NO_ALWAYS_KINDS
        req = ConfirmRequest(
            id=_new_id(),
            bot_id=bot_id,
            kind=kind,
            payload=payload,
            hash=h,
            callback=None,
            ttl=ttl,
            expires=now_ts + ttl,
            always_allowed=allowed,
        )
        self._requests[req.id] = req
        self._by_bot[bot_id] = req
        return req

    def get(self, bot_id: str) -> ConfirmRequest | None:
        """The current pending request for *bot_id*, or None."""
        return self._by_bot.get(bot_id)

    def decide(self, bot_id: str, decision: str,
               *, payload: str | None = None,
               request_id: str | None = None,
               now: float | None = None) -> Decision:
        """Process a user decision: 'yes' or 'no'.

        Returns a Decision with accepted/reason.
        """
        now_ts = now or time.monotonic()
        req = self._by_bot.get(bot_id)
        if req is None:
            return Decision(False, "no_request")
        # If a request_id was given and it doesn't match the current one, refuse.
        if request_id is not None and request_id != req.id:
            return Decision(False, "no_request")

        # If settled (declined, expired, or already accepted), refuse.
        if req.settled:
            return Decision(False, "no_request")

        # Expired?
        if req.expired(now_ts):
            self._settle(req, "expired")
            self._record(req, "expired", bot_id)
            return Decision(False, "expired", request=req)

        if decision == "no":
            self._settle(req, "declined")
            self._record(req, "declined", bot_id)
            return Decision(False, "declined", request=req)

        if decision != "yes":
            return Decision(False, "no_request")

        # Yes: check payload hash. If no payload given but we have the request's own, use it.
        check_payload = payload if payload is not None else req.payload
        if payload_hash(check_payload) != req.hash:
            return Decision(False, "mismatch", request=req)

        # A second yes on this same request is already refused above (settled).
        # A later put with the same payload is a new request and may be accepted again.
        self._settle(req, "accepted")
        self._record(req, "accepted", bot_id)
        return Decision(True, "accepted", always_allowed=req.always_allowed, request=req)

    def blocks(self, request: ConfirmRequest) -> list:
        """Bubble blocks for the request: heading, payload in a code block, and actions."""
        blocks = [text_block(15, 0, "", False, [("Confirm", "b")]),
                  plain_block("gap")]
        lines = request.payload.split("\n")
        blocks.append(code_block(lines if lines else [""]))
        blocks.append(plain_block("gap"))
        # Commands: confirm/<id>/yes and confirm/<id>/no
        actions = [("Yes", f"confirm/{request.id}/yes"),
                   ("No", f"confirm/{request.id}/no")]
        blocks.append(actions_block(actions))
        return blocks

    def blocks_for_bot(self, bot_id: str) -> list:
        """Return blocks for the current confirm on *bot_id*, or []."""
        req = self._by_bot.get(bot_id)
        if req is None or req.settled:
            return []
        return self.blocks(req)

    # ── Internal ────────────────────────────────────────────────

    @staticmethod
    def _settle(req: ConfirmRequest, reason: str) -> None:
        req.settled = True

    def _record(self, req: ConfirmRequest, decision: str, by: str) -> None:
        path = self.record_path
        if path is not None:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            entry = json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "request": req.payload,
                                "decision": decision, "source": "confirm", "by": by}) + "\n"
            with open(path, "a") as fh:
                fh.write(entry)
            return
        from harness import approvals
        approvals.record(req.payload, decision, "confirm", by)


def _new_id() -> str:
    """A short random id for a confirm request."""
    import secrets
    return secrets.token_hex(6)
