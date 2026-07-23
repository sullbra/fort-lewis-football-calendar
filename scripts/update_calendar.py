from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import re

SOURCE_URL = "https://goskyhawks.com/Calendar.ashx/calendar.ics"
OUTPUT_FILE = Path("fort-lewis-football.ics")


def unfold_ical_lines(text: str) -> list[str]:
    """Unfold RFC 5545 continuation lines."""
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []

    for line in raw_lines:
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)

    return lines


def escape_text(value: str) -> str:
    """Escape text values for an iCalendar property."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def normalized_for_comparison(text: str) -> str:
    """
    Ignore changing timestamp metadata when deciding whether the actual
    football schedule changed.
    """
    ignored_prefixes = ("DTSTAMP", "LAST-MODIFIED", "CREATED")
    normalized_lines = [
        line.rstrip()
        for line in unfold_ical_lines(text)
        if line and not line.startswith(ignored_prefixes)
    ]
    return "\n".join(normalized_lines)


def read_component(lines: list[str], start: int, component: str) -> tuple[list[str], int]:
    """Read a complete iCalendar component beginning at lines[start]."""
    block = [lines[start]]
    i = start + 1
    depth = 1

    while i < len(lines):
        line = lines[i]
        block.append(line)

        if line == f"BEGIN:{component}":
            depth += 1
        elif line == f"END:{component}":
            depth -= 1
            if depth == 0:
                return block, i

        i += 1

    raise RuntimeError(f"Unterminated {component} component in source calendar.")


def main() -> None:
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; FortLewisFootballCalendar/1.0)"
        },
    )

    with urlopen(request, timeout=30) as response:
        source = response.read().decode("utf-8-sig", errors="replace")

    lines = unfold_ical_lines(source)
    timezone_blocks: list[list[str]] = []
    event_blocks: list[list[str]] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        if line == "BEGIN:VTIMEZONE":
            block, i = read_component(lines, i, "VTIMEZONE")
            timezone_blocks.append(block)

        elif line == "BEGIN:VEVENT":
            block, i = read_component(lines, i, "VEVENT")
            event_blocks.append(block)

        i += 1

    football_events = [
        block
        for block in event_blocks
        if re.search(r"\bfootball\b", "\n".join(block), flags=re.IGNORECASE)
    ]

    if not football_events:
        raise RuntimeError(
            "No football events were found in the Fort Lewis athletics calendar."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    output: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Fort Lewis Football Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text('Fort Lewis Football')}",
        "X-WR-TIMEZONE:America/Denver",
        f"X-WR-CALDESC:{escape_text('Automatically updated Fort Lewis College football schedule')}",
    ]

    for block in timezone_blocks:
        output.extend(block)

    for block in football_events:
        cleaned: list[str] = []
        inserted_dtstamp = False

        for line in block:
            if line.startswith(("DTSTAMP", "LAST-MODIFIED", "CREATED")):
                if not inserted_dtstamp:
                    cleaned.append(f"DTSTAMP:{stamp}")
                    inserted_dtstamp = True
                continue

            cleaned.append(line)

        if not inserted_dtstamp:
            cleaned.insert(1, f"DTSTAMP:{stamp}")

        output.extend(cleaned)

    output.append("END:VCALENDAR")
    new_text = "\r\n".join(output) + "\r\n"

    if OUTPUT_FILE.exists():
        existing_text = OUTPUT_FILE.read_text(encoding="utf-8-sig", errors="replace")
        if normalized_for_comparison(existing_text) == normalized_for_comparison(new_text):
            print(
                f"No football schedule changes found; kept {OUTPUT_FILE} unchanged."
            )
            return

    OUTPUT_FILE.write_text(new_text, encoding="utf-8")
    print(f"Wrote {len(football_events)} football events to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
