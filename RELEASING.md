# Releasing

Setu Gateway's release pipeline (`.github/workflows/release.yml`) runs on any tag
matching `v*.*.*` (or manually via `workflow_dispatch`). It builds every publishable
artifact and attaches them to a GitHub Release. **Publishing to PyPI, npm, and GHCR is
disabled by default** - the pipeline builds and verifies everything but stops short of
pushing anywhere external until a maintainer deliberately arms it.

## Cutting a release

1. Bump the version in lockstep across all three manifests - the pipeline's
   `verify-version` job fails the whole run if these don't match the tag:
   - `pyproject.toml` (`setu-gateway`, the gateway app)
   - `packages/sdk-python/pyproject.toml` (`setu-gateway-sdk`)
   - `packages/sdk-typescript/package.json` (`@setu/sdk`)
2. Update `CHANGELOG.md`: move `[Unreleased]` entries under a new `## [X.Y.Z]` heading.
3. Commit, then tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. The pipeline builds the gateway package, both SDKs, both Docker images, and the
   OpenAPI schema, then creates a GitHub Release with all of them attached.

Note on pre-release suffixes: `packages/sdk-python` and the root package use Python's
PEP 440 versioning, which does not accept a bare `-alpha` suffix the way semver does -
`0.1.0a0` or `0.1.0.dev0` rather than `0.1.0-alpha`. `verify-version` does an exact
string comparison (tag with its leading `v` stripped) against each manifest, so pick a
version string that's simultaneously valid for hatchling and `packages/sdk-typescript`'s
semver, and use the identical string (fully qualified, no `v`) in all three manifests
and in the git tag.

## Arming real publishing

By default `ENABLE_RELEASE_PUBLISH` is unset, so `build-sdk-python`, `build-sdk-typescript`,
and `build-docker` build and upload artifacts but skip their publish steps. To enable:

1. Settings -> Secrets and variables -> Actions -> **Variables** -> add
   `ENABLE_RELEASE_PUBLISH` = `true`.
2. Settings -> Secrets and variables -> Actions -> **Secrets** -> add:
   - `PYPI_API_TOKEN` - a PyPI API token scoped to the `setu-gateway-sdk` project
     (create the project on PyPI first, or use a user-scoped token for the first publish).
   - `NPM_TOKEN` - an npm automation token with publish rights to the `@setu` org/scope.
   - GHCR needs no separate secret - it authenticates with the workflow's own
     `GITHUB_TOKEN`, scoped to this repository's package registry.

Once armed, every future tag push publishes for real. Turn `ENABLE_RELEASE_PUBLISH`
back off (or delete it) to return to build-only dry runs.

### Future improvement

PyPI's [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC, no stored
token) is the better long-term setup, but it requires the `setu-gateway-sdk` project to
already exist on PyPI (or a pending-publisher claim) before it can be linked to this
workflow - not practical for a project's first-ever release. Worth switching to after
the first manual/token-based publish.
