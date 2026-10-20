# Publishing to GitHub and PyPI

For the maintainer. After this, anyone can `pip install balesdk`.

## 1. Put it on GitHub

```bash
cd balesdk
git add -A
git status            # check: no *.bale file, no gateway.json, no .env
git commit -m "Initial release"
git branch -M main
git remote add origin git@github.com:<you>/balesdk.git     # create the empty repo first
git push -u origin main
```

Then in `pyproject.toml` replace `pedramkhademi619` in `[project.urls]` with
your GitHub user name if it differs, and put your real name in `authors`.

## 2. Check the name is free

<https://pypi.org/project/balesdk/> must show "404". If it is taken, change
`name` in `pyproject.toml` (the import name `balesdk` can stay the same).

## 3. Build and look at the package

```bash
pip install build twine
python -m build                 # creates dist/balesdk-0.1.0.tar.gz and a .whl
twine check dist/*
```

## 4. Try it on TestPyPI first (recommended)

1. Make an account at <https://test.pypi.org> and create an API token.
2. `twine upload --repository testpypi dist/*`
3. In a clean virtualenv:
   `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ balesdk`
   then `balesdk --version`.

## 5. Publish to PyPI

Make an account at <https://pypi.org>, turn on two-factor authentication, and
either:

**A. By hand**

```bash
twine upload dist/*             # username: __token__, password: your pypi- API token
```

**B. Automatically from GitHub (no token stored)** - "trusted publishing":

1. On PyPI: *Your projects -> Publishing -> Add a pending publisher* with owner
   = your GitHub user, repository = `balesdk`, workflow = `release.yml`,
   environment = `pypi`.
2. On GitHub: *Settings -> Environments -> New environment* named `pypi`.
3. Release by tagging:

```bash
# bump the version in pyproject.toml and balesdk/__init__.py, update CHANGELOG.md
git commit -am "Release 0.1.0" && git tag v0.1.0 && git push --tags
```

`.github/workflows/release.yml` tests, builds, and uploads to PyPI, then creates
the GitHub release.

## Rules to remember

- A version number can never be re-uploaded or replaced on PyPI. Fix mistakes by
  releasing the next version (you can "yank" a bad one).
- Keep `__version__` in `balesdk/__init__.py` and `version` in `pyproject.toml`
  equal.
- `aiobale-py` is a dependency, so `pip install balesdk` pulls it in; credit
  stays in `NOTICE`.
- Never publish a `.bale` file. `.gitignore` excludes them; check `git status`
  before every commit.
