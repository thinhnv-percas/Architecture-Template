#!/usr/bin/env python3
"""
Auto-generate Table of Contents for GitHub Wiki Home page.
Scans all .md files in the wiki repo and builds a structured TOC.
"""

import os
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone


# ── Configuration ────────────────────────────────────────────────────────────
TOC_START_MARKER = "<!-- TOC:START - Do not edit this section manually -->"
TOC_END_MARKER   = "<!-- TOC:END -->"
HOME_FILE        = "Home.md"
EXCLUDE_FILES    = {"Home.md", "_Footer.md", "_Sidebar.md", "_Header.md"}
# ─────────────────────────────────────────────────────────────────────────────


def slugify(text: str) -> str:
    """Convert text to GitHub wiki link slug."""
    text = text.strip()
    text = re.sub(r"[^\w\s\-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text


def get_file_title(filepath: Path) -> str:
    """Extract title from first H1 heading or derive from filename."""
    try:
        content = filepath.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    except Exception:
        pass
    # Fallback: filename without extension, replace hyphens/underscores
    name = filepath.stem
    return re.sub(r"[-_]+", " ", name).title()


def get_file_description(filepath: Path) -> str:
    """Extract first non-heading, non-empty paragraph as description."""
    try:
        content = filepath.read_text(encoding="utf-8")
        lines = content.splitlines()
        skip_heading = True
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if skip_heading:
                    skip_heading = False
                    continue
            if stripped.startswith(("<!--", "---", "```")):
                continue
            if not skip_heading and stripped:
                # Truncate long descriptions
                desc = stripped[:120]
                if len(stripped) > 120:
                    desc += "…"
                return desc
    except Exception:
        pass
    return ""


def parse_directory_structure(wiki_dir: Path) -> dict:
    """
    Group wiki pages by directory/prefix convention.
    Files named 'Category-Page-Name.md' are grouped under 'Category'.
    Files in subdirectories are grouped by directory name.
    """
    structure = {}  # { group: [ {title, slug, description, path} ] }
    ungrouped = []

    md_files = sorted(
        [f for f in wiki_dir.rglob("*.md") if f.name not in EXCLUDE_FILES],
        key=lambda f: f.stem.lower()
    )

    for filepath in md_files:
        rel = filepath.relative_to(wiki_dir)
        parts = rel.parts  # e.g. ('guides', 'setup.md') or ('Setup-Guide.md',)

        title = get_file_title(filepath)
        description = get_file_description(filepath)

        # GitHub wiki link uses the stem (filename without .md)
        # For nested files: path relative to wiki root, use forward slashes
        slug = "/".join(parts[:-1] + (filepath.stem,)) if len(parts) > 1 else filepath.stem

        page = {
            "title": title,
            "slug": slug,
            "description": description,
            "path": rel,
        }

        if len(parts) > 1:
            # Nested in a subdirectory → group by directory name
            group = parts[0].replace("-", " ").replace("_", " ").title()
            structure.setdefault(group, []).append(page)
        else:
            # Flat file → try grouping by prefix (e.g. "Setup-Installation" → "Setup")
            # Only group if there are multiple files with the same prefix
            ungrouped.append(page)

    # Attempt prefix grouping for flat files
    prefix_groups: dict[str, list] = {}
    no_prefix: list = []

    for page in ungrouped:
        stem = page["path"].stem
        # Split on first hyphen or underscore that could be a separator
        parts_stem = re.split(r"[-_]", stem, maxsplit=1)
        if len(parts_stem) > 1:
            prefix = parts_stem[0].title()
            prefix_groups.setdefault(prefix, []).append(page)
        else:
            no_prefix.append(page)

    # Only create a prefix group if it has ≥2 pages; otherwise treat as ungrouped
    for prefix, pages in prefix_groups.items():
        if len(pages) >= 2:
            structure.setdefault(prefix, []).extend(pages)
        else:
            no_prefix.extend(pages)

    if no_prefix:
        structure.setdefault("Others", []).extend(no_prefix)

    return structure


def build_toc(wiki_dir: Path, repo_name: str) -> str:
    """Build the full TOC markdown block."""
    structure = parse_directory_structure(wiki_dir)

    if not structure:
        return "_No wiki pages found yet._\n"

    lines = []
    total_pages = sum(len(v) for v in structure.values())

    lines.append(f"> 📚 **{total_pages} page{'s' if total_pages != 1 else ''}** — "
                 f"auto-generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
    lines.append("")

    for group, pages in structure.items():
        lines.append(f"### {group}\n")
        for page in sorted(pages, key=lambda p: p["title"].lower()):
            slug = page["slug"]
            title = page["title"]

            link = f"[[{title}|{slug}]]"
            lines.append(f"- {link}")
        lines.append("")

    return "\n".join(lines)


def update_home(wiki_dir: Path, repo_name: str) -> bool:
    """
    Inject/update TOC block inside Home.md.
    Returns True if the file was actually changed.
    """
    home_path = wiki_dir / HOME_FILE

    toc_block = (
        f"{TOC_START_MARKER}\n\n"
        f"{build_toc(wiki_dir, repo_name)}\n"
        f"{TOC_END_MARKER}"
    )

    if home_path.exists():
        original = home_path.read_text(encoding="utf-8")
    else:
        # Create a minimal Home.md if it doesn't exist
        original = (
            f"# {repo_name} Wiki\n\n"
            f"Welcome to the **{repo_name}** wiki.\n\n"
            f"{TOC_START_MARKER}\n{TOC_END_MARKER}\n"
        )

    # Replace existing TOC block if present
    pattern = re.compile(
        rf"{re.escape(TOC_START_MARKER)}.*?{re.escape(TOC_END_MARKER)}",
        re.DOTALL,
    )

    if pattern.search(original):
        updated = pattern.sub(toc_block, original)
    else:
        # Append TOC at the end
        updated = original.rstrip() + "\n\n" + toc_block + "\n"

    if updated == original:
        print("ℹ️  TOC is already up-to-date. No changes needed.")
        return False

    home_path.write_text(updated, encoding="utf-8")
    print(f"✅ Updated {HOME_FILE} with {sum(len(v) for v in parse_directory_structure(wiki_dir).values())} page(s).")
    return True


def git_commit_push(wiki_dir: Path, actor: str, email: str) -> None:
    """Stage, commit, and push changes to the wiki repo."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def run(cmd: list[str]) -> None:
        result = subprocess.run(cmd, cwd=wiki_dir, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Command failed: {' '.join(cmd)}")
            print(result.stderr)
            sys.exit(1)

    run(["git", "config", "user.name",  actor])
    run(["git", "config", "user.email", email])
    run(["git", "add", HOME_FILE])
    run(["git", "commit", "-m", "docs(wiki): auto-update Home page table of contents [skip ci]"])
    run(["git", "push"])
    print("🚀 Changes pushed to wiki.")


def main() -> None:
    wiki_dir  = Path(os.environ.get("WIKI_DIR",  "wiki"))
    repo_name = os.environ.get("REPO_NAME",  "Repository")
    actor     = os.environ.get("GIT_ACTOR",  "github-actions[bot]")
    email     = os.environ.get("GIT_EMAIL",  "github-actions[bot]@users.noreply.github.com")
    dry_run   = os.environ.get("DRY_RUN", "false").lower() == "true"

    if not wiki_dir.exists():
        print(f"❌ Wiki directory not found: {wiki_dir}")
        sys.exit(1)

    changed = update_home(wiki_dir, repo_name)

    if changed and not dry_run:
        git_commit_push(wiki_dir, actor, email)
    elif dry_run:
        print("🔍 Dry run mode — no git operations performed.")


if __name__ == "__main__":
    main()
