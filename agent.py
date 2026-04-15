#!/usr/bin/env python3
"""
agent.py — GitHub Copilot SDK coding agent loop

Drives the GitHub Copilot SDK Python client in an iterative loop.
Each iteration:
  1. Re-reads your task prompt (editable while running).
  2. Sends it to a fresh Copilot SDK session with streaming output.
  3. Waits for the model to finish (SessionIdle event).
  4. Checks git commits and logs changes.
  5. Waits --delay seconds, then repeats.

Custom tools registered with the agent every session:
  analyze_image — Submit an image file path + question; returns vision analysis.

Usage:
    python agent.py --prompt prompt.md
    python agent.py --prompt prompt.md --max-iterations 10
    python agent.py --prompt prompt.md --dir ../MyProject --dir ../Shared
    python agent.py --prompt prompt.md --delay 15 --model claude-opus-4.6
    python agent.py --prompt prompt.md --image screenshot.png
    python agent.py --prompt prompt.md --once
    python agent.py --prompt prompt.md --dry-run

Prerequisites:
    - Python 3.10+
    - github-copilot-sdk  (auto-installed by setup.py)
    - A GitHub fine-grained PAT with Copilot → Read-only permission
"""

import asyncio
import subprocess
import sys
import os
import time
import shutil
import argparse
import base64
import mimetypes
from pathlib import Path
from datetime import datetime

from setup import run_setup

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "claude-opus-4.6"
DEFAULT_DELAY = 30           # seconds between iterations
DEFAULT_ITERATION_TIMEOUT = 3600  # kill after 60 minutes total per iteration
DONE_SIGNAL_FILE = ".agent_done"  # agent creates this file to signal completion

# Force UTF-8 on Windows
if sys.platform == "win32":
    os.system("chcp 65001 > nul 2>&1")
    os.environ["PYTHONIOENCODING"] = "utf-8"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_file = None


def init_log(log_dir: Path) -> Path:
    """Open a timestamped log file and return its path."""
    global _log_file
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"agent_{stamp}.log"
    _log_file = open(log_path, "w", encoding="utf-8")
    log(f"Log started at {datetime.now().isoformat()}")
    return log_path


def close_log():
    global _log_file
    if _log_file:
        log(f"Log ended at {datetime.now().isoformat()}")
        _log_file.close()
        _log_file = None


def log(message: str):
    global _log_file
    if _log_file:
        _log_file.write(message + "\n")
        _log_file.flush()


def log_section(label: str, content: str):
    log(f"\n{'=' * 60}")
    log(f"{label}  [{datetime.now().isoformat()}]")
    log(f"{'=' * 60}")
    log(content)
    log(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git_head(cwd: Path) -> str:
    """Return the current HEAD commit hash, or '' on failure."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd), capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def git_new_commits(cwd: Path, old_sha: str, new_sha: str) -> list[tuple[str, str]]:
    """Return a list of (hash, message) for commits between old_sha and new_sha."""
    try:
        if old_sha:
            cmd = ["git", "log", "--format=%H%n%B%n---END---", f"{old_sha}..{new_sha}"]
        else:
            # No previous HEAD (first commit(s) in the repo)
            cmd = ["git", "log", "--format=%H%n%B%n---END---", new_sha]
        r = subprocess.run(
            cmd,
            cwd=str(cwd), capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        commits = []
        entries = r.stdout.split("---END---")
        for entry in entries:
            lines = entry.strip().splitlines()
            if not lines:
                continue
            sha = lines[0].strip()
            message = "\n".join(lines[1:]).strip()
            if sha:
                commits.append((sha, message))
        return commits
    except Exception:
        return []


def git_has_uncommitted(cwd: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(cwd), capture_output=True, text=True, timeout=10,
        )
        return bool(r.stdout.strip())
    except Exception:
        return False


def git_diff_stat(cwd: Path, sha: str) -> str:
    """Return the --stat output for a single commit."""
    try:
        r = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--stat", "-r", sha],
            cwd=str(cwd), capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def git_changed_files(cwd: Path, sha: str) -> list[str]:
    """Return list of files changed in a single commit."""
    try:
        r = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
            cwd=str(cwd), capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            return [f for f in r.stdout.strip().splitlines() if f]
        return []
    except Exception:
        return []


def git_diff_patch(cwd: Path, sha: str, max_bytes: int = 8000) -> str:
    """Return the unified diff (patch) for a single commit, truncated if large."""
    try:
        r = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "-p", "-r", sha],
            cwd=str(cwd), capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return ""
        patch = r.stdout.strip()
        if len(patch) > max_bytes:
            patch = patch[:max_bytes] + "\n... (diff truncated)"
        return patch
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Internal commit logging
# ---------------------------------------------------------------------------
AGENT_DIR = Path(__file__).resolve().parent
INTERNAL_LOGS_DIR = AGENT_DIR / "InternalLogs"


def init_internal_logs():
    """Create the InternalLogs directory if it doesn't exist."""
    INTERNAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)


def log_commits(cwd: Path, old_sha: str, new_sha: str):
    """Write a timestamped log file for each new commit."""
    commits = git_new_commits(cwd, old_sha, new_sha)
    for sha, message in commits:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{stamp}_{sha[:8]}.log"
        log_path = INTERNAL_LOGS_DIR / filename
        log_path.write_text(
            f"Timestamp: {datetime.now().isoformat()}\n"
            f"Commit:    {sha}\n\n"
            f"{message}\n",
            encoding="utf-8",
        )
        log(f"Commit log written: {log_path}")


COMMIT_LOG_FILE = "commit_log.md"


def append_commit_log(cwd: Path, old_sha: str, new_sha: str):
    """Append human-readable entries to commit_log.md in the working directory."""
    commits = git_new_commits(cwd, old_sha, new_sha)
    if not commits:
        return

    log_path = cwd / COMMIT_LOG_FILE

    # Create the file with a header if it doesn't exist yet
    if not log_path.exists():
        log_path.write_text(
            "# Commit Log\n\n"
            "Auto-generated by CoderAgent. Each entry describes a commit: "
            "what changed, why, and which files were affected.\n\n",
            encoding="utf-8",
        )

    entries = []
    for sha, message in commits:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        changed_files = git_changed_files(cwd, sha)
        diff_stat = git_diff_stat(cwd, sha)
        patch = git_diff_patch(cwd, sha)

        # Split commit message into subject and body
        msg_lines = message.strip().splitlines()
        subject = msg_lines[0] if msg_lines else "(no message)"
        body = "\n".join(msg_lines[1:]).strip() if len(msg_lines) > 1 else ""

        entry = f"---\n\n"
        entry += f"## `{sha[:8]}` — {subject}\n\n"
        entry += f"**Date:** {stamp}\n\n"

        if body:
            entry += f"**Details:**\n\n{body}\n\n"

        if changed_files:
            entry += f"**Files changed ({len(changed_files)}):**\n\n"
            for f in changed_files:
                entry += f"- `{f}`\n"
            entry += "\n"

        if diff_stat:
            entry += f"**Diff summary:**\n\n```\n{diff_stat}\n```\n\n"

        if patch:
            entry += f"**Changes:**\n\n```diff\n{patch}\n```\n\n"

        entries.append(entry)

    with open(log_path, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(entry)

    log(f"Commit log updated: {log_path} ({len(entries)} new entries)")


# ---------------------------------------------------------------------------
# Prompt handling
# ---------------------------------------------------------------------------

def load_prompt(path: Path) -> str:
    """Read the user prompt file, creating it from the example template if needed."""
    if not path.exists():
        example = path.parent / "prompt.example.md"
        if example.exists():
            shutil.copy2(example, path)
            print(f"Created {path.name} from example template.")
            print(f"Please edit {path} with your task, then re-run the agent.")
            sys.exit(1)
        print(f"ERROR: Prompt file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def load_scratchpad(work_dir: Path) -> str:
    """Read the agent scratchpad file, or return '' if it doesn't exist yet."""
    pad = work_dir / "agent_scratchpad.md"
    if pad.exists():
        return pad.read_text(encoding="utf-8")
    return ""


def check_done_signal(work_dir: Path) -> bool:
    """Check if the agent signalled task completion; remove the file if found."""
    signal = work_dir / DONE_SIGNAL_FILE
    if signal.exists():
        signal.unlink()
        return True
    return False


def build_full_prompt(user_prompt: str, iteration: int, scratchpad: str,
                      work_dir: Path, extra_dirs: list[Path]) -> str:
    """Wrap the user prompt with directory context, scratchpad, and housekeeping."""
    if scratchpad.strip():
        scratchpad_section = (
            "\n---\n\n"
            "## Scratchpad (your notes from the previous iteration)\n\n"
            f"{scratchpad}\n"
        )
    else:
        scratchpad_section = (
            "\n---\n\n"
            "## Scratchpad\n\n"
            "*(empty — first iteration, or no notes were saved)*\n"
        )

    dirs_info = f"Primary working directory: `{work_dir}`\n"
    if extra_dirs:
        dirs_info += "Additional directories available:\n"
        for d in extra_dirs:
            dirs_info += f"  - `{d}`\n"

    return f"""## Iteration {iteration}

{dirs_info}
{user_prompt}
{scratchpad_section}
---

## Housekeeping (always follow these)

1. **Commit regularly.** After every meaningful change, stage and commit with a
   clear message describing what you did.  Small, frequent commits are better
   than one large commit at the end.
2. **Log your progress.** Before starting work, briefly state your plan.  After
   completing a step, summarize what was done and what remains.
3. **Stay on task.** Focus only on the instructions above.  Do not refactor
   unrelated code or add features that were not requested.
4. **Stop when done.** When the task is fully complete and there is nothing left
   to do, create an empty file called `.agent_done` in the working directory
   (e.g. `touch .agent_done`).  This signals the outer loop to stop.  Commit
   your work first.
5. **Update the scratchpad.** Before stopping, write notes to
   `agent_scratchpad.md` in the working directory.  Include:
   - What you accomplished this iteration
   - What still needs to be done
   - Any problems, blockers, or decisions for the next iteration
   - Key file paths or context the next iteration will need
   Do NOT commit this file — it is git-ignored.
6. **Analyze images when needed.** Use the `analyze_image` tool to examine any
   image file.  Pass the file path and a specific question about the image.
"""


# ---------------------------------------------------------------------------
# Custom tools
# ---------------------------------------------------------------------------

def _build_custom_tools(github_token: str, model: str) -> list:
    """Build and return the list of custom tools to register with each session.

    Tools are created fresh each call so closures over github_token/model
    are always current.

    Available custom tools
    ----------------------
    analyze_image
        Analyze an image file (JPEG, PNG, GIF, WebP, BMP, …) using vision AI.
        The agent passes an image path and a specific question; the tool spins
        up a short-lived Copilot session with the image attached and returns
        a text answer.  This lets the agent examine diagrams, screenshots,
        UI mockups, or any other visual artifact in the working directory
        without leaving its current session.
    """
    # Deferred imports — SDK may not be installed until setup.py runs
    from copilot import CopilotClient, SubprocessConfig, define_tool  # noqa: F401
    from copilot.session import PermissionHandler
    from copilot.generated.session_events import (
        AssistantMessageData,
        SessionIdleData,
    )
    from pydantic import BaseModel, Field

    class AnalyzeImageParams(BaseModel):
        image_path: str = Field(
            description=(
                "Path to the image file to analyze.  "
                "Can be absolute or relative to the working directory."
            )
        )
        question: str = Field(
            description="Specific question to answer about the image contents."
        )

    @define_tool(
        description=(
            "Analyze an image file using vision AI and answer a specific question "
            "about it.  Supports JPEG, PNG, GIF, WebP, BMP and other common "
            "image formats.  Returns a detailed text answer."
        )
    )
    async def analyze_image(params: AnalyzeImageParams) -> str:
        path = Path(params.image_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return f"Error: image file not found: {params.image_path}"

        try:
            image_bytes = path.read_bytes()
            image_data = base64.b64encode(image_bytes).decode("utf-8")
        except OSError as exc:
            return f"Error reading image: {exc}"

        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = "image/jpeg"

        try:
            async with CopilotClient(
                SubprocessConfig(github_token=github_token)
            ) as vision_client:
                async with await vision_client.create_session(
                    on_permission_request=PermissionHandler.approve_all,
                    model=model,
                ) as vision_session:
                    done_evt = asyncio.Event()
                    result_parts: list[str] = []

                    def on_vision_event(event):
                        match event.data:
                            case AssistantMessageData() as data:
                                result_parts.append(data.content)
                            case SessionIdleData():
                                done_evt.set()

                    vision_session.on(on_vision_event)
                    await vision_session.send(
                        params.question,
                        attachments=[{
                            "type": "blob",
                            "data": image_data,
                            "mimeType": mime_type,
                        }],
                    )
                    try:
                        await asyncio.wait_for(done_evt.wait(), timeout=120)
                    except asyncio.TimeoutError:
                        return "Vision analysis timed out after 120 s."

                    return result_parts[0] if result_parts else "(no analysis returned)"
        except asyncio.TimeoutError:
            return "Vision analysis timed out."
        except (OSError, ValueError) as exc:
            return f"Error during vision analysis: {exc}"
        except asyncio.CancelledError:
            raise

    return [analyze_image]


# ---------------------------------------------------------------------------
# SDK agent session
# ---------------------------------------------------------------------------

async def run_agent(
    prompt: str,
    *,
    github_token: str,
    model: str,
    work_dir: Path,
    iteration: int,
    image_paths: list[Path],
    iteration_timeout: int = DEFAULT_ITERATION_TIMEOUT,
) -> bool:
    """Run one agent iteration using the Copilot SDK.

    Opens a fresh CopilotClient + session, streams output to the terminal and
    the log file, then waits for the SessionIdle event (model finished) or the
    iteration timeout.

    Returns True on successful completion, False on timeout or error.
    """
    # Deferred SDK imports
    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler, PermissionRequestResult  # noqa: F401
    from copilot.generated.session_events import (
        AssistantMessageData,
        AssistantMessageDeltaData,
        AssistantReasoningData,
        AssistantReasoningDeltaData,
        SessionIdleData,
    )

    print()
    print("=" * 60)
    print(f"  Iteration {iteration}  |  model: {model}")
    print("=" * 60)

    log_section(f"PROMPT (iteration {iteration})", prompt)

    # ------------------------------------------------------------------
    # Build image attachments from --image flags
    # ------------------------------------------------------------------
    attachments: list[dict] = []
    for img_path in image_paths:
        if not img_path.exists():
            print(f"  WARNING: Image not found, skipping: {img_path}", flush=True)
            log(f"WARNING: Image not found: {img_path}")
            continue
        try:
            image_data = base64.b64encode(img_path.read_bytes()).decode("utf-8")
            mime_type, _ = mimetypes.guess_type(str(img_path))
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = "image/jpeg"
            attachments.append({
                "type": "blob",
                "data": image_data,
                "mimeType": mime_type,
            })
            print(f"  Attached image: {img_path.name}", flush=True)
            log(f"Attached image: {img_path}")
        except OSError as exc:
            print(f"  WARNING: Could not read {img_path.name}: {exc}", flush=True)
            log(f"WARNING: Could not read image {img_path}: {exc}")

    # ------------------------------------------------------------------
    # Permission handler — approve all, with terminal + log output
    # ------------------------------------------------------------------
    def on_permission(request, invocation) -> "PermissionRequestResult":
        kind = getattr(request.kind, "value", str(request.kind))
        if kind == "shell":
            cmd_text = getattr(request, "full_command_text", "")
            log(f"[TOOL] shell: {cmd_text}")
            print(f"\n  ▶ shell: {cmd_text}", flush=True)
        elif kind == "write":
            fname = getattr(request, "file_name", "")
            log(f"[TOOL] write: {fname}")
            print(f"\n  ▶ write: {fname}", flush=True)
        elif kind == "custom-tool":
            tool_name = getattr(request, "tool_name", "")
            log(f"[TOOL] custom: {tool_name}")
            print(f"\n  ▶ tool: {tool_name}", flush=True)
        elif kind not in ("read", "memory"):
            log(f"[TOOL] {kind}")
        return PermissionRequestResult(kind="approved")

    # ------------------------------------------------------------------
    # User-input handler — relay agent questions to the terminal
    # ------------------------------------------------------------------
    async def on_user_input(request, invocation) -> dict:
        question = request.get("question", "")
        choices = request.get("choices")
        log(f"[AGENT QUESTION] {question}")
        print(f"\n  Agent asks: {question}", flush=True)
        if choices:
            for idx, choice in enumerate(choices, 1):
                print(f"    {idx}. {choice}")
        try:
            loop = asyncio.get_running_loop()
            answer = await loop.run_in_executor(
                None, lambda: input("  Your answer: ")
            )
            return {"answer": answer.strip(), "wasFreeform": True}
        except (EOFError, KeyboardInterrupt):
            return {"answer": "", "wasFreeform": True}

    # ------------------------------------------------------------------
    # Event handler — stream output to terminal and log
    # ------------------------------------------------------------------
    output_parts: list[str] = []
    done_event = asyncio.Event()

    def on_event(event) -> None:
        match event.data:
            case AssistantMessageDeltaData() as data:
                delta = data.delta_content or ""
                if delta:
                    print(delta, end="", flush=True)
                    output_parts.append(delta)
                    log(delta)
            case AssistantReasoningDeltaData() as data:
                delta = data.delta_content or ""
                if delta:
                    log(f"[REASONING] {delta}")
            case AssistantMessageData() as data:
                # Final full message — only print if streaming gave us nothing
                if not output_parts:
                    print(data.content, flush=True)
                    log(data.content)
            case AssistantReasoningData():
                pass  # reasoning already captured via delta events
            case SessionIdleData():
                done_event.set()

    # ------------------------------------------------------------------
    # Custom tools
    # ------------------------------------------------------------------
    custom_tools = _build_custom_tools(github_token=github_token, model=model)

    # ------------------------------------------------------------------
    # Run the session
    # ------------------------------------------------------------------
    config = SubprocessConfig(
        github_token=github_token,
        cwd=str(work_dir),
    )

    try:
        async with CopilotClient(config) as client:
            create_kwargs: dict = dict(
                on_permission_request=on_permission,
                on_user_input_request=on_user_input,
                model=model,
                tools=custom_tools,
                streaming=True,
            )
            async with await client.create_session(**create_kwargs) as session:
                session.on(on_event)

                send_kwargs: dict = {}
                if attachments:
                    send_kwargs["attachments"] = attachments

                await session.send(prompt, **send_kwargs)

                try:
                    await asyncio.wait_for(done_event.wait(), timeout=iteration_timeout)
                except asyncio.TimeoutError:
                    msg = (
                        f"\nTIMEOUT: Iteration {iteration} exceeded "
                        f"{iteration_timeout}s — aborting."
                    )
                    print(msg, flush=True)
                    log(msg)
                    return False

        log_section(f"OUTPUT (iteration {iteration})", "".join(output_parts))
        return True

    except KeyboardInterrupt:
        raise
    except asyncio.CancelledError:
        raise
    except (OSError, RuntimeError, ConnectionError) as exc:
        print(f"\nERROR in agent session: {exc}", file=sys.stderr, flush=True)
        log(f"ERROR: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main async loop
# ---------------------------------------------------------------------------

async def async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a GitHub Copilot SDK coding agent in a loop",
    )
    parser.add_argument(
        "--prompt", required=True, metavar="FILE",
        help="Path to the Markdown file containing the task prompt",
    )
    parser.add_argument(
        "--dir", action="append", default=[], metavar="PATH",
        help=(
            "Working directory for the agent (repeatable). "
            "The first --dir is the primary working directory; "
            "additional --dir values are mentioned in the prompt. "
            "Defaults to the current directory."
        ),
    )
    parser.add_argument(
        "--image", action="append", default=[], metavar="FILE",
        help=(
            "Image file to attach to the initial prompt (repeatable). "
            "The model can see and reason about these images. "
            "The agent can also call analyze_image() at any time."
        ),
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Copilot model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--delay", type=int, default=DEFAULT_DELAY, metavar="SECONDS",
        help=f"Seconds to wait between iterations (default: {DEFAULT_DELAY})",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=0, metavar="N",
        help="Stop after N iterations (0 = unlimited, default: 0)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run exactly one iteration then exit (shorthand for --max-iterations 1)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the full prompt and exit without running the agent",
    )
    parser.add_argument(
        "--iteration-timeout", type=int, default=DEFAULT_ITERATION_TIMEOUT,
        metavar="SECONDS",
        help=(
            f"Max seconds per iteration before aborting "
            f"(default: {DEFAULT_ITERATION_TIMEOUT}, 0=disabled)"
        ),
    )

    args = parser.parse_args()

    # Load config, verify Python version, install/verify SDK
    cfg = run_setup()
    github_token: str = cfg.get("github_token", "")

    # Resolve directories
    work_dir = Path(args.dir[0]).resolve() if args.dir else Path.cwd().resolve()
    extra_dirs = [Path(d).resolve() for d in args.dir[1:]]
    image_paths = [Path(p).resolve() for p in args.image]

    prompt_path = Path(args.prompt).resolve()
    user_prompt = load_prompt(prompt_path)

    if args.once:
        args.max_iterations = 1

    # Dry run — print prompt and exit
    if args.dry_run:
        scratchpad = load_scratchpad(work_dir)
        full = build_full_prompt(
            user_prompt, iteration=1, scratchpad=scratchpad,
            work_dir=work_dir, extra_dirs=extra_dirs,
        )
        print(full)
        sys.exit(0)

    # Init logging
    log_dir = work_dir / "logs"
    log_path = init_log(log_dir)
    init_internal_logs()

    print(f"Prompt:          {prompt_path}")
    print(f"Working dir:     {work_dir}")
    print(f"Extra dirs:      {extra_dirs or '(none)'}")
    if image_paths:
        print(f"Images:          {[str(p) for p in image_paths]}")
    print(f"Model:           {args.model}")
    print(f"Delay:           {args.delay}s")
    print(f"Iter timeout:    {args.iteration_timeout}s")
    print(f"Max iters:       {args.max_iterations or 'unlimited'}")
    print(f"Log file:        {log_path}")
    print()

    log(f"Prompt file: {prompt_path}")
    log(f"Working dir: {work_dir}")
    log(f"Model: {args.model}")
    log(f"Max iterations: {args.max_iterations or 'unlimited'}")

    # Clear any stale done signal from a previous run
    stale_signal = work_dir / DONE_SIGNAL_FILE
    if stale_signal.exists():
        stale_signal.unlink()
        log("Cleared stale .agent_done signal from previous run.")

    iteration = 0
    try:
        while True:
            iteration += 1

            if args.max_iterations and iteration > args.max_iterations:
                break

            # Re-read prompt each iteration so the user can steer mid-flight
            user_prompt = load_prompt(prompt_path)
            scratchpad = load_scratchpad(work_dir)
            full_prompt = build_full_prompt(
                user_prompt, iteration, scratchpad, work_dir, extra_dirs
            )

            commit_before = git_head(work_dir)

            # Images are only attached on the first iteration
            current_images = image_paths if iteration == 1 else []

            await run_agent(
                full_prompt,
                github_token=github_token,
                model=args.model,
                work_dir=work_dir,
                iteration=iteration,
                image_paths=current_images,
                iteration_timeout=args.iteration_timeout,
            )

            # Track commits made during this iteration
            commit_after = git_head(work_dir)
            if commit_after and commit_before != commit_after:
                msg = f"Agent committed (HEAD now {commit_after[:8]})"
                print(f"\n>> {msg}")
                log(msg)
                log_commits(work_dir, commit_before, commit_after)
                append_commit_log(work_dir, commit_before, commit_after)
            elif commit_after and git_has_uncommitted(work_dir):
                msg = "WARNING: Agent did NOT commit. Uncommitted changes detected."
                print(f"\n>> {msg}")
                log(msg)
            else:
                log("No commit and no uncommitted changes this iteration.")

            # Check for early-exit signal from the agent
            if check_done_signal(work_dir):
                msg = "Agent signalled TASK COMPLETE — stopping."
                print(f"\n>> {msg}")
                log(msg)
                break

            # Delay before next iteration (skip after last iteration)
            is_last = args.max_iterations and iteration >= args.max_iterations
            if not is_last and args.delay > 0:
                print(f"\nWaiting {args.delay}s before next iteration…")
                log(f"Waiting {args.delay}s…")
                await asyncio.sleep(args.delay)

    except KeyboardInterrupt:
        print("\n\nStopped by user (Ctrl-C).")
        log("Stopped by user.")
    finally:
        print()
        print("=" * 60)
        print(f"Session complete.  {iteration} iteration(s) run.")
        print(f"Log: {log_path}")
        print("=" * 60)
        close_log()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
