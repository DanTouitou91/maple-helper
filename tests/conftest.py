"""Shared test setup.

maplehelper.store creates folders under %APPDATA% at import time, so APPDATA is
pointed at a throwaway folder here, before any test imports the app. Tests never
touch a real player's settings, profiles or history.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="maplehelper-tests-")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import pytest  # noqa: E402

FIXTURE_KB = Path(__file__).parent / "fixtures" / "kb"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test reaches the internet. An app left alive by one test fires its 4-second update check during a
    later test; a real 21 MB download unpacking in a daemon thread while pytest tears widgets down crashed
    Python on Windows (heap corruption). Tests that model a server patch these again themselves."""
    import urllib.error
    import urllib.request

    def refuse(*a, **k):
        raise urllib.error.URLError("no network in tests")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    from maplehelper import updater
    monkeypatch.setattr(updater, "_get", lambda url, timeout=30: None)


@pytest.fixture
def kb_copy(tmp_path) -> Path:
    """A writable copy of the fixture knowledge base."""
    dst = tmp_path / "kb"
    shutil.copytree(FIXTURE_KB, dst)
    return dst


@pytest.fixture
def kb():
    from maplehelper.kb import KnowledgeBase
    return KnowledgeBase(FIXTURE_KB)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Settings/Profiles/History write into tmp_path instead of the shared test APPDATA."""
    from maplehelper import store
    monkeypatch.setattr(store.Settings, "path", tmp_path / "settings.json")
    monkeypatch.setattr(store.Profiles, "path", tmp_path / "profiles.json")
    monkeypatch.setattr(store, "HISTORY_DIR", tmp_path / "history")
    (tmp_path / "history").mkdir()
    return store
