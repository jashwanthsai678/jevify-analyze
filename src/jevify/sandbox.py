"""Sandbox lifecycle: copy the project, inject the Jev SDK, and merge verified files back."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .fsutil import EXCLUDED_DIRS, RUNTIME_FILENAME
from .translator import RUNTIME_SOURCE

MARKER = ".jevify-sandbox"
SDK_PACKAGE = "typesafe-sdk"


def create_sandbox(project: Path, sandbox_dir: Path | None) -> Path:
    project = Path(project).resolve()
    if sandbox_dir is None:
        sandbox = Path(tempfile.mkdtemp(prefix="jevify-"))
    else:
        sandbox = Path(sandbox_dir).resolve()
        if sandbox.exists() and any(sandbox.iterdir()):
            if not (sandbox / MARKER).exists():
                raise SystemExit(f"refusing to reuse non-empty directory that is not a jevify sandbox: {sandbox}")
            shutil.rmtree(sandbox)
        sandbox.mkdir(parents=True, exist_ok=True)

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = {n for n in names if n in EXCLUDED_DIRS or n.endswith(".egg-info")}
        skipped |= {n for n in names if (Path(directory) / n).resolve() == sandbox}
        return skipped

    shutil.copytree(project, sandbox, ignore=ignore, dirs_exist_ok=True)
    (sandbox / MARKER).write_text("created by jevify; safe to delete\n", encoding="utf-8")
    return sandbox


def install_runtime(directory: Path) -> Path:
    dest = Path(directory) / RUNTIME_FILENAME
    shutil.copyfile(RUNTIME_SOURCE, dest)
    return dest


def inject_dependency(sandbox: Path, use_uv: bool = True) -> str:
    """Add typesafe-sdk to the sandbox's dependency file. Returns a human-readable note."""
    pyproject, requirements = sandbox / "pyproject.toml", sandbox / "requirements.txt"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8")
        if SDK_PACKAGE in text:
            return "typesafe-sdk already declared"
        if use_uv and shutil.which("uv"):
            try:
                proc = subprocess.run(["uv", "add", "--no-sync", SDK_PACKAGE], cwd=sandbox,
                                      capture_output=True, text=True, timeout=120)
                if proc.returncode == 0:
                    return "added typesafe-sdk with `uv add`"
            except (subprocess.TimeoutExpired, OSError):
                pass
        return _edit_pyproject(pyproject, text)
    if requirements.exists():
        body = requirements.read_text(encoding="utf-8")
        if SDK_PACKAGE not in body:
            requirements.write_text(body.rstrip("\n") + f"\n{SDK_PACKAGE}\n", encoding="utf-8")
        return "appended typesafe-sdk to requirements.txt"
    return "no pyproject.toml or requirements.txt found: add typesafe-sdk to your dependencies manually"


def _edit_pyproject(path: Path, text: str) -> str:
    dep = re.search(r"^dependencies\s*=\s*\[", text, re.M)
    proj = re.search(r"^\[project\]\s*$", text, re.M)
    if dep:
        text = text[: dep.end()] + f'\n    "{SDK_PACKAGE}",' + text[dep.end():]
    elif proj:
        text = text[: proj.end()] + f'\ndependencies = ["{SDK_PACKAGE}"]' + text[proj.end():]
    else:
        return "pyproject.toml has no [project] table: add typesafe-sdk manually"
    path.write_text(text, encoding="utf-8")
    return "added typesafe-sdk to pyproject.toml (uv add unavailable)"


def merge_back(project: Path, sandbox: Path, changed: list[str], runtime_dirs: set[str],
               dependency_files: list[str]) -> list[str]:
    """Copy verified files into the project; originals are saved under .jevify/backup/."""
    project, sandbox = Path(project).resolve(), Path(sandbox).resolve()
    backup = project / ".jevify" / "backup"
    written: list[str] = []
    for rel in [*changed, *dependency_files]:
        src, dst = sandbox / rel, project / rel
        if not src.exists():
            continue
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            continue
        if dst.exists():
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dst, backup / rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        written.append(rel)
    for d in sorted(runtime_dirs):
        install_runtime(project / d)
        written.append((Path(d) / RUNTIME_FILENAME).as_posix())
    return written
