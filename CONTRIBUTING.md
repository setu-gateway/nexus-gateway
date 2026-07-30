# Contributing to Setu Gateway

Thank you for helping build Setu Gateway, an open-source AI infrastructure platform. We welcome bug fixes, documentation, providers, plugins, tests, and thoughtful design feedback.

## Before you begin

- Read the relevant RFC in [`rfcs/`](rfcs).
- Search existing issues and pull requests.
- Open an issue first for a substantial feature or public API change.
- Never include credentials, customer data, or private prompts in issues, commits, or tests.

## Development workflow

1. Create a short-lived branch from `main`: `feature/short-description`, `fix/short-description`, or `docs/short-description`.
2. Make a focused change with tests and documentation where applicable.
3. Use [Conventional Commits](https://www.conventionalcommits.org/), for example `feat(router): add capability filter`.
4. Open a pull request using the repository template.

`main` must remain deployable. Major architectural decisions require an RFC; implementation-level choices should use an ADR once the ADR directory is introduced.

## Definition of done

- Formatting, linting, type checks, and tests pass.
- New behavior has appropriate unit and integration coverage.
- Public behavior has documentation and examples.
- Provider and plugin changes declare capabilities, permissions, and compatibility.
- Security-sensitive changes receive explicit review.

## Code review

Review focuses on correctness, safety, maintainability, tests, documentation, and compatibility. Be constructive, specific, and respectful. By contributing, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Security issues

Do not report vulnerabilities publicly. See [SECURITY.md](SECURITY.md).
