# AGENTS.md — Best Practices for Coding Agents

Guidelines and conventions for working with and building coding agents in this repository.

---

## 1. Design Before You Code

- **Create a design doc first.** Before implementing a feature, write a brief design document in Markdown covering goals, approach, trade-offs, and edge cases. Store it in `docs/` (e.g., `docs/design-feature-name.md`).
- **Use Mermaid for all diagrams.** Architecture, data flow, sequence, and component diagrams must use Mermaid syntax in fenced code blocks. Do not use ASCII art for diagrams with more than three nodes or any branching.
- **Define API contracts early.** Document function signatures, input/output types, and error behaviors before writing implementation code. This prevents rework and keeps the agent aligned with expectations.
- **Scope deliberately.** Break large tasks into small, well-defined units of work. Each unit should be independently testable and commitable.

## 2. Iterative Development Cycle

Follow this loop for every feature or change:

1. **Plan** — Read the task, examine relevant code, outline your approach.
2. **Implement** — Write the minimal code to achieve the goal. Avoid over-engineering.
3. **Test** — Run existing tests, add new unit tests for new behavior.
4. **Commit** — Stage and commit with a clear, descriptive message.
5. **Review** — Re-read your changes. Check for regressions, unused code, and missed edge cases.
6. **Repeat** — Move to the next unit of work.

Do not skip steps. Small, frequent iterations catch problems early and keep progress visible.

## 3. Documentation

- **Write all documentation in Markdown.** Design docs, API references, guides, and READMEs must be `.md` files committed to the repo. Do not produce Word, PDF, or other binary document formats.
- Every public function must have a docstring explaining its purpose, parameters, return value, and any exceptions raised.
- Keep the module-level docstring in each file up to date with a summary of what the file contains.
- **Include Mermaid diagrams** in documentation where they clarify architecture, data flow, or component relationships. Diagrams are version-controlled and render natively on GitHub.

## 4. Testing

- **Add unit tests after adding features.** Every new function should have corresponding tests.
- **Test edge cases.** Empty inputs, missing files, timeouts, malformed data.
- **Run the full test suite before committing.** Do not commit code that breaks existing tests.
- **Keep tests fast.** Mock external dependencies (network, file I/O, subprocess calls) so tests run in seconds, not minutes.
- Place tests in a `tests/` directory, mirroring the source structure (e.g., `tests/test_agent.py` for `agent.py`).

## 5. Code Organization & Modularity

- **One concern per file.** Setup/config logic lives in `setup.py`. The main agent loop lives in `agent.py`.
- **Avoid circular imports.** Keep dependency flow one-directional: `agent.py` → `setup.py`.
- **Extract shared utilities** into a `utils.py` if helpers are used across multiple files.
- The Copilot CLI handles all tooling natively — no custom tool implementations needed.

## 6. Commit Practices

- **Commit early, commit often.** Each commit should represent one logical change.
- **Write descriptive commit messages.** First line: what changed (imperative mood, ≤72 chars). Body: why, if non-obvious.
- **Do not commit generated files, logs, or secrets.** Ensure `.gitignore` covers `logs/`, `InternalLogs/`, `*.log`, `.env`, `agent_scratchpad.md`, and `.agent_done`.

## 7. Error Handling

- Validate inputs at system boundaries (CLI args, config file reads).
- Return meaningful error messages — the user needs to understand what went wrong.
- Do not swallow exceptions silently. Log them, then return or re-raise as appropriate.

## 8. Security

- **Never hardcode tokens or secrets.** Use environment variables or config files excluded from version control.
- **Validate file paths** to prevent path traversal.
- The GitHub token is passed as `GITHUB_TOKEN` env var to the Copilot CLI subprocess — never logged or printed.

## 9. Configuration

- Use `CoderAgentConfig.yaml` (copied from `CoderAgentConfig.example.yaml`) for runtime settings.
- Provide sensible defaults for all config values so the agent works out of the box.
- Document every config option in the example file.

## 10. Agent Prompt Hygiene

- Keep task prompts focused and specific. One clear objective per prompt.
- Use the scratchpad (`agent_scratchpad.md`) to carry context between iterations — what was done, what remains, any blockers.
- Signal completion by creating `.agent_done` only when the task is truly finished and committed.
