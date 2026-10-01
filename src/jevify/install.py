"""`jevify install` / `jevify uninstall`: put the self-contained /jevify skill where Claude Code looks for skills.

The skill folder gets SKILL.md, a launcher, and a copy of this package (standard library only), so
`/jevify` works without the PyPI package being installed. Python 3.11+ is still required.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import __version__

PACKAGE_DIR = Path(__file__).parent
SKILL_SOURCE = PACKAGE_DIR / "skill" / "SKILL.md"
LAUNCHER = '''"""Launcher for the bundled jevify copy. Usage: python jevify.py analyze|run|... <args>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from jevify.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
'''
_OWNED = ("SKILL.md", "jevify.py", ".jevify_version", "lib")


def default_skills_dir() -> Path:
    return Path.home() / ".claude" / "skills"


def install_skill(skills_dir: Path | None = None) -> Path:
    folder = (skills_dir or default_skills_dir()) / "jevify"
    folder.mkdir(parents=True, exist_ok=True)
    lib = folder / "lib"
    if lib.exists():
        shutil.rmtree(lib)  # only ever our own previous copy
    shutil.copytree(PACKAGE_DIR, lib / "jevify", ignore=shutil.ignore_patterns("__pycache__", "skill", "*.pyc"))
    (folder / "jevify.py").write_text(LAUNCHER, encoding="utf-8")
    (folder / ".jevify_version").write_text(__version__, encoding="utf-8")
    shutil.copyfile(SKILL_SOURCE, folder / "SKILL.md")
    return folder / "SKILL.md"


def uninstall_skill(skills_dir: Path | None = None) -> bool:
    folder = (skills_dir or default_skills_dir()) / "jevify"
    if not (folder / "SKILL.md").exists():
        return False
    for name in _OWNED:
        target = folder / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    try:
        folder.rmdir()  # only removes the folder if nothing else lives in it
    except OSError:
        pass
    return True
