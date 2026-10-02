"""The problem report carries the log and diagnostics, never private data."""
import json
import logging
import zipfile

from maplehelper import report


def test_report_has_log_and_info_but_no_private_settings(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "maplehelper.log").write_text("2026-10-01 INFO started\n", encoding="utf-8")
    monkeypatch.setattr(report, "LOG_DIR", logs)
    info = report.system_info("0.4.0", "2026.10.01.0100", "ok")
    path = report.build_report(tmp_path / "out", info, {"language": "he", "window": {"x": 1}, "bubble_pos": {}})
    with zipfile.ZipFile(path) as z:
        assert set(z.namelist()) == {"info.json", "settings.json", "logs/maplehelper.log"}
        assert json.loads(z.read("info.json"))["app_version"] == "0.4.0"
        assert json.loads(z.read("settings.json")) == {"language": "he"}


def test_logging_writes_to_the_log_file(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "LOG_DIR", tmp_path)
    monkeypatch.setattr(report, "LOG_FILE", tmp_path / "maplehelper.log")
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        for h in [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]:
            root.removeHandler(h)
        report.setup_logging()
        logging.getLogger("maplehelper.test").info("hello log")
        for h in root.handlers:
            h.flush()
        assert "hello log" in (tmp_path / "maplehelper.log").read_text(encoding="utf-8")
    finally:
        for h in root.handlers[:]:
            if h not in before:
                root.removeHandler(h)
                h.close()


def test_home_folder_and_wishlist_stay_out_of_the_report(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(report, "HOME", r"C:\Users\dan")
    (logs / "maplehelper.log").write_text("ERROR no file C:\\Users\\dan\\x.jpg (C:/Users/dan/y)\n", encoding="utf-8")
    monkeypatch.setattr(report, "LOG_DIR", logs)
    path = report.build_report(tmp_path / "out", {}, {"language": "he", "wish_prices": {"a": 1}, "wishlist": {},
                                                      "wish_alerts": [], "session_summaries": True})
    with zipfile.ZipFile(path) as z:
        assert z.read("logs/maplehelper.log").decode() == "ERROR no file ~\\x.jpg (~/y)\n"
        assert json.loads(z.read("settings.json")) == {"language": "he", "session_summaries": True}


def test_the_log_itself_is_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "LOG_DIR", tmp_path)
    monkeypatch.setattr(report, "LOG_FILE", tmp_path / "maplehelper.log")
    monkeypatch.setattr(report, "HOME", "/home/dan")
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        for h in [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]:
            root.removeHandler(h)
        report.setup_logging()
        try:
            open("/home/dan/secret.txt")
        except OSError:
            logging.getLogger("maplehelper.test").warning("stderr said: /home/dan/.codex/log", exc_info=True)
        for h in root.handlers:
            h.flush()
        text = (tmp_path / "maplehelper.log").read_text(encoding="utf-8")
        assert "/home/dan" not in text and "~/.codex/log" in text and "~/secret.txt" in text
    finally:
        for h in root.handlers[:]:
            if h not in before:
                root.removeHandler(h)
                h.close()
