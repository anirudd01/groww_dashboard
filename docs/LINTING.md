# Linting

Ruff runs with its **built-in defaults**: there is no `pyproject.toml` or `ruff.toml` here or in any
parent folder (`ruff check -v` logs "Using Ruff default settings"). Ruff 0.17.5's defaults include UP, BLE,
I, F, RUF and more, with line length 88. Runtime is Python 3.12.

    .venv/Scripts/python -m ruff check --output-format concise $(git ls-files '*.py' | grep -v '^tests/')

Write new code so it doesn't trip the common rules:

- **UP006 / UP045 / UP035:** use `dict[str, int]`, `list[...]` and `X | None`, not `typing.Dict` or `Optional`. Import `Callable`, `Iterable` and similar from `collections.abc`.
- **F401:** don't leave unused imports, especially `typing` names after a refactor.
- **I001:** keep imports sorted: stdlib, then third-party, then local, in alphabetical order.
- **BLE001 / S110:** catch specific exceptions. A broad `except Exception` needs `# noqa: BLE001 - <why>` and must report or log the error, never `pass`.
- **RUF100:** don't add `noqa` for rules that don't fire. The `# noqa: E402` comments after `sys.path.insert` are intentional: E402 is off by default, but keep them.

**Caution:** never combine `--fix` and RUF100 with a narrow `--select`. RUF100 then strips every `noqa` for the rules that aren't selected, including the reasons written in them. That happened once, on 2026-11-13, and was restored by hand.
