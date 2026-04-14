# CoderAgent

A programmable coding agent that runs in a loop, powered by the [GitHub Copilot Python SDK](https://github.com/github/copilot-sdk).

You describe a task in a Markdown file.  The agent reads your instructions, uses the same AI model that drives GitHub Copilot in your editor, writes and edits code, runs shell commands, and commits its work — then loops back to pick up where it left off.  Press **Ctrl-C** to stop at any time.

---

## Table of Contents

1. [What is an agent?](#what-is-an-agent)
2. [What does CoderAgent do?](#what-does-coderagent-do)
3. [Requirements](#requirements)
4. [Quick Start](#quick-start)
5. [Configuration](#configuration)
6. [How it works](#how-it-works)
7. [Tooling capabilities](#tooling-capabilities)
8. [CLI reference](#cli-reference)
9. [Writing effective prompts](#writing-effective-prompts)
10. [Platform support](#platform-support)
11. [Logs](#logs)
12. [Troubleshooting](#troubleshooting)

---

## What is an agent?

In software, an **AI agent** is a program that:

1. Receives a goal written in plain English (a *prompt*).
2. Reasons about what steps to take.
3. Uses **tools** — reading files, writing files, running shell commands, fetching web pages — to carry out those steps.
4. Observes the results and decides what to do next.
5. Repeats until the goal is achieved.

Think of it as autocomplete taken to its logical conclusion: instead of completing one line of code, the model completes an entire task.  The key difference from a plain LLM chatbot is that the agent can *act* — it does not just generate text, it executes code and modifies files.

---

## What does CoderAgent do?

CoderAgent is a thin loop built on top of the GitHub Copilot Python SDK.  Each iteration it:

1. Reads your `prompt.md` task file (you can edit it while the loop is running).
2. Opens a fresh Copilot session with streaming output — you see the model's thinking in real time.
3. Gives the agent a full suite of tools (see [Tooling capabilities](#tooling-capabilities)).
4. Waits for the model to finish, then checks whether anything was committed to git.
5. Waits a configurable delay, then runs the next iteration.

The loop continues indefinitely until you press **Ctrl-C**, the agent creates a `.agent_done` signal file, or you set `--max-iterations`.

---

## Requirements

| Requirement | Detail |
|---|---|
| **Python** | 3.10 or newer |
| **GitHub account** | With an active [GitHub Copilot](https://github.com/features/copilot) subscription (a free tier is available) |
| **Personal access token** | Fine-Grained PAT (`github_pat_`) — see below |
| **git** | Auto-installed if missing |
| **github-copilot-sdk** | Auto-installed by `setup.py` on first run |

### Generating a GitHub Token

> **Important:** You **must** use a **Fine-Grained Personal Access Token** (`github_pat_`).
> Classic tokens (`ghp_`) are **not supported**.

1. Go to **https://github.com/settings/personal-access-tokens/new**.
2. Give it a descriptive name (e.g., `CoderAgent`).
3. Set an expiration date.
4. Under **Account permissions**, enable:
   - **GitHub Copilot** → **Read-only**
5. Click **Generate token** and copy the value.
6. Paste it into `CoderAgentConfig.yaml`:
   ```yaml
   github_token: github_pat_your_token_here
   ```

> `CoderAgentConfig.yaml` is listed in `.gitignore` — your token will never be committed.

---

## Quick Start

```bash
# 1. Clone this repo
git clone https://github.com/JChanOnto/github-copilot-sdk-agent.git
cd github-copilot-sdk-agent

# 2. Run setup — creates CoderAgentConfig.yaml from the template
python setup.py
#    Edit CoderAgentConfig.yaml and paste your github_pat_ token, then continue.

# 3. Start the agent (first run auto-creates prompt.md from the template)
python agent.py --prompt prompt.md --dir ../MyProject

# 4. Edit prompt.md with your task description, then run the agent again
python agent.py --prompt prompt.md --dir ../MyProject
```

The first time you run `agent.py`, it will:
- Auto-create `CoderAgentConfig.yaml` and ask you to fill in your token.
- Auto-install `github-copilot-sdk` via pip.
- Auto-create `prompt.md` from `prompt.example.md` and ask you to edit it.

---

## Configuration

`CoderAgentConfig.yaml` lives in the same directory as `agent.py`.  It is loaded on every run.

```yaml
# CoderAgentConfig.yaml
github_token: github_pat_your_token_here
```

| Key | Required | Description |
|---|---|---|
| `github_token` | Yes | Fine-Grained PAT with Copilot → Read-only permission |

`setup.py` validates the token on every start and exits early with clear instructions if anything is wrong.

---

## How it works

```
┌──────────────────────────────────────────────────────┐
│                   Your machine                        │
│                                                       │
│  prompt.md  ──(re-read each iteration)──┐            │
│                                         │            │
│                              ┌──────────▼──────────┐ │
│                              │     agent.py loop   │ │
│                              │                     │ │
│  CoderAgentConfig.yaml ──────►  1. Read prompt     │ │
│  (github_token)              │  2. Open SDK session│ │
│                              │  3. Stream output   │ │
│                              │  4. Track commits   │ │
│                              │  5. Wait & repeat ──┼─┘
│                              └────────┬────────────┘ │
│                                       │ JSON-RPC      │
│                              ┌────────▼────────────┐ │
│                              │  Copilot CLI        │ │
│                              │  (bundled in SDK)   │ │
│                              └────────┬────────────┘ │
│                                       │ HTTPS         │
└───────────────────────────────────────┼──────────────┘
                                        │
                               ┌────────▼────────────┐
                               │  GitHub Copilot API │
                               │  (claude-opus-4.6   │
                               │   or chosen model)  │
                               └─────────────────────┘
```

### Session lifecycle

- Each loop iteration opens a **fresh** Copilot SDK session.  The model sees the full prompt plus notes from the previous iteration (the *scratchpad*).
- The SDK spawns a bundled Copilot CLI process internally and communicates with it over JSON-RPC — no manual CLI installation needed.
- The model streams its response token-by-token directly to your terminal.
- When the model stops generating (the `SessionIdle` event fires), the iteration ends.
- The agent inspects `git log` to see what was committed, logs the diffs, then sleeps for `--delay` seconds before the next iteration.

### Scratchpad

`agent_scratchpad.md` in the working directory is the agent's inter-iteration memory.  The agent is instructed to update it at the end of every iteration with what it did, what remains, and any blockers.  This file is git-ignored and never committed.

---

## Tooling capabilities

The agent has access to two layers of tools:

### Built-in Copilot tools

These are provided by the Copilot CLI and are always available.  The model uses them autonomously — you do not need to call them explicitly.

| Tool | What it does |
|---|---|
| **read_file** | Read any file from the filesystem |
| **edit_file** | Create or overwrite a file |
| **shell** | Execute shell commands (build, test, lint, git, …) |
| **web_search** | Search the web for documentation or answers |
| **web_fetch** | Download the content of a URL |
| **memory** | Store and recall facts across tool calls within a session |

The agent is permitted to use all built-in tools automatically.  Each tool call is logged to your terminal with a `▶` prefix so you can see exactly what the agent is doing.

### Custom tools (registered by CoderAgent)

These tools are defined in `agent.py` and registered with the Copilot SDK.  They extend what the built-in CLI tools provide.

#### `analyze_image`

Analyzes an image file using vision AI and answers a specific question about it.

| Parameter | Type | Description |
|---|---|---|
| `image_path` | string | Path to the image (absolute, or relative to the working directory) |
| `question` | string | A specific question to answer about the image |

**Returns:** A detailed text answer describing or answering the question about the image.

**Supported formats:** JPEG, PNG, GIF, WebP, BMP, and other common image types.

**Example use cases:**
- "What does the UI layout in `screenshot.png` look like?"
- "Are there any error messages visible in `build_output.png`?"
- "Describe the architecture diagram in `design.png`."

The agent calls this tool automatically whenever it needs to understand an image.  You can also attach images up-front with `--image` to give the agent visual context for its first message.

---

## CLI reference

```
python agent.py --prompt FILE [options]
```

### Required

| Flag | Description |
|---|---|
| `--prompt FILE` | Markdown file with your task description. Created from `prompt.example.md` on first run. |

### Directory options

| Flag | Default | Description |
|---|---|---|
| `--dir PATH` | current dir | Working directory for the agent. The first `--dir` is the primary directory (where the agent runs git commands and writes files). Repeatable — extra `--dir` values are mentioned in the prompt. |

### Vision options

| Flag | Description |
|---|---|
| `--image FILE` | Attach an image to the first iteration's prompt. Repeatable. The model can see and describe the image. The agent can also call `analyze_image` at any time. |

### Model options

| Flag | Default | Description |
|---|---|---|
| `--model NAME` | `claude-opus-4.6` | Copilot model to use. Other options include `gpt-5`, `claude-sonnet-4.5`, etc. |

### Loop control

| Flag | Default | Description |
|---|---|---|
| `--delay SECONDS` | `30` | Pause between iterations. |
| `--max-iterations N` | `0` (unlimited) | Stop after N iterations. |
| `--once` | — | Shorthand for `--max-iterations 1`. |
| `--iteration-timeout SECONDS` | `3600` | Abort an iteration if it runs longer than this (0 = disabled). |

### Utility

| Flag | Description |
|---|---|
| `--dry-run` | Print the full expanded prompt and exit without calling the model. Useful for debugging prompts. |

### Examples

```bash
# Basic usage — unlimited loop, 30 s delay
python agent.py --prompt prompt.md --dir ../MyProject

# Single shot — run once and exit
python agent.py --prompt prompt.md --dir ../MyProject --once

# Custom model and faster loop
python agent.py --prompt prompt.md --dir ../MyProject --model gpt-5 --delay 10

# Attach a screenshot for the agent to reference
python agent.py --prompt prompt.md --dir ../MyProject --image designs/wireframe.png

# Attach multiple images
python agent.py --prompt prompt.md --dir ../MyProject \
    --image screenshots/before.png \
    --image screenshots/after.png

# Two directories visible to the agent
python agent.py --prompt prompt.md --dir ../MyProject --dir ../SharedLib

# Preview the prompt without running
python agent.py --prompt prompt.md --dry-run
```

---

## Writing effective prompts

Your prompt file is plain Markdown.  The agent reads it at the start of every iteration, so you can edit it while the loop is running to steer behavior.

The repo includes `prompt.example.md` as a starting template.  Your actual `prompt.md` is git-ignored and stays local.

### Recommended structure

```markdown
## Goal
<!-- What should the agent accomplish?  Be specific. -->
Fix the null-pointer crash in `src/parser.cpp` line 42.

## Context
<!-- What files/directories should the agent read first? -->
- Read `README.md` for project conventions.
- The parser lives in `src/parser.cpp` and `src/parser.h`.
- Tests are in `tests/parser_test.cpp`.

## Steps
1. Read the failing test and understand what input triggers the crash.
2. Read `src/parser.cpp` around line 42.
3. Identify the root cause and implement a fix.
4. Compile with `make` and run `make test`.
5. Commit with a descriptive message.

## Rules
- Do not modify files outside `src/` and `tests/`.
- All existing tests must still pass after the fix.
- Use `make` — do not use CMake directly.
```

### Tips

- **Be specific.** "Fix the crash in `src/parser.cpp` line 42" works better than "fix bugs."
- **Include build/test commands.** Tell the agent exactly how to verify its work: `npm test`, `dotnet test`, `make test`, etc.
- **Steer mid-flight.** Edit `prompt.md` while the loop is running — the next iteration picks up your changes immediately.
- **Use the scratchpad.** The agent writes progress notes to `agent_scratchpad.md` between iterations.  You can read it to see where it left off.

---

## Platform support

| Step | Windows | Linux / macOS |
|---|---|---|
| Python packages | `pip` (auto) | `pip` (auto) |
| Install `git` | `winget` | `apt-get` / `dnf` / `pacman` / `brew` |
| Copilot CLI | Bundled in `github-copilot-sdk` | Bundled in `github-copilot-sdk` |
| Auth | Token passed directly to SDK | Token passed directly to SDK |

The Copilot CLI binary is bundled inside the `github-copilot-sdk` Python package — no separate download or `gh` CLI installation is required.

---

## Logs

All output is written to `<working-dir>/logs/agent_<timestamp>.log`.

Each iteration's full prompt and the complete model response are recorded with timestamps, making it easy to review exactly what the agent did and why.

Additionally, `commit_log.md` in the working directory receives a human-readable entry for every commit the agent makes, including the diff summary and changed files.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `github_token is not set` | Edit `CoderAgentConfig.yaml` and paste your `github_pat_` token. |
| `Classic PATs (ghp_) are NOT supported` | Generate a Fine-Grained PAT at https://github.com/settings/personal-access-tokens/new with **GitHub Copilot → Read-only**. |
| `Could not import Copilot SDK` | Run `pip install github-copilot-sdk` manually, or re-run `python setup.py`. |
| `Python 3.10+ is required` | Download a newer Python from https://python.org/downloads/. |
| `git not found` | `setup.py` tries to install `git` automatically.  If it fails, install git manually from https://git-scm.com/. |
| Agent keeps running without committing | Add explicit commit instructions to your prompt: "After each change, run `git add -A && git commit -m '...'`". |
| TIMEOUT after N seconds | Increase `--iteration-timeout` or break your task into smaller steps. |
| `Permission denied` writing files | In Docker (root container), ensure your working directory is owned by root. On the host: `sudo chown -R $(whoami) <working-dir>`. |

