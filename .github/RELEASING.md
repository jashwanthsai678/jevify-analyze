# Releasing jevvify

Releases are cut by pushing a `v*` tag. [`release.yml`](workflows/release.yml) then runs the tests, builds the sdist
and wheel, generates a CycloneDX SBOM, creates build provenance attestations, publishes to PyPI and creates a GitHub
Release with the files attached.

## One-time setup

- On pypi.org, add a trusted publisher for project `jevvify`: owner `jashwanthsai678`, repository `jevify-analyze`,
  workflow `release.yml`, environment `pypi`. (Before the first release, add it as a "pending publisher".)
- In the GitHub repository settings, create an environment named `pypi`. Optionally require a reviewer for it.

## Checklist

1. [ ] Bump the version in **both** `pyproject.toml` (`version = "X.Y.Z"`) and `src/jevvify/__init__.py`
       (`__version__ = "X.Y.Z"`).
2. [ ] In `CHANGELOG.md`, change the `## X.Y.Z (unreleased)` heading to `## X.Y.Z (YYYY-MM-DD)` and check the
       entries cover what changed.
3. [ ] Run the checks locally:
       ```bash
       uv run --python 3.13 --with pytest python -m pytest -q
       uv run --python 3.13 --with ruff ruff check src tests
       uv build
       ```
4. [ ] Commit (`Release X.Y.Z`), push to `main`, and wait for CI to pass.
5. [ ] Tag and push:
       ```bash
       git tag -a vX.Y.Z -m "jevvify X.Y.Z"
       git push origin vX.Y.Z
       ```
6. [ ] Watch the Release workflow. The tag must match the package version or the build job fails.
7. [ ] Verify PyPI: https://pypi.org/project/jevvify/ shows `X.Y.Z` with both the sdist and the wheel.
8. [ ] Verify attestations for a downloaded file:
       ```bash
       gh attestation verify jevvify-X.Y.Z-py3-none-any.whl --repo jashwanthsai678/jevify-analyze
       ```
9. [ ] Verify the install from PyPI in a clean environment:
       ```bash
       uv tool install jevvify==X.Y.Z
       jevvify --version
       jevvify analyze examples/ticket_router
       ```
10. [ ] Check the GitHub Release has the dist files and the `.cdx.json` SBOM attached; edit the notes if needed.
11. [ ] Announce: link the release notes (GitHub Discussions, social, wherever the project is discussed).

## If something goes wrong

PyPI does not allow re-uploading a version. Fix the problem, bump to the next patch version and release again. Delete
a broken GitHub Release or tag only if nothing was published to PyPI from it.
