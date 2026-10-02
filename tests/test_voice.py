"""The speech model loads from disk without contacting Hugging Face, and the runtimes send no telemetry
(no real model: faster_whisper and onnxruntime are stand-ins)."""
import sys
import types

import pytest


@pytest.fixture
def runtimes(monkeypatch):
    """Fake faster_whisper / onnxruntime; `calls` records each WhisperModel(...) and whether the local
    load is told to fail (no copy on disk)."""
    calls = []
    state = {"on_disk": True, "telemetry_off": 0}

    class WhisperModel:
        def __init__(self, model_id, **kw):
            calls.append(kw)
            if kw["local_files_only"] and not state["on_disk"]:
                raise FileNotFoundError("not in cache")
            if kw["device"] == "cuda":
                raise RuntimeError("no GPU here")

    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = WhisperModel
    ort = types.ModuleType("onnxruntime")
    ort.disable_telemetry_events = lambda: state.__setitem__("telemetry_off", state["telemetry_off"] + 1)
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    for k in ("HF_HUB_DISABLE_TELEMETRY", "HF_HUB_DISABLE_IMPLICIT_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    return calls, state


def test_a_downloaded_model_loads_offline_with_telemetry_off(runtimes):
    import os

    from maplehelper import voice
    calls, state = runtimes
    voice.Transcriber().load()
    assert [c["local_files_only"] for c in calls] == [True, True]          # cuda try, then cpu: never online
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1" and os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1"
    assert state["telemetry_off"] == 1


def test_only_a_missing_model_goes_online(runtimes):
    from maplehelper import voice
    calls, state = runtimes
    state["on_disk"] = False
    t = voice.Transcriber()
    t.load()
    assert [c["local_files_only"] for c in calls] == [True, True, False, False] and t.loaded()
    assert calls[-1]["device"] == "cpu" and str(calls[-1]["download_root"]).endswith("models")


def test_a_missing_onnxruntime_is_not_an_error(runtimes, monkeypatch):
    from maplehelper import voice
    monkeypatch.setitem(sys.modules, "onnxruntime", None)        # import raises ImportError
    voice.quiet_runtimes()
