import re

MIN_OS = 15
MIN_OS_LABEL = f"iOS {MIN_OS} / iPadOS {MIN_OS}"


def is_supported(os_version: str) -> bool:
    match = re.match(r"(\d+)", os_version or "")
    return match is None or int(match.group(1)) >= MIN_OS
