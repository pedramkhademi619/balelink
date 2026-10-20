import pytest

from balesdk import cli


def test_parser_accepts_every_command():
    p = cli.build_parser()
    assert p.parse_args(["login", "me", "--phone", "0912"]).command == "login"
    assert p.parse_args(["send", "me", "0912", "hi"]).text == "hi"
    assert p.parse_args(["serve", "--port", "9"]).port == 9
    for c in ("logout", "whoami", "listen"):
        assert p.parse_args([c, "me"]).session == "me"
    with pytest.raises(SystemExit):
        p.parse_args([])


def test_sessions_lists_saved_logins(tmp_path, capsys):
    assert cli.main(["--directory", str(tmp_path), "sessions"]) == 0
    assert "no saved logins" in capsys.readouterr().out
    (tmp_path / "work.bale").write_text("x")
    cli.main(["--directory", str(tmp_path), "sessions"])
    assert "work" in capsys.readouterr().out


def test_not_logged_in_commands(tmp_path, capsys):
    assert cli.main(["--directory", str(tmp_path), "whoami", "me"]) == 1
    assert cli.main(["--directory", str(tmp_path), "logout", "me"]) == 0


def test_serve_refuses_open_remote_bind(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("BALESDK_API_KEY", raising=False)
    assert cli.main(["--directory", str(tmp_path), "serve", "--host", "0.0.0.0"]) == 1
    assert "BALESDK_API_KEY" in capsys.readouterr().err
