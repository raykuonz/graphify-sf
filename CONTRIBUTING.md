# Contributing to graphify-sf

Thanks for taking the time to contribute.

## Ways to contribute

- **Bug reports** — open an issue with the bug report template
- **Feature requests** — open an issue with the feature request template
- **Pull requests** — fix bugs, add metadata extractors, improve docs

---

## Development setup

```bash
# Clone
git clone https://github.com/raykuo/graphify-sf
cd graphify-sf

# Install with dev dependencies (uses lock file)
uv sync --extra dev

# Run the test suite
uv run pytest

# Check linting and formatting
uv run ruff check .
uv run ruff format --check .
```

Python 3.10+ required.

---

## Adding a new metadata extractor

Most contributions will be adding support for a new Salesforce metadata type. The pattern is consistent across all existing extractors:

1. **Add ID helpers** in `graphify_sf/extract/_ids.py`:
   ```python
   def my_type_id(name: str) -> str:
       return make_sf_id("mytype", name)
   ```

2. **Add a file type** in `graphify_sf/detect.py`:
   - Add a value to the `SFFileType` enum
   - Add the compound extension to `_COMPOUND_EXT_MAP`

3. **Write the extractor** in `graphify_sf/extract/` — follow the pattern in `agentforce.py` or `flow.py`:
   - Parse XML with `xml.etree.ElementTree`
   - Return `{"nodes": [...], "edges": [...]}`
   - Tag edges `EXTRACTED` when the relationship is explicit in XML, `INFERRED` when heuristic

4. **Wire it up** in `graphify_sf/extract/__init__.py`:
   - Import the function
   - Add the compound suffix to `_DISPATCH`

5. **Write tests** in `tests/` using `tmp_path` and inline XML fixtures — see `test_extract_agentforce.py` for examples.

6. **Update the README** — add a row to the Supported Metadata Types table.

---

## Pull request checklist

- [ ] `uv run pytest` passes (all existing tests green)
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] New extractor has tests for: node creation, edge types, missing file, ID helpers
- [ ] README Supported Metadata Types table updated
- [ ] CHANGELOG.md updated under `[Unreleased]`

---

## Code style

- **Linter/formatter**: [ruff](https://docs.astral.sh/ruff/) is enforced in CI. Run `uv run ruff check .` and `uv run ruff format .` before opening a PR.
- Type hints on all public functions
- Docstrings on all public functions
- Extractors must never raise — catch `(ET.ParseError, FileNotFoundError, OSError)` and return `{"nodes": [], "edges": []}`

---

## Reporting security issues

See [SECURITY.md](SECURITY.md).
