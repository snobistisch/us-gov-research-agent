# Contributing

Contributions are welcome.

1. Create a focused branch.
2. Copy `.env.example` to `.env` and use only your own keys.
3. Install development dependencies with `python -m pip install -e '.[dev]'`.
4. Run `pre-commit install` once, then `pre-commit run --all-files`.
5. Run `ruff check .` and `pytest` before opening a pull request.

Never add live API responses that contain request headers, query-string keys, personal SEC contact data, or other credentials. Build sanitized minimal fixtures by hand. Report security issues privately as described in [SECURITY.md](SECURITY.md).
