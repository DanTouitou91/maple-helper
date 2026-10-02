"""AI runs end cleanly: a hung CLI times out, Stop kills it, a dead process never raises (real child processes)."""
import json
import subprocess
import sys
import threading
import time

import pytest

from maplehelper.providers import base, claude, codex

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="fake CLIs are POSIX scripts")


def fake_cli(tmp_path, body: str) -> str:
    """An executable standing in for the CLI: ignores its arguments, runs `body` (Python)."""
    exe = tmp_path / "fake-cli"
    exe.write_text(f"#!{sys.executable}\nimport sys, time, json\n{body}\n", encoding="utf-8")
    exe.chmod(0o755)
    return str(exe)


RESULT = json.dumps({"type": "result", "result": "Hi.\n@@META@@\n{}"})


def brain_for(kb_copy, monkeypatch, provider, exe):
    from maplehelper.brain import Brain
    from maplehelper.kb import KnowledgeBase
    b = Brain(KnowledgeBase(kb_copy), provider=provider)
    b.backend.exe = exe
    monkeypatch.setattr(b.backend, "prewarm", lambda: None)
    return b


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_a_hung_run_ends_with_a_timeout(kb_copy, tmp_path, monkeypatch, provider):
    monkeypatch.setattr(claude if provider == "claude" else codex, "RUN_TIMEOUT", 1)
    b = brain_for(kb_copy, monkeypatch, provider, fake_cli(tmp_path, "sys.stdin.read(); time.sleep(60)"))
    t = time.monotonic()
    ans = b.ask("hi", None, None, None)
    assert ans.error == "timeout" and time.monotonic() - t < 10


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_stop_kills_the_run(kb_copy, tmp_path, monkeypatch, provider):
    b = brain_for(kb_copy, monkeypatch, provider, fake_cli(tmp_path, "sys.stdin.read(); time.sleep(60)"))
    threading.Timer(0.5, b.cancel).start()
    t = time.monotonic()
    ans = b.ask("hi", None, None, None)
    assert ans.error == "cancelled" and time.monotonic() - t < 10


def test_stop_before_the_process_started(kb_copy, tmp_path, monkeypatch):
    b = brain_for(kb_copy, monkeypatch, "claude", fake_cli(tmp_path, f"sys.stdin.read(); print({RESULT!r})"))
    real_run = b.backend.run

    def run_after_stop(*a, **k):
        b.cancel()                                # pressed while the prompt was being built
        return real_run(*a, **k)
    monkeypatch.setattr(b.backend, "run", run_after_stop)
    assert b.ask("hi", None, None, None).error == "cancelled"


def test_a_chatty_stderr_never_stalls_claude(kb_copy, tmp_path, monkeypatch):
    # stderr was read only after stdout ended: a full pipe deadlocked the run
    body = f"sys.stdin.read(); sys.stderr.write('x' * 1_000_000); sys.stderr.flush(); print({RESULT!r})"
    monkeypatch.setattr(claude, "RUN_TIMEOUT", 10)
    b = brain_for(kb_copy, monkeypatch, "claude", fake_cli(tmp_path, body))
    ans = b.ask("hi", None, None, None)
    assert ans.error is None and ans.text == "Hi."


def test_stop_between_the_worker_start_and_ask_still_counts(kb_copy, tmp_path, monkeypatch):
    b = brain_for(kb_copy, monkeypatch, "claude", fake_cli(tmp_path, f"sys.stdin.read(); print({RESULT!r})"))
    b.begin()                                     # the chat, on the GUI thread, right before the worker starts
    b.cancel()                                    # Stop pressed before the worker reached ask()
    assert b.ask("hi", None, None, None).error == "cancelled"
    b.begin()
    assert b.ask("hi", None, None, None).text == "Hi."     # the next question starts fresh


def test_the_next_question_is_not_cancelled(kb_copy, tmp_path, monkeypatch):
    b = brain_for(kb_copy, monkeypatch, "claude", fake_cli(tmp_path, f"sys.stdin.read(); print({RESULT!r})"))
    b.cancel()                                    # Stop pressed after an earlier answer
    assert b.ask("hi", None, None, None).text == "Hi."


def test_dead_warm_process_and_failed_restart_return_an_error(kb_copy, tmp_path, monkeypatch):
    b = brain_for(kb_copy, monkeypatch, "claude", fake_cli(tmp_path, "pass"))   # exits without reading
    dead = b.backend._spawn()
    dead.wait()
    monkeypatch.setattr(b.backend, "_take_warm", lambda: dead)

    def cannot_start():
        raise OSError("gone")
    monkeypatch.setattr(b.backend, "_spawn", cannot_start)
    assert b.ask("hi", None, None, None).error.startswith("launch_failed")


def test_codex_exiting_early_is_an_error_not_a_crash(kb_copy, tmp_path, monkeypatch):
    b = brain_for(kb_copy, monkeypatch, "codex", fake_cli(tmp_path, "sys.stderr.write('bad flag')"))
    r = b.backend._exec([b.backend.exe], "x" * 1_000_000, str(tmp_path), None)   # BrokenPipe on the prompt
    assert r.error == "no_result"


class TestClaudeSummary:
    def summarize(self, kb_copy, tmp_path, monkeypatch, body, api_key=None):
        b = brain_for(kb_copy, monkeypatch, "claude", fake_cli(tmp_path, body))
        b.api_key = api_key
        return b.summarize("Player: hi\nHelper: hello")

    def test_a_good_summary(self, kb_copy, tmp_path, monkeypatch):
        assert self.summarize(kb_copy, tmp_path, monkeypatch, "print('Worked on the 2nd job.')") == \
            "Worked on the 2nd job."

    @pytest.mark.parametrize("body", [
        "print('Claude AI usage limit reached|1759420800'); sys.exit(1)",
        "print('Invalid API key · Please run /login')",               # exit 0, but an error all the same
        "print('Worked on the 2nd job.'); sys.exit(2)",
    ])
    def test_errors_are_never_kept_as_a_summary(self, kb_copy, tmp_path, monkeypatch, body):
        assert self.summarize(kb_copy, tmp_path, monkeypatch, body) is None

    def test_uses_the_same_login_as_questions(self, kb_copy, tmp_path, monkeypatch):
        body = "import os; print('key=' + os.environ.get('ANTHROPIC_API_KEY', 'none'))"
        monkeypatch.setenv("ANTHROPIC_API_KEY", "leftover")
        assert self.summarize(kb_copy, tmp_path, monkeypatch, body) == "key=none"
        assert self.summarize(kb_copy, tmp_path, monkeypatch, body, api_key="sk-ant-1") == "key=sk-ant-1"


def test_deadline_reports_whether_it_fired():
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    d = base.Deadline(p, 0.2)
    p.wait()
    assert d.expired
    q = subprocess.Popen([sys.executable, "-c", "pass"])
    d = base.Deadline(q, 30)
    q.wait()
    d.cancel()
    assert not d.expired


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_shutdown_waits_for_the_killed_processes(kb_copy, tmp_path, monkeypatch, provider):
    """Windows frees the KB folder only once a killed process has exited: the update renames it right after."""
    exe = fake_cli(tmp_path, "sys.stdin.read(); time.sleep(60)")
    b = brain_for(kb_copy, monkeypatch, provider, exe)
    running = subprocess.Popen([exe], stdin=subprocess.PIPE)
    b.backend._proc = running
    if provider == "claude":
        warm = b.backend._warm = subprocess.Popen([exe], stdin=subprocess.PIPE)
        b.backend._warm_config = b.backend._config()
    b.shutdown()
    assert running.returncode is not None                      # reaped, not just signalled
    if provider == "claude":
        assert warm.returncode is not None and b.backend._warm is None


def test_stop_warm_leaves_the_running_answer_alone(kb_copy, tmp_path, monkeypatch):
    exe = fake_cli(tmp_path, "sys.stdin.read(); time.sleep(60)")
    b = brain_for(kb_copy, monkeypatch, "claude", exe)
    running = b.backend._proc = subprocess.Popen([exe], stdin=subprocess.PIPE)
    warm = b.backend._warm = subprocess.Popen([exe], stdin=subprocess.PIPE)
    try:
        b.stop_warm()
        assert warm.returncode is not None and running.poll() is None
    finally:
        running.kill()
        running.wait()
