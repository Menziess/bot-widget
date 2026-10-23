"""An outbox for bubble messages: a message is only sent once the POST succeeded."""

RETRY_S = (1, 2, 5, 10, 15)


class Outbox:
    """Messages waiting for OpenBot.

    A transient failure keeps the message and its clientMessageId, so a retry
    cannot arrive twice; a refusal drops it. The caller waits RETRY_S seconds.
    """

    def __init__(self):
        self.items = []

    def add(self, text: str, cid: str):
        self.items.append({"text": text, "cid": cid, "tries": 0})

    def current(self) -> dict | None:
        return self.items[0] if self.items else None

    def sent(self, cid: str) -> dict | None:
        """Forget a delivered message and return it."""
        item = next((i for i in self.items if i["cid"] == cid), None)
        if item is not None:
            self.items.remove(item)
        return item

    def failed(self, cid: str, retryable: bool) -> int | None:
        """Wait in seconds before a retry, or None when the message is dropped."""
        item = next((i for i in self.items if i["cid"] == cid), None)
        if item is None:
            return None
        if not retryable:
            self.sent(cid)
            return None
        wait = RETRY_S[min(item["tries"], len(RETRY_S) - 1)]
        item["tries"] += 1
        return wait
