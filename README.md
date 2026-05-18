# CoderAgent

A programmable coding agent that runs in a loop, powered by [GitHub Copilot CLI](https://github.com/github/copilot-cli).

You describe a task in a Markdown file.  The agent reads your instructions, launches the Copilot CLI which uses AI to write and edit code, run shell commands, and commit work — then loops back to pick up where it left off.  Press **Ctrl-C** to stop at any time.

---

## Table of Contents

1. [What is an agent?](#what-is-an-agent)
2. [What does CoderAgent do?](#what-does-coderagent-do)
3. [Requirements](#requirements)
4. [Quick Start](#quick-start)
5. [Configuration](#configuration)
6. [Tooling capabilities](#tooling-capabilities)
7. [CLI reference](#cli-reference)
8. [Writing effective prompts](#writing-effective-prompts)
9. [Platform support](#platform-support)
10. [Logs](#logs)
11. [Troubleshooting](#troubleshooting)

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

CoderAgent is a thin loop built on top of the GitHub Copilot CLI.  Each iteration it:

1. Reads your `prompt.md` task file (you can edit it while the loop is running).
2. Launches the `copilot` CLI in your target working directory with the prompt piped to stdin.
3. The CLI's built-in agentic capabilities handle file editing, shell commands, and image analysis.
4. Waits for the CLI to finish, then checks whether anything was committed to git.
5. Waits a configurable delay, then runs the next iteration.

The loop continues indefinitely until you press **Ctrl-C**, the agent creates a `.agent_done` signal file, or you set `--max-iterations`.

---

## Requirements

| Requirement | Detail |
|---|---|
| **Python** | 3.10 or newer |
| **GitHub account** | With an active [GitHub Copilot](https://github.com/features/copilot) subscription |
| **Personal access token** | Fine-Grained PAT (`github_pat_`) with Copilot Requests permission |
| **git** | Auto-installed if missing |
| **GitHub Copilot CLI** | Auto-installed via npm/winget if missing |

### Generating a GitHub Token

> **Important:** You **must** use a **Fine-Grained Personal Access Token** (`github_pat_`).
> Classic tokens (`ghp_`) are **not supported**.

1. Go to **https://github.com/settings/personal-access-tokens/new**.
2. Give it a descriptive name (e.g., `CoderAgent`).
3. Set an expiration date.
4. Under **Permissions**, click "add permissions" and select:
   - **Copilot Requests**
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
git clone https://github.com/JChanOnto/github-copilot-cli-agent.git
cd github-copilot-cli-agent

# 2. Run setup — creates CoderAgentConfig.yaml from the template
python setup.py
#    Edit CoderAgentConfig.yaml and paste your github_pat_ token, then continue.

# 3. Start the agent (first run auto-creates prompt.md from the template)
python agent.py --prompt prompt.md --dir ../MyProject

# 4. Edit prompt.md with your task description, then run the agent again
python agent.py --prompt prompt.md --dir ../MyProject
```

---

## Configuration

All runtime configuration lives in `CoderAgentConfig.yaml` (created on first run from `CoderAgentConfig.example.yaml`).

| Key | Required | Description |
|---|---|---|
| `github_token` | Yes | Your Fine-Grained PAT (`github_pat_…`) with Copilot Requests permission |

The token is exported as `GITHUB_TOKEN` when launching the Copilot CLI, so authentication is handled automatically.

---

## Tooling capabilities

The GitHub Copilot CLI provides all tools natively:

| Tool | Description |
|---|---|
| **File read/write** | Read, create, and edit files in the working directory |
| **Shell execution** | Run arbitrary shell commands |
| **Vision/Images** | Analyze images with vision-capable models (built-in) |
| **MCP servers** | Extend capabilities via custom MCP servers |
| **GitHub integration** | Access repos, issues, PRs via natural language |

No custom tool implementations are needed — the CLI handles everything.

---

## CLI reference

```
python agent.py --prompt FILE [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--prompt FILE` | *(required)* | Path to the Markdown task prompt |
| `--dir PATH` | `.` | Working directory (repeatable) |
| `--model NAME` | `claude-sonnet-4` | Model to use |
| `--delay N` | `30` | Seconds between iterations |
| `--max-iterations N` | `0` (unlimited) | Stop after N iterations |
| `--once` | — | Run one iteration then exit |
| `--dry-run` | — | Print the full prompt and exit |
| `--iteration-timeout N` | `3600` | Max seconds per iteration |

---

## Writing effective prompts

See `prompt.example.md` for the template.  Tips:

- **Be specific.** Name the files, functions, and behaviors you want.
- **Give numbered steps.** Ordered workflows are easier for the agent to follow.
- **Set constraints.** Tell the agent what *not* to touch.
- **Point to context.** Reference key files and directories the agent should read first.

---

## Platform support

| Platform | Install method |
|---|---|
| Windows | `winget install GitHub.Copilot` or `npm install -g @github/copilot` |
| macOS | `brew install copilot-cli` or `npm install -g @github/copilot` |
| Linux | `npm install -g @github/copilot` or install script |

The agent's `setup.py` will auto-install the Copilot CLI if it's not found on PATH.

---

## Logs

- **Per-iteration logs** are written to `<work_dir>/logs/agent_YYYYMMDD_HHMMSS.log`.
- **Commit logs** are appended to `<work_dir>/commit_log.md`.
- **Internal commit records** are saved in `InternalLogs/` next to `agent.py`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `copilot` not found | Run `python setup.py` or install manually: `npm install -g @github/copilot` |
| Token rejected | Ensure you're using a Fine-Grained PAT with Copilot Requests permission |
| Agent loops without progress | Edit `prompt.md` to be more specific; check `agent_scratchpad.md` |
| Timeout every iteration | Increase `--iteration-timeout` or simplify the task |

