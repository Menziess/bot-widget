"""Join streamed answer pieces so the bubble shows the model's final text once."""

import re

# A skill ending the model wrote as words. The bubble's italic markdown eats _for_, so
# not_for_me twice, glued, reads as notformenotforme.
_SENTINEL = re.compile(r"(?:not_for_me|NOT_FOR_ME|notforme)+$")


def fold_chunk(current: str, chunk: str) -> str:
    """The answer after one more piece.

    A piece that already starts with the answer is a longer copy and replaces it.
    A piece equal to the answer was sent again and is ignored.
    A trailing not_for_me echo is not part of the answer.
    """
    if not chunk:
        return current
    if not current or chunk.startswith(current):
        merged = chunk
    else:
        merged = current + chunk
    return _SENTINEL.sub("", merged)
