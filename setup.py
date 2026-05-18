"""
setup.py - Configuration loading, dependency verification, and Copilot CLI
           installation for CoderAgent.

Called automatically by agent.py at startup.  Can also be run standalone:

    python setup.py

Checks performed
----------------
1. Python 3.10+ version requirement.
2. CoderAgentConfig.yaml exists and contains a valid GitHub token.
3. GitHub Copilot CLI binary is installed (auto-installs via npm/winget if missing).
4. git is available on PATH (auto-installs via system package manager if missing).
"""

import os
import re
import subprocess
import shutil
import sys
import platform
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
AGENT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = AGENT_DIR / "CoderAgentConfig.yaml"
CONFIG_EXAMPLE = AGENT_DIR / "CoderAgentConfig.example.yaml"

_PLACEHOLDER = "XXXXXXXXXXXXXXXXXX"

# Minimum supported Python version
_MIN_PYTHON = (3, 10)

# ---------------------------------------------------------------------------
# Required system tools
# ---------------------------------------------------------------------------
_REQUIRED_SYSTEM_TOOLS: list[tuple[str, str]] = [
    ("git", "Git version control"),
    ("copilot", "GitHub Copilot CLI"),
]


# ---------------------------------------------------------------------------
# Python version check
# ---------------------------------------------------------------------------

def check_python_version() -> None:
    """Exit with a clear message if the running Python version is too old."""
    v = sys.version_info[:2]
    if v < _MIN_PYTHON:
        min_str = ".".join(str(x) for x in _MIN_PYTHON)
        cur_str = ".".join(str(x) for x in v)
        print(
            f"ERROR: Python {min_str}+ is required (you have {cur_str}).",
            file=sys.stderr,
        )
        print("  Download from: https://www.python.org/downloads/", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _parse_simple_yaml(text: str) -> dict[str, str]:
    """Parse a flat key: value YAML file (no nested structures)."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)", line)
        if m:
            result[m.group(1)] = m.group(2).strip().strip("'\"")
    return result


def load_config() -> dict[str, str]:
    """Load CoderAgentConfig.yaml, creating it from the example if needed.

    Returns the parsed config dict.  Exits with instructions if the token
    is still the placeholder value.
    """
    if not CONFIG_FILE.exists():
        if CONFIG_EXAMPLE.exists():
            shutil.copy2(CONFIG_EXAMPLE, CONFIG_FILE)
            print(f"Created {CONFIG_FILE.name} from example template.")
            print(f"Please edit {CONFIG_FILE} and set your GitHub token,")
            print("then re-run the agent.")
            sys.exit(1)
        else:
            print(
                f"ERROR: Neither {CONFIG_FILE.name} nor "
                f"{CONFIG_EXAMPLE.name} found in {AGENT_DIR}",
                file=sys.stderr,
            )
            sys.exit(1)

    cfg = _parse_simple_yaml(CONFIG_FILE.read_text(encoding="utf-8"))

    token = cfg.get("github_token", "")
    if not token or token == _PLACEHOLDER:
        print(f"ERROR: github_token in {CONFIG_FILE.name} is not set.")
        print(
            f"Please edit {CONFIG_FILE} and replace the placeholder "
            "with your GitHub personal access token."
        )
        print(
            "Generate one at: "
            "https://github.com/settings/personal-access-tokens/new"
        )
        sys.exit(1)

    if token.startswith("ghp_"):
        print("=" * 60)
        print("  WARNING: Classic PATs (ghp_) are NOT supported.")
        print("  Please replace your token with a Fine-Grained PAT (github_pat_).")
        print()
        print(
            "  Generate one at: "
            "https://github.com/settings/personal-access-tokens/new"
        )
        print("  Required: Copilot Requests permission")
        print(f"  Update:   {CONFIG_FILE}")
        print("=" * 60)
        sys.exit(1)

    return cfg


# ---------------------------------------------------------------------------
# System tool management
# ---------------------------------------------------------------------------

_SYSTEM_INSTALL_SPECS: dict[str, dict[str, list[tuple[str, list]]]] = {
    "Windows": {
        "git": [
            (
                "winget",
                [
                    [
                        "winget", "install", "--id", "Git.Git", "-e",
                        "--accept-source-agreements",
                        "--accept-package-agreements",
                    ]
                ],
            )
        ],
        "copilot": [
            (
                "winget",
                [
                    [
                        "winget", "install", "--id", "GitHub.Copilot", "-e",
                        "--accept-source-agreements",
                        "--accept-package-agreements",
                    ]
                ],
            ),
            (
                "npm",
                [["npm", "install", "-g", "@github/copilot"]],
            ),
        ],
    },
    "Linux": {
        "git": [
            (
                "apt-get",
                [
                    ["sudo", "apt-get", "update"],
                    ["sudo", "apt-get", "install", "-y", "git"],
                ],
            ),
            ("dnf", [["sudo", "dnf", "install", "-y", "git"]]),
            ("pacman", [["sudo", "pacman", "-S", "--noconfirm", "git"]]),
        ],
        "copilot": [
            (
                "npm",
                [["npm", "install", "-g", "@github/copilot"]],
            ),
        ],
    },
    "Darwin": {
        "git": [
            ("brew", [["brew", "install", "git"]]),
        ],
        "copilot": [
            ("brew", [["brew", "install", "copilot-cli"]]),
            (
                "npm",
                [["npm", "install", "-g", "@github/copilot"]],
            ),
        ],
    },
}


def _run_install_steps(steps: list, name: str) -> bool:
    """Execute a sequence of install commands.  Returns True only if all succeed."""
    for step in steps:
        if isinstance(step, str):
            print(f"  Running: {step}")
            try:
                r = subprocess.run(step, shell=True, timeout=300)
            except subprocess.TimeoutExpired:
                print("ERROR: install command timed out.", file=sys.stderr)
                return False
        else:
            print(f"  Running: {' '.join(step)}")
            try:
                r = subprocess.run(step, timeout=300)
            except FileNotFoundError:
                print(f"ERROR: '{step[0]}' not found.", file=sys.stderr)
                return False
            except subprocess.TimeoutExpired:
                print("ERROR: install command timed out.", file=sys.stderr)
                return False
        if r.returncode != 0:
            return False
    return True


def _install_system_tool(tool: str, desc: str, system: str) -> bool:
    """Attempt to install a system tool using the platform package manager."""
    specs = _SYSTEM_INSTALL_SPECS.get(system, {}).get(tool)
    if not specs:
        print(
            f"ERROR: No automatic install method for '{tool}' on {system}. "
            f"Please install {desc} manually.",
            file=sys.stderr,
        )
        return False

    for prereq, steps in specs:
        if shutil.which(prereq):
            print(f"Installing {desc} via {prereq}…")
            if _run_install_steps(steps, desc):
                return True

    managers = ", ".join({p for p, _ in specs})
    print(
        f"ERROR: None of the supported package managers ({managers}) were found. "
        f"Please install {desc} manually.",
        file=sys.stderr,
    )
    return False


def _refresh_path() -> None:
    """Re-add common bin directories to PATH after an install."""
    extra_dirs = [
        d for d in ("/usr/local/bin", "/usr/bin", "/usr/local/sbin")
        if os.path.isdir(d)
    ]
    current = os.environ.get("PATH", "")
    current_set = set(current.split(os.pathsep))
    added = [d for d in extra_dirs if d not in current_set]
    if added:
        os.environ["PATH"] = os.pathsep.join(added) + os.pathsep + current
        print(f"  Updated PATH with: {', '.join(added)}")


def ensure_system_tools() -> None:
    """Check that required system tools are present; install any that are missing."""
    system = platform.system()
    missing = [
        (cmd, desc) for cmd, desc in _REQUIRED_SYSTEM_TOOLS
        if shutil.which(cmd) is None
    ]

    if not missing:
        return

    print("Missing system tools detected:")
    for cmd, desc in missing:
        print(f"  - {cmd} ({desc})")
    print()

    for cmd, desc in missing:
        if not _install_system_tool(cmd, desc, system):
            sys.exit(1)
        _refresh_path()
        if shutil.which(cmd) is None:
            print(
                f"WARNING: '{cmd}' still not found on PATH after install. "
                "You may need to restart your terminal.",
                file=sys.stderr,
            )
            sys.exit(1)

    print("System tools ready.\n")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_setup() -> dict[str, str]:
    """Full startup check: Python version → config → system tools.

    Returns the loaded config dict (contains github_token and any other keys).
    """
    check_python_version()
    cfg = load_config()
    ensure_system_tools()
    return cfg


# ---------------------------------------------------------------------------
# Standalone usage
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_setup()
    print("\nAll checks passed. CoderAgent is ready to run.")
