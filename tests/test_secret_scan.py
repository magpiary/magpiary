"""Secret guards run only in disposable repositories with generated, synthetic credentials."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("secret_check", ROOT / "scripts/secret_check.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def git(repo, *args, data=None):
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
                          cwd=repo, input=data, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Synthetic Scanner Test")
    git(tmp_path, "config", "user.email", "scanner@example.invalid")
    (tmp_path / "scripts").mkdir()
    for name in ("secret_check.py", "secret-scan.sh"):
        shutil.copyfile(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    (tmp_path / "README.md").write_text("Synthetic repository\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "Synthetic initial commit")
    return tmp_path


def run(repo, *args, env=None):
    return subprocess.run([sys.executable, "scripts/secret_check.py", *args], cwd=repo,
                          capture_output=True, text=True, env=env)


@pytest.mark.parametrize("prefix,tail", [("AIza", "a" * 35), ("BSA", "b" * 30),
                                       ("nsec1", "q" * 58), ("sk-or-v1-", "a" * 64)])
def test_fallback_catches_provider_secrets_without_printing_them(repo, prefix, tail):
    synthetic = prefix + tail
    (repo / "leak.txt").write_text(synthetic + " # secret-check: fake\n")
    result = run(repo, "--worktree")
    assert result.returncode == 1
    assert "leak.txt" in result.stdout
    assert synthetic not in result.stdout + result.stderr


def test_fallback_checks_reflog_objects_that_are_not_on_a_branch(repo):
    clean = git(repo, "rev-parse", "HEAD")
    synthetic = "BSA" + "q" * 30
    blob = git(repo, "hash-object", "-w", "--stdin", data=synthetic)
    tree = git(repo, "mktree", data=f"100644 blob {blob}\told.txt\n")
    commit = git(repo, "commit-tree", tree, "-p", clean, "-m", "Synthetic historical fixture")
    # Move a fixture-only non-branch ref; the candidate then remains only in its reflog.
    git(repo, "update-ref", "--create-reflog", "refs/audit/fixture", commit)
    git(repo, "update-ref", "refs/audit/fixture", clean)
    result = run(repo, "--history")
    assert result.returncode == 1 and "old.txt" in result.stdout
    assert synthetic not in result.stdout + result.stderr


@pytest.mark.parametrize("name", ["boards.json", "cookies.json", "library.sqlite3-wal", "library.db-journal", "phone.shortcut", "stats-proxy", "agent-activity.jsonl"])
def test_private_file_names_are_blocked_even_when_empty(repo, name):
    (repo / name).touch()
    git(repo, "add", name)
    result = run(repo)
    assert result.returncode == 1 and name in result.stdout


def test_ignored_frontend_and_script_source_is_reported(repo):
    (repo / "src").mkdir()
    (repo / "src/hidden.js").write_text("// synthetic source\n")
    (repo / "scripts/hidden.sh").write_text("# synthetic script\n")
    (repo / ".gitignore").write_text("src/hidden.js\nscripts/hidden.sh\n")
    result = run(repo, "--worktree")
    assert result.returncode == 1
    assert "src/hidden.js" in result.stdout and "scripts/hidden.sh" in result.stdout


def test_sample_env_names_are_allowed_but_their_content_is_still_scanned(repo):
    (repo / ".env.example").write_text("API_KEY=replace-me\n")
    git(repo, "add", ".env.example")
    assert run(repo).returncode == 0
    synthetic = "BSA" + "q" * 30
    (repo / ".env.example").write_text("API_KEY=" + synthetic + "\n")
    assert run(repo, "--worktree").returncode == 1


def test_push_script_still_blocks_content_when_gitleaks_is_unavailable(repo, tmp_path):
    bindir = tmp_path.parent / (tmp_path.name + "-bin")
    bindir.mkdir()
    for name, target in (("python3", sys.executable), ("git", shutil.which("git")),
                         ("dirname", shutil.which("dirname"))):
        (bindir / name).symlink_to(target)
    env = {**os.environ, "PATH": str(bindir)}
    clean = subprocess.run(["/bin/bash", "scripts/secret-scan.sh"], cwd=repo, env=env, capture_output=True, text=True)
    assert clean.returncode == 0 and "secret-scan: clean" in clean.stdout
    synthetic = "BSA" + "q" * 30
    (repo / "leak.txt").write_text(synthetic)
    result = subprocess.run(["/bin/bash", "scripts/secret-scan.sh"], cwd=repo, env=env, capture_output=True, text=True)
    assert result.returncode == 1 and "push blocked" in result.stderr
    assert "leak.txt" in result.stdout
    assert "gitleaks unavailable" in result.stderr
    assert synthetic not in result.stdout + result.stderr


def test_quoted_session_cookie_values_are_scanned():
    value = "s" * 32
    assert list(checker.scan([("synthetic:1", '{"sessionid": "' + value + '"}')]))


def test_recommended_ignore_rules_protect_copies_without_hiding_source(repo):
    shutil.copyfile(ROOT / ".gitignore", repo / ".gitignore")
    for name in ("boards.json", "cookies.json", "library.sqlite3-wal", "library.sqlite3-shm", "library.db-journal"):
        result = subprocess.run(["git", "check-ignore", "-q", name], cwd=repo)
        assert result.returncode == 0
    for name in (".env.example", "src/magpiary/frames.py", "scripts/secret-scan.sh", "brand/logo.png"):
        result = subprocess.run(["git", "check-ignore", "-q", name], cwd=repo)
        assert result.returncode == 1
