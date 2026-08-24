#!/usr/bin/env python3
"""recurring.py: Manage recurring obligations (re-emerging tasks).

Recurring tasks are evergreen obligations that complete and re-emerge on a
frequency (洗牙 every 6mo, HVAC filter every 3mo, annual physical, etc.),
distinct from one-shot GTD tasks which terminate at `[x]`.

Source of truth: `$OV/gtd/recurring.md`.

Schema (one item per line, no `[ ]` checkbox so todos.py scan ignores it):

    - <slug>  every:<N><unit>  last-done:<YYYY-MM-DD>  area:#<tag>
        - optional sub-bullet notes (vendor, model, link, etc.)

Section headers (`## Health`, `## Home`, etc.) group items visually; area
tag still wins over section for filtering.

Units: d (days), w (weeks, 7d), mo (months, ~30d), y (years, ~365d).
Approximation is intentional: recurring cadences don't need exact calendar
arithmetic. Use literal `Nd` for precision.

Computed states (not stored):
    overdue       today > last-done + every
    due-soon      0 <= (last-done + every) - today <= 7
    satisfied     (last-done + every) - today > 7

Subcommands:
    list                        show overdue + due-soon, grouped by section
    list --all                  also show satisfied
    list --area #health         filter
    list --json                 structured output
    done <slug>                 update last-done to today
    done <slug> <date>          update last-done to a specific date
    next <slug>                 print computed next-due date

Exit codes: 0 always, even when items are overdue. The cue layer in
`cues.py` is the surfacing mechanism, not the exit code.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tier  # type: ignore[import-not-found]  # noqa: E402

RECURRING_FILE_RELATIVE = "recurring.md"  # under gtd/

ITEM_RE = re.compile(
    r"^- ([a-z0-9][\w-]*)"
    r"\s+every:(\d+)(d|w|mo|y)"
    r"\s+last-done:(\d{4}-\d{2}-\d{2})"
    r"(?:\s+area:(#[\w-]+))?"
    r"\s*$"
)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")

UNIT_DAYS = {"d": 1, "w": 7, "mo": 30, "y": 365}


@dataclass
class Recurring:
    slug: str
    every_n: int
    every_unit: str  # "d" | "w" | "mo" | "y"
    last_done: str  # YYYY-MM-DD
    area: str | None
    section: str | None
    line: int

    def every_days(self) -> int:
        return self.every_n * UNIT_DAYS[self.every_unit]

    def last_done_date(self) -> date:
        return date.fromisoformat(self.last_done)

    def next_due(self) -> date:
        return self.last_done_date() + timedelta(days=self.every_days())

    def days_until_due(self, today: date) -> int:
        return (self.next_due() - today).days

    def status(self, today: date) -> str:
        d = self.days_until_due(today)
        if d < 0:
            return "overdue"
        if d <= 7:
            return "due-soon"
        return "satisfied"

    def every_str(self) -> str:
        return f"{self.every_n}{self.every_unit}"


def recurring_path() -> Path:
    return tier("gtd") / RECURRING_FILE_RELATIVE


def parse_file() -> list[Recurring]:
    path = recurring_path()
    if not path.is_file():
        return []
    items: list[Recurring] = []
    current_section: str | None = None
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        sec_m = SECTION_RE.match(line)
        if sec_m:
            current_section = sec_m.group(1)
            continue
        m = ITEM_RE.match(line)
        if not m:
            continue
        slug, n, unit, last_done, area = m.groups()
        items.append(
            Recurring(
                slug=slug,
                every_n=int(n),
                every_unit=unit,
                last_done=last_done,
                area=area,
                section=current_section,
                line=i,
            )
        )
    return items


def find_by_slug(slug: str) -> Recurring | None:
    for item in parse_file():
        if item.slug == slug:
            return item
    return None


def update_last_done(slug: str, new_date: str) -> bool:
    path = recurring_path()
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    changed = False
    for i, line in enumerate(lines):
        m = ITEM_RE.match(line)
        if not m or m.group(1) != slug:
            continue
        lines[i] = re.sub(
            r"last-done:\d{4}-\d{2}-\d{2}",
            f"last-done:{new_date}",
            line,
            count=1,
        )
        changed = True
        break
    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


# --- subcommands ----------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    today = date.today()
    items = parse_file()
    if args.area:
        items = [i for i in items if i.area == args.area]

    visible = [i for i in items if i.status(today) != "satisfied" or args.all]
    visible.sort(key=lambda i: (i.next_due(), i.slug))

    if args.json:
        payload = []
        for i in visible:
            d = asdict(i)
            d["next_due"] = i.next_due().isoformat()
            d["days_until_due"] = i.days_until_due(today)
            d["status"] = i.status(today)
            payload.append(d)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not visible:
        if not items:
            print("No recurring items found. Add some to gtd/recurring.md.")
        else:
            print("All recurring items satisfied. Run with --all to see them.")
        return 0

    groups: dict[str, list[Recurring]] = {}
    for i in visible:
        key = i.section or "(no section)"
        groups.setdefault(key, []).append(i)

    for section, group in groups.items():
        print(f"\n{section}")
        print("─" * 56)
        for i in group:
            status = i.status(today)
            d = i.days_until_due(today)
            if status == "overdue":
                marker = f"OVERDUE {-d}d"
            elif status == "due-soon":
                marker = f"due in {d}d" if d > 0 else "due today"
            else:
                marker = f"ok ({d}d)"
            area = f"  {i.area}" if i.area else ""
            print(f"  {marker:<14}  {i.slug}  every:{i.every_str()}  last:{i.last_done}{area}")
    print()
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    new_date = args.date or date.today().isoformat()
    try:
        date.fromisoformat(new_date)
    except ValueError:
        print(f"ERROR: invalid date '{new_date}', expected YYYY-MM-DD", file=sys.stderr)
        return 2
    item = find_by_slug(args.slug)
    if not item:
        print(f"ERROR: no recurring item with slug '{args.slug}'", file=sys.stderr)
        return 2
    if not update_last_done(args.slug, new_date):
        print(f"ERROR: failed to update '{args.slug}'", file=sys.stderr)
        return 2
    updated = find_by_slug(args.slug)
    assert updated is not None
    next_due = updated.next_due().isoformat()
    print(f"✓ {args.slug}  last-done:{new_date}  next:{next_due}")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    item = find_by_slug(args.slug)
    if not item:
        print(f"ERROR: no recurring item with slug '{args.slug}'", file=sys.stderr)
        return 2
    today = date.today()
    d = item.days_until_due(today)
    print(f"{args.slug}: next due {item.next_due().isoformat()} ({d:+d}d)")
    return 0


def cmd_overdue_count(_args: argparse.Namespace) -> int:
    """Internal: for cue integration. Prints count of overdue + due-soon items."""
    today = date.today()
    items = parse_file()
    overdue = [i for i in items if i.status(today) == "overdue"]
    due_soon = [i for i in items if i.status(today) == "due-soon"]
    payload = {
        "overdue": [
            {"slug": i.slug, "days_overdue": -i.days_until_due(today)}
            for i in sorted(overdue, key=lambda x: x.days_until_due(today))
        ],
        "due_soon": [
            {"slug": i.slug, "days_until_due": i.days_until_due(today)}
            for i in sorted(due_soon, key=lambda x: x.days_until_due(today))
        ],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/recurring.py",
        description="Manage recurring obligations (re-emerging tasks).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List recurring items by status.")
    p_list.add_argument("--all", action="store_true", help="Include satisfied items.")
    p_list.add_argument("--area", help="Filter by area tag, e.g. #health")
    p_list.add_argument("--json", action="store_true", help="JSON output.")
    p_list.set_defaults(func=cmd_list)

    p_done = sub.add_parser("done", help="Mark a recurring item as completed.")
    p_done.add_argument("slug", help="The slug of the recurring item.")
    p_done.add_argument("date", nargs="?", help="Completion date (default: today).")
    p_done.set_defaults(func=cmd_done)

    p_next = sub.add_parser("next", help="Print next-due date for a slug.")
    p_next.add_argument("slug")
    p_next.set_defaults(func=cmd_next)

    p_cue = sub.add_parser(
        "overdue-json", help="Internal: emit overdue + due-soon as JSON (for cues.py)."
    )
    p_cue.set_defaults(func=cmd_overdue_count)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
