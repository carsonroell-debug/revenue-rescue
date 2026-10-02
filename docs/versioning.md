# Versioning and release policy

Revenue Rescue uses semantic versioning:

```text
MAJOR.MINOR.PATCH
```

- **MAJOR**: incompatible public API/tool-contract change.
- **MINOR**: backward-compatible capability/tool addition or substantial detector expansion.
- **PATCH**: backward-compatible bug fix, false-positive reduction, operational fix, or documentation correction.

## Release source of truth

The runtime version lives in:

```text
revenuerescue/version.py
```

Health, readiness, and OpenAPI surfaces should report that same version.

## Before creating a tag

1. update `revenuerescue/version.py`;
2. update `CHANGELOG.md`;
3. run `python scripts/release_check.py`;
4. confirm CI is green;
5. confirm the container workflow is green;
6. confirm benchmark gates for a public release;
7. create an annotated `vX.Y.Z` tag from the exact release commit.

Do not publish a release tag from a commit that has not passed the required quality/security gates.
