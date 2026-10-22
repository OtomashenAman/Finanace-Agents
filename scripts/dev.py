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


# The sample CSVs, in sheet order; each becomes a sheet named after its type
_SAMPLE_SHEETS = {
    "vendors": "Vendors",
    "bills": "Bills",
    "purchase_orders": "Purchase orders",
    "chart_of_accounts": "Chart of accounts",
    "customers": "Customers",
    "customer_invoices": "Customer invoices",
    "customer_payments": "Customer payments",
    "expenses": "Expenses",
    "account_balances": "Account balances",
    "subledger_totals": "Subledger totals",
    "profit_and_loss": "Profit and loss",
}


def _cell(value: str) -> object:
    """Numbers and dates as Excel would hold them; codes like 1000 or 2026-09 stay text."""
    import re
    from datetime import date

    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    return value


def sample_workbook() -> None:
    """docs/sample-uploads/all-agents.xlsx from the sample CSVs (one sheet per type)."""
    import csv

    from openpyxl import Workbook

    folder = ROOT / "docs" / "sample-uploads"
    workbook = Workbook()
    workbook.remove(workbook.active)
    for stem, title in _SAMPLE_SHEETS.items():
        sheet = workbook.create_sheet(title)
        with (folder / f"{stem}.csv").open(newline="") as f:
            for i, row in enumerate(csv.reader(f)):
                sheet.append(row if i == 0 else [_cell(v) for v in row])
    workbook.save(folder / "all-agents.xlsx")
    print(f"Wrote {folder / 'all-agents.xlsx'}")
