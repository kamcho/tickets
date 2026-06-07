"""Clean and normalize assistant replies for customer-facing chat."""
import re


def format_assistant_reply(text):
    """Strip markdown emphasis and normalize whitespace; keep emoji structure."""
    if not text:
        return text

    cleaned = text.strip()
    cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'__(.+?)__', r'\1', cleaned)
    cleaned = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'\1', cleaned)
    cleaned = re.sub(r'^#{1,6}\s+', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^[-*]\s+', '• ', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'\2', cleaned)
    cleaned = re.sub(r'\[([^\]]+)\]\((/[^)]+)\)', r'\2', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()
