from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

config = context.config


def run(connection):
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get('connection')
if connection is not None:
    run(connection)
else:
    engine = create_engine(config.get_main_option('sqlalchemy.url'), poolclass=NullPool)
    with engine.begin() as connection:
        run(connection)
