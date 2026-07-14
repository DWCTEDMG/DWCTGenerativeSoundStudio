# Stable branch and preview policy

This document defines the target repository policy. It does not claim that GitHub settings have
already been changed; the evidence snapshot below records the current external state honestly.

## Channels

- `main` is the protected, releasable branch. It accepts changes through reviewed pull requests only.
- `next` is the integration and preview channel. Completed work may soak there before promotion to
  `main`; it is never presented as a stable release.
- `codex/*`, `feature/*`, and equivalent short-lived branches are implementation branches. They are
  deleted after merge and are not release channels.

The current historical default branch, `codex/Unified`, must be migrated to `main` through an
explicit repository-admin operation after the modernization branch is reviewed. No automation or
local commit should silently retarget the default branch.

## Required `main` protection

Configure a GitHub ruleset or classic branch protection for `main` with:

1. pull requests required before merge;
2. at least one approving review and dismissal of stale approvals;
3. required resolution of review conversations;
4. required status checks, up-to-date branches, and no force pushes or deletion;
5. repository administrators subject to the same merge checks; and
6. secret-scanning push protection retained.

The required check set is:

- `Studio (windows-latest)`;
- `Studio (ubuntu-latest)`;
- the EDMG Director `validate` job; and
- CodeQL when the repository's CodeQL workflow applies.

Before making checks required, ensure each named workflow reports a terminal result on every pull
request to `main`; path-filtered workflows that never start can otherwise leave a required check
pending indefinitely.

## Promotion flow

1. Merge focused, reviewed work into `next` after its relevant tests pass.
2. Run the complete Studio, Director, Python, packaging, migration, and evidence gates required for
   that release candidate.
3. Open a promotion pull request from `next` to `main` containing the changelog, known blockers,
   compatibility evidence, and rollback instructions.
4. Tag and publish only from the protected `main` commit that passed the release gate.

Emergency fixes still use a pull request. If an administrator must bypass a rule to restore service,
record the reason and immediately follow with a normal reviewed reconciliation change.

## Evidence snapshot - 2026-07-14

- GitHub reports `codex/Unified` as the default branch.
- `main` exists, while `next` does not yet exist remotely.
- The default branch is not protected.
- Studio CI run 29313230364 passed Windows and Ubuntu.
- Secret scanning and push protection are enabled.

Changing the default branch, creating the remote preview channel, or enabling protection is an
external repository mutation. The Day 1 branch records these as blocked evidence until the owner
approves the push and repository-admin settings change.
