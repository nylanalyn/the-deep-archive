"""Tests for configuration loading and env interpolation."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from deeparchive.config import ConfigError, load_config


def _write_config(tmp_path: Path, body: str) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent(body), encoding="utf-8")
    return config_path


class TestMinimalValidConfig:
    def test_loads_minimal_config(self, tmp_path):
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "irc.example.net"
            port = 6697
            nickname = "the-archivist"
            channel = "#archive"

            [db]
            path = "data/archive.sqlite3"
            """,
        )
        config = load_config(path)
        assert config.irc.server == "irc.example.net"
        assert config.irc.port == 6697
        assert config.irc.nickname == "the-archivist"
        assert config.irc.channel == "#archive"
        assert config.irc.username == "the-archivist"  # defaults from nickname
        assert config.irc.realname == "the-archivist"
        assert config.irc.ssl is True
        assert config.irc.tls_verify is True
        assert config.irc.sasl is None
        assert config.irc.day_boundary_timezone == "UTC"
        assert config.irc.actions_per_day == 5
        assert config.db.path == "data/archive.sqlite3"
        assert config.logging.level == "INFO"
        assert config.logging.file is None

    def test_config_dir_resolved(self, tmp_path):
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "irc.example.net"
            port = 6697
            nickname = "a"
            channel = "#a"

            [db]
            path = "x.sqlite3"
            """,
        )
        config = load_config(path)
        assert config.config_dir == path.parent.resolve()


class TestEnvInterpolation:
    def test_resolves_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SASL_PASSWORD", "hunter2")
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "irc.example.net"
            port = 6697
            nickname = "a"
            channel = "#a"

            [irc.sasl]
            username = "a"
            password = "${SASL_PASSWORD}"

            [db]
            path = "x.sqlite3"
            """,
        )
        config = load_config(path)
        assert config.irc.sasl is not None
        assert config.irc.sasl.password == "hunter2"

    def test_resolves_env_var_with_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPTIONAL", raising=False)
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "${OPTIONAL:-irc.default.net}"
            port = 6697
            nickname = "a"
            channel = "#a"

            [db]
            path = "x.sqlite3"
            """,
        )
        config = load_config(path)
        assert config.irc.server == "irc.default.net"

    def test_unresolved_env_var_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEFINITELY_MISSING", raising=False)
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "${DEFINITELY_MISSING}"
            port = 6697
            nickname = "a"
            channel = "#a"

            [db]
            path = "x.sqlite3"
            """,
        )
        with pytest.raises(ConfigError, match="DEFINITELY_MISSING"):
            load_config(path)


class TestValidation:
    @pytest.mark.parametrize("missing", ["server", "port", "nickname", "channel"])
    def test_missing_required_irc_key(self, tmp_path, missing):
        lines = [
            "[irc]",
            'server = "x"',
            "port = 6697",
            'nickname = "a"',
            'channel = "#a"',
            "",
            "[db]",
            'path = "x.sqlite3"',
        ]
        # Strip the line declaring the key we want absent.
        key_line = next(
            i for i, line in enumerate(lines) if line.strip().startswith(f"{missing} =")
        )
        del lines[key_line]
        path = tmp_path / "config.toml"
        path.write_text("\n".join(lines), encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(path)

    def test_port_out_of_range(self, tmp_path):
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "x"
            port = 99999
            nickname = "a"
            channel = "#a"

            [db]
            path = "x.sqlite3"
            """,
        )
        with pytest.raises(ConfigError, match="port"):
            load_config(path)

    def test_bad_timezone_raises(self, tmp_path):
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "x"
            port = 6697
            nickname = "a"
            channel = "#a"
            day_boundary_timezone = "Not/A/Zone"

            [db]
            path = "x.sqlite3"
            """,
        )
        with pytest.raises(ConfigError, match="day_boundary_timezone"):
            load_config(path)

    def test_valid_timezone_accepted(self, tmp_path):
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "x"
            port = 6697
            nickname = "a"
            channel = "#a"
            day_boundary_timezone = "America/New_York"

            [db]
            path = "x.sqlite3"
            """,
        )
        config = load_config(path)
        assert config.irc.day_boundary_timezone == "America/New_York"

    def test_custom_daily_action_limit_accepted(self, tmp_path):
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "x"
            port = 6697
            nickname = "a"
            channel = "#a"
            actions_per_day = 7

            [db]
            path = "x.sqlite3"
            """,
        )
        assert load_config(path).irc.actions_per_day == 7

    @pytest.mark.parametrize("value", ["0", "-1", '"five"', "true"])
    def test_invalid_daily_action_limit_rejected(self, tmp_path, value):
        path = _write_config(
            tmp_path,
            f"""
            [irc]
            server = "x"
            port = 6697
            nickname = "a"
            channel = "#a"
            actions_per_day = {value}

            [db]
            path = "x.sqlite3"
            """,
        )
        with pytest.raises(ConfigError, match="actions_per_day"):
            load_config(path)

    def test_missing_file_raises(self):
        with pytest.raises((ConfigError, FileNotFoundError)):
            load_config("/nonexistent/path.toml")

    def test_missing_db_section(self, tmp_path):
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "x"
            port = 6697
            nickname = "a"
            channel = "#a"
            """,
        )
        with pytest.raises(ConfigError, match="db"):
            load_config(path)

    def test_bad_log_level(self, tmp_path):
        path = _write_config(
            tmp_path,
            """
            [irc]
            server = "x"
            port = 6697
            nickname = "a"
            channel = "#a"

            [db]
            path = "x.sqlite3"

            [logging]
            level = "VERBOSE"
            """,
        )
        with pytest.raises(ConfigError, match="level"):
            load_config(path)
