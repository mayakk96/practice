"""Schema drift is caught before an application is packaged against its migrations."""

from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command


def assert_alembic_metadata_matches(factory):
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    with factory.kw["bind"].connect() as connection:
        config.attributes["connection"] = connection
        command.check(config)


def test_sqlite_migrations_match_application_metadata(factory):
    assert_alembic_metadata_matches(factory)


@pytest.mark.postgres
def test_postgresql_migrations_match_application_metadata(postgres_factory):
    assert_alembic_metadata_matches(postgres_factory)
