"""Cross-platform helpers for the poe tasks in pyproject.toml (Linux, macOS, Windows).

Anything that would otherwise need bash (cp, rm -rf, find, cd) lives here so the
same `uv run poe <task>` works on every OS.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "src" / "frontend"


def _run(cmd: list[str], cwd: Path = ROOT) -> None:
    exe = shutil.which(cmd[0])  # resolves npm.cmd / docker.exe on Windows
    if exe is None:
        sys.exit(f"'{cmd[0]}' not found on PATH - see README 'Prerequisites'")
    code = subprocess.call([exe, *cmd[1:]], cwd=cwd)
    if code:
        sys.exit(code)


def npm(*args: str) -> None:
    """Run npm inside src/frontend."""
    _run(["npm", *args], cwd=FRONTEND)


def init_env() -> None:
    """Create .env from .env.example if it doesn't exist yet."""
    env, example = ROOT / ".env", ROOT / ".env.example"
    if env.exists():
        print(".env already exists - leaving it untouched")
        return
    shutil.copyfile(example, env)
    print("Created .env from .env.example - fill in SECRET_KEY / AZURE_OPENAI_API_KEY")


def db_shell() -> None:
    """Open psql in the db container (credentials come from the container's own env)."""
    _run(
        [
            "docker",
            "compose",
            "exec",
            "db",
            "sh",
            "-c",
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
        ]
    )


def clean() -> None:
    """Remove caches and build artifacts."""
    targets = [ROOT / ".cache", FRONTEND / "dist"]
    targets += [
        p
        for p in ROOT.rglob("__pycache__")
        if ".venv" not in p.parts and "node_modules" not in p.parts
    ]
    for path in targets:
        shutil.rmtree(path, ignore_errors=True)
    print(f"Removed {len(targets)} cache/build directories")
