"""Runtime loading and reload behavior for TOML content."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from deeparchive.content import CONTENT_DOMAINS, ContentError, ContentLoader, load_content

SHIPPED = Path(__file__).resolve().parents[1] / "deeparchive" / "content"


def _copy_content(destination: Path) -> None:
    for domain in CONTENT_DOMAINS:
        shutil.copyfile(SHIPPED / f"{domain}.toml", destination / f"{domain}.toml")


def test_loads_packaged_defaults() -> None:
    pack = load_content()
    assert pack.themes
    assert pack.scars
    assert pack.relics
    assert pack.fragments.file_openings["default"]


def test_loads_directory_override(tmp_path: Path) -> None:
    _copy_content(tmp_path)
    pack = load_content(tmp_path)
    assert set(pack.themes) == {"darkness", "flood", "geometry"}


def test_missing_directory_is_contextual(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="content directory not found"):
        load_content(tmp_path / "absent")


def test_missing_domain_names_file(tmp_path: Path) -> None:
    _copy_content(tmp_path)
    (tmp_path / "relics.toml").unlink()
    with pytest.raises(ContentError, match="missing required content file: relics.toml"):
        load_content(tmp_path)


def test_invalid_toml_names_file(tmp_path: Path) -> None:
    _copy_content(tmp_path)
    (tmp_path / "scars.toml").write_text("[scars\n", encoding="utf-8")
    with pytest.raises(ContentError, match="invalid TOML in scars.toml"):
        load_content(tmp_path)


def test_reload_replaces_pack_after_valid_edit(tmp_path: Path) -> None:
    _copy_content(tmp_path)
    loader = ContentLoader(tmp_path)
    original = loader.current
    themes = tmp_path / "themes.toml"
    themes.write_text(
        themes.read_text(encoding="utf-8").replace('name = "Darkness"', 'name = "Deep Darkness"'),
        encoding="utf-8",
    )

    replacement = loader.reload()

    assert replacement is loader.current
    assert replacement is not original
    assert replacement.themes["darkness"].name == "Deep Darkness"


def test_failed_reload_keeps_last_valid_pack(tmp_path: Path) -> None:
    _copy_content(tmp_path)
    loader = ContentLoader(tmp_path)
    original = loader.current
    (tmp_path / "fragments.toml").write_text("not = [valid", encoding="utf-8")

    with pytest.raises(ContentError, match="invalid TOML in fragments.toml"):
        loader.reload()

    assert loader.current is original
