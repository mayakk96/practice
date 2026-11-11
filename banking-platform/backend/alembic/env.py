from sqlalchemy import engine_from_config, pool

from alembic import context
from app import clearing, db, events, exceptions, models, reconciliation, settlement  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", db.DATABASE_URL.replace("%", "%%"))
target_metadata = db.Base.metadata


def run():
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    elif context.is_offline_mode():
        context.configure(url=db.DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
        )
        with connectable.connect() as connection:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()


run()
