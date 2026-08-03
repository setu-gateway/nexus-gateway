# Governance

This document defines how decisions get made in Setu Gateway, and the roles people
grow into as the project grows. It reflects where the project actually is today
(pre-1.0, single founder) rather than a governance structure the project hasn't
grown into yet - see [MAINTAINERS.md](MAINTAINERS.md) for who currently holds
which role.

## Roles

### Maintainer

Has merge access to `main` and release authority. Responsible for the overall
technical direction, reviewing and merging RFCs (see [`rfcs/`](rfcs)), cutting
releases per [RELEASING.md](RELEASING.md), and final say when consensus can't be
reached. New maintainers are proposed by an existing maintainer and confirmed by
lazy consensus among current maintainers (see "Decision-making" below).

### Core team

Trusted contributors with a sustained history of high-quality contributions across
multiple areas of the codebase (not just one plugin or subsystem). Core team members
can review and approve PRs outside their own area and are consulted on RFCs before
they're opened for broader comment. Promoted from Committer by maintainer vote.

### Committer

Has write access scoped to a specific area (e.g., a provider plugin, the dashboard,
one SDK) after a sustained record of accepted, well-reviewed PRs in that area.
Committers can merge PRs within their scope once another Committer, Core Team
member, or Maintainer has approved.

### Reviewer

Has repository triage permissions (labeling, assigning, requesting changes) but not
merge access. A natural first step for a regular contributor moving toward
Committer status.

### Contributor

Anyone who opens an issue, PR, or discussion. No special access required - see
[CONTRIBUTING.md](CONTRIBUTING.md) to get started.

## Decision-making

- **Day-to-day changes** (bug fixes, docs, most PRs): reviewed and merged by any
  Committer/Core Team member/Maintainer per [CONTRIBUTING.md](CONTRIBUTING.md)'s
  review process. No formal vote needed.
- **Substantial features or public API changes**: require an RFC in
  [`rfcs/`](rfcs) first, per [CONTRIBUTING.md](CONTRIBUTING.md). RFCs are decided by
  **lazy consensus** among Maintainers - if no Maintainer objects within a stated
  comment period, it's accepted. An explicit objection from any Maintainer blocks
  merge until resolved in discussion.
- **Governance changes** (this document, adding/removing Maintainers): require
  agreement from a majority of current Maintainers.
- **Releases**: cut by any Maintainer following [RELEASING.md](RELEASING.md)'s
  checklist. No separate vote required for a routine release; a major version bump
  should have been previewed in the [ROADMAP](ROADMAP.md) first.

## Code of Conduct

All roles and all contributors are bound by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
Maintainers are responsible for enforcement.

## Where this document is thin, on purpose

This project is pre-1.0 with a single maintainer today (see MAINTAINERS.md) -
several of the mechanisms above (a maintainer vote, lazy-consensus RFC review by
"Maintainers" plural) don't have enough people to exercise yet. They're written now,
before they're needed, so that the first new maintainer is added under a process
that already exists rather than one invented in the moment. Expect this document to
be revised as the project's actual contributor base grows past what it describes.
