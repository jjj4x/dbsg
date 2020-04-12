from dataclasses import dataclass, field
from itertools import chain
from typing import Any, MutableMapping
from json import load

from pytest import fixture

from dbsg.lib import configuration

MAIN_FIXTURE = './tests/raw_introspection_fixture.json'


class Cursor:
    def __init__(self, data_fixture):
        self.statement = None
        self.binds = None
        self.rowfactory = None
        self.fixture = data_fixture
        self.rows = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return

    def execute(self, statement, binds):
        self.statement = statement
        self.binds = binds

    def fetchall(self):
        if self.binds:
            rows = self.fixture[self.binds['schema'].lower()]
        else:
            packages = chain(self.fixture.values())
            rows = chain(pkg.values() for pkg in packages)

        if self.rowfactory is not None:
            rows = [self.rowfactory(*row) for row in rows]

        self.rows = rows

        return rows


class Connection:
    def __init__(self, data_fixture, *args, **kwargs):
        self.fixture = data_fixture
        self.args = args
        self.kwargs = kwargs

    def cursor(self):
        return Cursor(self.fixture)


def session_pool_factory():
    @dataclass
    class SessionPool:
        busy: Any = field(default=None)
        dsn: Any = field(default=None)
        getmode: Any = field(default=None)
        homogeneous: Any = field(default=None)
        increment: Any = field(default=None)
        max: Any = field(default=None)
        max_lifetime_session: Any = field(default=None)
        min: Any = field(default=None)
        name: Any = field(default=None)
        opened: Any = field(default=None)
        stmtcachesize: Any = field(default=None)
        timeout: Any = field(default=None)
        tnsentry: Any = field(default=None)
        username: Any = field(default=None)
        wait_timeout: Any = field(default=None)

        fixture: MutableMapping = field(default=None)

        def acquire(self, *args, **kwargs):
            return Connection(self.fixture, *args, **kwargs)

        def drop(self, *args, **kwargs):
            raise NotImplemented

        def release(self, *args, **kwargs):
            raise NotImplemented

        def __init__(self, *args, **kwargs):
            pass

    with open(MAIN_FIXTURE, 'r', encoding='utf8') as fh:
        json = load(fh)

    SessionPool.fixture = json

    return SessionPool


@fixture(name='dbsg_config')
def dbsg_config_fixture(monkeypatch):
    import sys
    monkeypatch.setattr(
        sys,
        'argv',
        [],
    )
    print(configuration.Setup)
    c = configuration.Setup()
    c.path = 'config_sample.yml'
    return c.configuration()


@fixture(name='dbsg_config_with_mocked_session')
def dbsg_config_with_mocked_session_fixture(monkeypatch):
    import sys
    monkeypatch.setattr(
        sys,
        'argv',
        [],
    )
    monkeypatch.setattr(
        configuration,
        "SessionPool",
        session_pool_factory(),
    )
    c = configuration.Setup()
    c.path = 'config_sample.yml'
    return c.configuration()


@fixture(name='raw_introspection')
def raw_introspection_fixture():
    with open(MAIN_FIXTURE, 'r', encoding='utf8') as fh:
        json = load(fh)
    return json
