# CLAUDE.md

This file provides guidance for AI assistants (Claude, Copilot, etc.) working in this repository.

## Repository Overview

**Repository:** `5zdyfr5mc8-star/codex-test`
**Status:** Early-stage / skeleton repository
**Primary branch:** `main`

This repository is currently in an initialization state. The structure and conventions below should be followed as the codebase grows.

## Repository Structure

```
codex-test/
├── CLAUDE.md       # AI assistant guidance (this file)
└── README.md       # Project overview
```

## Git Workflow

### Branch Conventions
- `main` — stable, production-ready code
- `master` — legacy alias (prefer `main`)
- Feature branches: `feature/<short-description>`
- Bug fixes: `fix/<short-description>`
- Claude-generated branches: `claude/<description>-<id>`

### Commit Messages
Use clear, imperative commit messages:
```
Add user authentication module
Fix null pointer in payment handler
Update README with setup instructions
```

### Push Procedure
Always push with tracking:
```bash
git push -u origin <branch-name>
```

If the push fails due to a network error, retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s).

## Development Guidelines

### General Principles
- Keep changes minimal and focused — only modify what is necessary
- Prefer editing existing files over creating new ones
- Do not add unnecessary comments, docstrings, or type annotations to code you didn't change
- Avoid over-engineering — build for current requirements, not hypothetical future ones
- Do not introduce backwards-compatibility shims for unused code

### Security
- Never commit secrets, API keys, or credentials
- Validate all user input at system boundaries
- Avoid command injection, XSS, SQL injection, and other OWASP top-10 vulnerabilities
- Use environment variables for sensitive configuration

### Code Style (language-agnostic defaults)
- Use descriptive, self-explanatory names
- Keep functions small and single-purpose
- Avoid deep nesting — prefer early returns
- Write tests alongside new functionality

## Testing

No test framework is configured yet. When adding tests:
- Place tests in a `tests/` or `__tests__/` directory adjacent to source code
- Follow the naming convention `<filename>.test.<ext>` or `test_<filename>.<ext>`
- Ensure all tests pass before pushing

## Adding a New Language/Framework

When bootstrapping this repo with actual code, update this file with:
1. The chosen language and framework
2. How to install dependencies
3. How to run the project locally
4. How to run tests and linters
5. Any environment variables required (never their values)

## GitHub Integration

- Issues and PRs live at `https://github.com/5zdyfr5mc8-star/codex-test`
- Use GitHub MCP tools (`mcp__github__*`) for all GitHub interactions — do not use `gh` CLI
- Target repository for all operations: `5zdyfr5mc8-star/codex-test`
- Do not interact with repositories outside this scope

## AI Assistant Notes

- Read files before modifying them
- Do not guess at file contents or structure — use available tools to explore first
- Prefer parallel tool calls when operations are independent
- Check for an existing `CLAUDE.md` before creating one — update rather than replace
- When uncertain about scope, ask rather than assume
