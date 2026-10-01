"""`jevvify install` / `jevvify uninstall`: put the self-contained /jevvify skill where Claude Code looks for skills.

The skill folder gets SKILL.md, a launcher, and a copy of this package (standard library only), so
`/jevvify` works without the PyPI package being installed. Python 3.11+ is still required.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import __version__

PACKAGE_DIR = Path(__file__).parent
SKILL_DIR = PACKAGE_DIR / "skill"  # SKILL.md plus reference/ files Claude reads on demand
LAUNCHER = '''"""Launcher for the bundled jevvify copy. Usage: python jevvify.py analyze|run|... <args>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from jevvify.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
'''
_OWNED = ("SKILL.md", "reference", "jevvify.py", ".jevvify_version", "lib")


def default_skills_dir() -> Path:
    return Path.home() / ".claude" / "skills"


def install_skill(skills_dir: Path | None = None) -> Path:
    folder = (skills_dir or default_skills_dir()) / "jevvify"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("lib", "reference"):
        if (folder / name).exists():
            shutil.rmtree(folder / name)  # only ever our own previous copy
    shutil.copytree(PACKAGE_DIR, folder / "lib" / "jevvify",
                    ignore=shutil.ignore_patterns("__pycache__", "skill", "*.pyc"))
    shutil.copytree(SKILL_DIR, folder, ignore=shutil.ignore_patterns("__pycache__"), dirs_exist_ok=True)
    (folder / "jevvify.py").write_text(LAUNCHER, encoding="utf-8")
    (folder / ".jevvify_version").write_text(__version__, encoding="utf-8")
    return folder / "SKILL.md"


def uninstall_skill(skills_dir: Path | None = None) -> bool:
    folder = (skills_dir or default_skills_dir()) / "jevvify"
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
