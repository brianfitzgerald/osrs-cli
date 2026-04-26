"""Wikitext to Markdown rendering for OSRS Wiki pages."""

from __future__ import annotations

import re
from typing import Any

SKILL_GROUP_NAMES = {
    "attack",
    "defence",
    "strength",
    "hitpoints",
    "ranged",
    "prayer",
    "magic",
    "cooking",
    "woodcutting",
    "fletching",
    "fishing",
    "firemaking",
    "crafting",
    "smithing",
    "mining",
    "herblore",
    "agility",
    "thieving",
    "slayer",
    "farming",
    "runecraft",
    "runecrafting",
    "hunter",
    "construction",
    "combat",
    "quest",
    "sailing",
}


def wikitext_to_markdown(wikitext: str) -> str:
    """Best-effort wikitext → markdown rendering.

    Handles headings, bold/italic, wiki + external links, lists, SCP skill
    templates, and strips templates / refs / tables / file embeds. Nested
    templates are unwrapped iteratively. Tables are replaced with a
    placeholder rather than rendered.
    """
    s = wikitext

    # Drop comments, refs, galleries, magic words, hidden tags.
    s = re.sub(r"<!--.*?-->", "", s, flags=re.DOTALL)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.DOTALL)
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<gallery[^>]*>.*?</gallery>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<noinclude>.*?</noinclude>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<onlyinclude>(.*?)</onlyinclude>", r"\1", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"__\w+__", "", s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)

    # File/image embeds — proper bracket-balanced removal.
    s = _drop_file_links(s)

    # Tables: convert top-level `{| ... |}` blocks to markdown tables. Nested
    # tables are handled by recursing on cell contents.
    s = _convert_tables(s)

    # SCP skill-check template before generic template stripping.
    s = re.sub(
        r"\{\{SCP\|([^|}]+)\|([^|}]+)(?:\|[^}]*)?\}\}",
        lambda m: f"{m.group(2).strip()} {m.group(1).strip()}",
        s,
        flags=re.IGNORECASE,
    )

    # Strip remaining templates iteratively to handle nesting.
    for _ in range(8):
        new_s = re.sub(r"\{\{[^{}]*\}\}", "", s)
        if new_s == s:
            break
        s = new_s

    # Wiki numbered lists (`#` prefix) — must run before headings emit `#`.
    # Match inline whitespace only (`[ \t]+`) so a marker followed by `\n`
    # doesn't fold the next line up onto this one.
    s = re.sub(
        r"^(#+)[ \t]+",
        lambda m: ("  " * (len(m.group(1)) - 1)) + "1. ",
        s,
        flags=re.MULTILINE,
    )

    # Wiki bullet lists (`*` prefix). Inline-whitespace match required so we
    # don't mangle markdown bold (`**...**`) emitted by table-caption rendering.
    s = re.sub(
        r"^(\*+)[ \t]+",
        lambda m: ("  " * (len(m.group(1)) - 1)) + "- ",
        s,
        flags=re.MULTILINE,
    )

    # Definition lists (rough): `;term` → bold, `:def` → indented.
    s = re.sub(r"^;[ \t]*(.+)$", r"**\1**", s, flags=re.MULTILINE)
    s = re.sub(r"^:[ \t]*", "    ", s, flags=re.MULTILINE)

    # Headings: ==X== → ## X (after lists, since heading output contains `#`).
    s = re.sub(
        r"^(=+)\s*(.+?)\s*=+\s*$",
        lambda m: ("#" * len(m.group(1))) + " " + m.group(2).strip(),
        s,
        flags=re.MULTILINE,
    )

    # Bold + italic (longest first to avoid mis-pairing).
    s = re.sub(r"'''(.+?)'''", r"**\1**", s)
    s = re.sub(r"''(.+?)''", r"*\1*", s)

    # Wiki links: [[Target]] / [[Target|Display]].
    def _wiki_link(m: re.Match[str]) -> str:
        target = m.group(1).strip()
        display = (m.group(2) or target).strip()
        url = "https://oldschool.runescape.wiki/w/" + target.replace(" ", "_")
        return f"[{display}]({url})"

    s = re.sub(r"\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]", _wiki_link, s)

    # External links: [url text] → [text](url); [url] → <url>.
    s = re.sub(r"\[(https?://\S+)\s+([^\]]+)\]", r"[\2](\1)", s)
    s = re.sub(r"\[(https?://\S+)\]", r"<\1>", s)

    # Collapse runs of blank lines.
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _drop_file_links(s: str) -> str:
    """Remove `[[File:...]]` / `[[Image:...]]` embeds, including nested brackets."""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i : i + 2] == "[[" and s[i + 2 : i + 7].lower() in ("file:", "image"):
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if s[j : j + 2] == "[[":
                    depth += 1
                    j += 2
                elif s[j : j + 2] == "]]":
                    depth -= 1
                    j += 2
                else:
                    j += 1
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _convert_tables(s: str) -> str:
    """Replace top-level `{| ... |}` blocks with rendered markdown tables.

    Nested tables are kept intact inside their parent cell and re-rendered
    when `_sanitize_table_cell` recurses into `wikitext_to_markdown`.
    """
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if i + 1 < n and s[i] == "{" and s[i + 1] == "|":
            depth = 1
            j = i + 2
            while j + 1 < n and depth > 0:
                if s[j] == "{" and s[j + 1] == "|":
                    depth += 1
                    j += 2
                elif s[j] == "|" and s[j + 1] == "}":
                    depth -= 1
                    j += 2
                else:
                    j += 1
            if depth == 0:
                out.append("\n" + _render_table(s[i + 2 : j - 2]) + "\n")
                i = j
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _render_table(body: str) -> str:
    """Render the body of a `{| ... |}` block as a markdown table.

    Honours `colspan` / `rowspan` by expanding them into empty cells:
    markdown can't represent merged cells, but expanding into blank slots
    preserves column alignment, which is the visible failure mode.
    """
    caption = ""
    # Each parsed cell: (is_header, content, colspan, rowspan)
    rows: list[list[tuple[bool, str, int, int]]] = []
    cur: list[tuple[bool, str, int, int]] = []
    started = False
    nested = 0  # depth inside a nested `{| ... |}` carried inside a cell

    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue

        if not started:
            if line.startswith(("|", "!")):
                started = True
            else:
                # Leading attribute line (`class="wikitable"` etc.) — skip.
                continue

        if nested > 0:
            # Inside a nested table — append verbatim to the in-progress cell.
            if cur:
                is_h, prev, cs, rs = cur[-1]
                cur[-1] = (is_h, prev + "\n" + line, cs, rs)
            nested += line.count("{|") - line.count("|}")
            continue

        if line.startswith("|+"):
            caption = line[2:].strip()
        elif line.startswith("|-"):
            if cur:
                rows.append(cur)
                cur = []
        elif line.startswith("!"):
            for cell in re.split(r"\s*!!\s*", line[1:]):
                content, cs, rs = _strip_cell_attrs(cell)
                cur.append((True, content, cs, rs))
        elif line.startswith("|"):
            for cell in re.split(r"\s*\|\|\s*", line[1:]):
                content, cs, rs = _strip_cell_attrs(cell)
                cur.append((False, content, cs, rs))
        elif cur:
            # Continuation of the previous cell's content (multi-line).
            is_h, prev, cs, rs = cur[-1]
            cur[-1] = (is_h, prev + "\n" + line, cs, rs)

        nested += line.count("{|") - line.count("|}")

    if cur:
        rows.append(cur)
    if not rows:
        return ""

    # Layout: walk parsed rows, expanding colspan inline and tracking rowspan
    # carry-over so spanned columns are skipped in subsequent rows.
    grid: list[list[str]] = []
    header_flags: list[list[bool]] = []
    # column index → (remaining rows after this one, is_header) for rowspans.
    carry: dict[int, tuple[int, bool]] = {}

    for parsed in rows:
        row_cells: list[str] = []
        row_headers: list[bool] = []
        col = 0
        for is_h, content, cs, rs in parsed:
            # Skip columns claimed by a rowspan from an earlier row.
            while col in carry:
                remaining, claimed_h = carry[col]
                row_cells.append("")
                row_headers.append(claimed_h)
                if remaining - 1 == 0:
                    del carry[col]
                else:
                    carry[col] = (remaining - 1, claimed_h)
                col += 1

            # Place this cell, expanding colspan into trailing empty cells.
            row_cells.append(content)
            row_headers.append(is_h)
            for _ in range(cs - 1):
                row_cells.append("")
                row_headers.append(is_h)

            if rs > 1:
                for k in range(cs):
                    carry[col + k] = (rs - 1, is_h)
            col += cs

        # Drain any remaining rowspan claims at the trailing edge of this row.
        while col in carry:
            remaining, claimed_h = carry[col]
            row_cells.append("")
            row_headers.append(claimed_h)
            if remaining - 1 == 0:
                del carry[col]
            else:
                carry[col] = (remaining - 1, claimed_h)
            col += 1

        grid.append(row_cells)
        header_flags.append(row_headers)

    width = max(len(r) for r in grid)
    for r in grid:
        r.extend([""] * (width - len(r)))

    rendered = [[_sanitize_table_cell(c) for c in r] for r in grid]

    out: list[str] = []
    if caption:
        out.append(f"**{_sanitize_table_cell(caption)}**")
        out.append("")

    first_has_header = any(header_flags[0])
    if first_has_header:
        header, body_rows = rendered[0], rendered[1:]
    else:
        header, body_rows = [""] * width, rendered

    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "|".join(["---"] * width) + "|")
    for r in body_rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def _strip_cell_attrs(cell: str) -> tuple[str, int, int]:
    """`style="x" colspan="2" | content` → `(content, 2, 1)`.

    Returns (content, colspan, rowspan). Defaults to (cell, 1, 1) when no
    attribute separator is present. Leaves nested tables / templates intact.
    """
    cell = cell.strip()
    if cell.startswith("{|"):
        return cell, 1, 1
    # Find the first `|` outside of `[[...]]` and `{{...}}`.
    bracket = brace = 0
    for k in range(len(cell)):
        pair = cell[k : k + 2]
        if pair == "[[":
            bracket += 1
        elif pair == "]]":
            bracket = max(0, bracket - 1)
        elif pair == "{{":
            brace += 1
        elif pair == "}}":
            brace = max(0, brace - 1)
        elif cell[k] == "|" and bracket == 0 and brace == 0:
            attrs = cell[:k]
            # Only treat as attr separator if the prefix looks like attributes.
            if "=" in attrs:
                cs = _parse_span_attr(attrs, "colspan")
                rs = _parse_span_attr(attrs, "rowspan")
                content = cell[k + 1 :].strip()
                return content, cs, rs
            break
    return cell, 1, 1


def _parse_span_attr(attrs: str, name: str) -> int:
    """Extract colspan / rowspan from a cell's attribute string."""
    m = re.search(rf"\b{name}\s*=\s*[\"']?(\d+)", attrs, re.IGNORECASE)
    return max(1, int(m.group(1))) if m else 1


def _sanitize_table_cell(content: str) -> str:
    """Recursively render a cell's wikitext as markdown, flattened to one line."""
    md = wikitext_to_markdown(content).strip()
    md = re.sub(r"\n+", "<br>", md)
    return md.replace("|", r"\|")


def strip_wiki_markup(s: str) -> str:
    # {{SCP|Skill|Level|...}} → "Level Skill" (skill-check template)
    s = re.sub(
        r"\{\{SCP\|([^|}]+)\|([^|}]+)(?:\|[^}]*)?\}\}",
        lambda m: f"{m.group(2).strip()} {m.group(1).strip()}",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\{\{[^}]+\}\}", "", s)
    s = re.sub(r"''+", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_requirements_field(wikitext: str) -> str | None:
    """Pull the `requirements =` field out of the {{Quest details}} template."""
    m = re.search(r"\{\{Quest details", wikitext, re.IGNORECASE)
    if not m:
        return None
    body = wikitext[m.end() :]
    m2 = re.search(r"\|\s*requirements\s*=", body, re.IGNORECASE)
    if not m2:
        return None
    rest = body[m2.end() :]
    depth = 0
    out: list[str] = []
    i = 0
    while i < len(rest):
        c = rest[i]
        if c == "{" and rest[i : i + 2] == "{{":
            depth += 1
            out.append("{{")
            i += 2
            continue
        if c == "}" and rest[i : i + 2] == "}}":
            if depth == 0:
                break
            depth -= 1
            out.append("}}")
            i += 2
            continue
        if c == "|" and depth == 0 and (i == 0 or rest[i - 1] == "\n"):
            break
        out.append(c)
        i += 1
    return "".join(out).strip()


def parse_requirements(field: str) -> dict[str, Any]:
    """Bucket requirement lines into skills, direct prereq quests, transitive, other."""
    skills: list[str] = []
    direct_quests: list[str] = []
    transitive_quests: list[str] = []
    other: list[str] = []
    seen_quest_header = False
    for raw in field.splitlines():
        stripped = raw.lstrip()
        m = re.match(r"^(\*+)\s*(.*)$", stripped)
        if not m:
            continue
        depth = len(m.group(1))
        body = m.group(2).strip()
        if not body or body.startswith("|") or body.startswith("}}"):
            continue
        cleaned = strip_wiki_markup(body)
        if not cleaned:
            continue
        # Quest-list header like "Completion of the following quests:" — skip;
        # subsequent deeper bullets are the actual list.
        if re.search(r"completion of the following quests", cleaned, re.IGNORECASE):
            seen_quest_header = True
            continue
        quest_link = re.match(r"^\[\[([^\]|]+)(?:\|[^\]]+)?\]\]\s*$", body)
        if quest_link:
            name = quest_link.group(1).strip()
            if seen_quest_header and depth <= 2:
                direct_quests.append(name)
            else:
                transitive_quests.append(name)
            continue
        skill_m = re.match(r"^(\d+)\s+([A-Za-z]+)", cleaned)
        if skill_m and skill_m.group(2).lower() in SKILL_GROUP_NAMES:
            skills.append(cleaned)
            continue
        other.append(cleaned)
    # Dedupe transitive while preserving order, and drop any already in direct.
    seen = set(direct_quests)
    deduped_transitive: list[str] = []
    for q in transitive_quests:
        if q in seen:
            continue
        seen.add(q)
        deduped_transitive.append(q)
    return {
        "skills": skills,
        "quests": direct_quests,
        "transitive_quests": deduped_transitive,
        "other": other,
    }
