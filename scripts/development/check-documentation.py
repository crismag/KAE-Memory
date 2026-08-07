"""Documentation integrity checks that are cheap enough to run every time.

Not a documentation toolchain — five greps and a diff, against sources that
already have tests. Each one catches a way documentation goes wrong silently:

* a relative link that stopped resolving when a file moved;
* an MCP tool or environment variable that was renamed in code and not in prose;
* a private hostname, account identifier or archive path reaching a public page;
* a generated page drifting from the registry it was generated from.

    uv run python scripts/development/check-documentation.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAGES = [*sorted(REPO.glob("docs/**/*.md")), REPO / "README.md"]

#: Things that must never appear in a public page. Account identifiers, the
#: deployment's own hostname, and any path into the private archive.
FORBIDDEN = (
    r"\b362114671228\b",
    r"kae\.crishub\.com",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"BEGIN [A-Z ]*PRIVATE KEY",
    r"development-context/",
    r"KAE-Ecosystem/",
)


def links() -> list[str]:
    bad = []
    for page in PAGES:
        for link in re.findall(r"\]\(([^)#]+?)\)", page.read_text()):
            if link.startswith(("http", "mailto")):
                continue
            if not (page.parent / link).exists():
                bad.append(f"{page.relative_to(REPO)} -> {link}")
    return bad


def tool_names() -> list[str]:
    from kae_memory.capabilities import declared_mcp_tools

    real = set(declared_mcp_tools())
    used = {m for p in PAGES for m in re.findall(r"`(kae_[a-z_]+)`", p.read_text())}
    return sorted(used - real)


def env_names() -> list[str]:
    found = subprocess.run(
        ["grep", "-rhoE", "KAE_[A-Z_]+", "src/", "config/", "deploy/", "tests/"],
        capture_output=True,
        text=True,
        cwd=REPO,
    ).stdout.split()
    used = {m for p in PAGES for m in re.findall(r"`(KAE_[A-Z_]+)`", p.read_text())}
    return sorted(used - set(found))


def forbidden() -> list[str]:
    hits = []
    for page in PAGES:
        text = page.read_text()
        for pattern in FORBIDDEN:
            if re.search(pattern, text):
                # The match itself is not printed: if it is a credential, a CI
                # log is the last place it should be repeated.
                hits.append(f"{page.relative_to(REPO)} matches {pattern!r}")
    return hits


def generated() -> list[str]:
    bad = []
    for script in ("generate-capability-matrix.py", "generate-interface-reference.py"):
        result = subprocess.run(
            [sys.executable, f"scripts/development/{script}", "--check"],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        if result.returncode != 0:
            bad.append(result.stderr.strip() or f"{script} reports drift")
    return bad


CHECKS = (
    ("relative links resolve", links),
    ("MCP tool names are real", tool_names),
    ("environment variables exist", env_names),
    ("no private paths or credentials", forbidden),
    ("generated pages match their sources", generated),
)


def main() -> int:
    failed = 0
    for name, check in CHECKS:
        problems = check()
        if problems:
            failed += 1
            print(f"FAIL  {name}")
            for p in problems:
                print(f"        {p}")
        else:
            print(f"ok    {name}")
    print()
    print(f"{len(PAGES)} pages checked")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
