"""Generation and persistence tests for the single active File."""

from __future__ import annotations

from deeparchive.content import load_content
from deeparchive.files import (
    MAX_SUCCESS_THRESHOLD,
    MIN_SUCCESS_THRESHOLD,
    FileGenerator,
    FileRepository,
    FileService,
)
from deeparchive.rng import Rng


def test_generation_is_reproducible() -> None:
    content = load_content()
    first = FileGenerator(content, Rng(123)).generate()
    second = FileGenerator(content, Rng(123)).generate()
    assert first == second


def test_generated_file_uses_valid_content() -> None:
    content = load_content()
    generated = FileGenerator(content, Rng(7)).generate()
    theme = content.themes[generated.theme_key]
    assert generated.location in theme.locations
    assert generated.theme_tags == theme.tags
    assert generated.opening_text in content.fragments.file_openings.get(
        theme.key, content.fragments.file_openings["default"]
    )
    assert MIN_SUCCESS_THRESHOLD <= generated.success_threshold <= MAX_SUCCESS_THRESHOLD
    assert generated.success_threshold > 0


def test_title_contains_required_noun() -> None:
    content = load_content()
    generated = FileGenerator(content, Rng(19)).generate()
    nouns = content.themes[generated.theme_key].title_parts["noun"]
    assert any(noun in generated.title for noun in nouns)


def test_service_creates_and_persists_one_file(migrated_conn) -> None:
    content = load_content()
    service = FileService(migrated_conn, content, Rng(55))
    first = service.ensure_active()
    second = service.ensure_active()
    assert first == second
    count = migrated_conn.execute("SELECT COUNT(*) FROM active_file").fetchone()[0]
    assert count == 1


def test_existing_file_survives_new_service_and_rng(migrated_conn) -> None:
    content = load_content()
    first = FileService(migrated_conn, content, Rng(1)).ensure_active()
    second = FileService(migrated_conn, content, Rng(999)).ensure_active()
    assert second == first


def test_hidden_threshold_is_persisted_but_not_described(migrated_conn) -> None:
    service = FileService(migrated_conn, load_content(), Rng(8))
    active = service.ensure_active()
    lines = service.describe_active()
    assert FileRepository(migrated_conn).get_active() == active
    assert "threshold" not in " ".join(lines).lower()
