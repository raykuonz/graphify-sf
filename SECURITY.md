# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Scope

graphify-sf is a **fully offline, read-only tool**. It parses local XML/source files and never connects to a Salesforce org or makes outbound API calls (unless you explicitly pass `--backend` to enable LLM extraction).

Security-relevant areas:

- **Path traversal** — the tool reads files under the path you provide; it does not follow symlinks outside that root
- **XML parsing** — uses the Python standard library `xml.etree.ElementTree` (not `lxml`); external entity expansion is not used
- **LLM backends** — when `--backend` is used, file content is sent to the configured LLM API; review which files are in scope before running on sensitive codebases
- **Graph output** — `graph.json` and `graph.html` contain your metadata labels and source-file paths; treat them with the same sensitivity as your source code

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Please report security issues using [GitHub's private vulnerability reporting](https://github.com/raykuo/graphify-sf/security/advisories/new).

Include:
- A description of the issue and its impact
- Steps to reproduce or a minimal proof-of-concept
- Affected versions

You can expect an acknowledgement within **72 hours** and a resolution or mitigation plan within **14 days** for confirmed issues. We will credit you in the release notes unless you prefer to remain anonymous.