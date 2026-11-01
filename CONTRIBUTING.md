# Contributing to simulated_quantum_resource

Thank you for your interest in contributing! This document describes how to set up a development environment and the checks your change must pass before it can be merged.

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). To report a security vulnerability, please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Ways to contribute

- **Report a bug** – open an issue with steps to reproduce, the expected and actual behavior, your OS, and your Python version.
- **Propose a feature** – open an issue describing the use case before starting large changes, so the design can be discussed first.
- **Submit a pull request** – bug fixes, features, tests, and documentation improvements are all welcome.

## Development setup

Requirements:

- Python 3.11 or later (CI tests 3.11, 3.12 and 3.13)
- Git

```bash
git clone https://github.com/qrmi-community/simulated_quantum_resource.git
cd simulated_quantum_resource

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e ".[dev]"
```

> **Tip:** If you change dependencies, recreate the virtual environment (`python3 -m venv --clear .venv`) before reinstalling, so stale packages from a previous resolution do not hide problems.

## Running the checks locally

CI runs the following steps on every supported Python version (see [`.github/workflows`](.github/workflows)). Please run them locally before opening a pull request.

### 1. Lint

```bash
pylint qsa_sim
black --check qsa_sim
```

To apply formatting automatically:

```bash
black qsa_sim
```

### 2. Start the simulator

```bash
./run.sh config.yaml
```

Wait until the server is ready. The port is the one set in `config.yaml` (CI uses `8290`):

```bash
curl -fsS --retry 30 --retry-delay 2 --retry-connrefused http://0.0.0.0:8290/versions
```

### 3. Run the tests

```bash
pytest
```

### 4. Stop the simulator

```bash
./stop.sh
```

## Pull request guidelines

1. Fork the repository and create a topic branch from `main` (e.g. `fix/six-moves-import`, `feat/new-endpoint`).
2. Keep each pull request focused on a single change. Unrelated refactoring belongs in a separate PR.
3. Add or update tests under `test/` for any behavior change.
4. Update `README.md` or `docs/` if you change user-facing behavior, configuration, or environment variables.
5. Make sure all checks above pass on your machine.
6. Open the pull request against `main` with:
   - a clear title summarizing the change
   - a description of **what** changed and **why**, plus how you verified it
   - links to related issues (e.g. `Fixes #123`)

A maintainer will review your PR. Please respond to review comments by pushing additional commits to the same branch.

## Dependency changes

- Declare dependencies in `pyproject.toml` and keep `requirements.txt` / `requirements-dev.txt` consistent with it.
- **Always give a reasonable lower bound** (e.g. `boto3>=1.35`). Without one, pip's resolver can backtrack to very old releases when a new version of a transitive dependency conflicts, silently installing incompatible packages.
- In the PR description, mention why the dependency is needed and which versions you tested.

## Coding style

- Code is formatted with [black](https://black.readthedocs.io/) and linted with [pylint](https://pylint.readthedocs.io/) using the repository's `.pylintrc`.
- Write docstrings for public modules, classes, and functions.
- Never commit secrets. Keep `.env` out of version control; use `dot.env` as the template.

## License

This project is licensed under the [Apache License 2.0](LICENSE.txt). By contributing, you agree that your contributions will be licensed under the same license.
