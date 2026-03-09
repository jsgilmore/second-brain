from typing import Any


def sanitize_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)

    sanitized_chars: list[str] = []
    for char in value:
        codepoint = ord(char)
        if char == "\x00":
            sanitized_chars.append(" ")
            continue
        if 0xD800 <= codepoint <= 0xDFFF:
            sanitized_chars.append("\ufffd")
            continue
        sanitized_chars.append(char)
    return "".join(sanitized_chars)


def sanitize_jsonish(value: Any) -> Any:
    if isinstance(value, dict):
        return {sanitize_text(key): sanitize_jsonish(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_jsonish(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_jsonish(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value
