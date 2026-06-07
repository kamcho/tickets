"""Text helpers for DB storage and display."""


def strip_non_bmp(text):
    """
    Remove characters outside the Basic Multilingual Plane (e.g. emoji).

    MySQL ``utf8`` (3-byte) columns reject 4-byte UTF-8 such as 🎫.
    Use ``utf8mb4`` in production; this keeps saves working until tables are migrated.
    """
    if not text:
        return text
    return ''.join(ch for ch in str(text) if ord(ch) <= 0xFFFF)
