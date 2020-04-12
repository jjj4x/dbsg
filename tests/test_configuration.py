from os import environ
from pytest import main

from dbsg.lib import configuration


def test_version():
    year, month, day, *_ = configuration.VERSION.split('.')
    assert (int(year), int(month), int(day)) > (2019, 1, 1)


def test_cli():
    cli = configuration.CommandLineInterface
    args = cli.parse_args([
        '--config', '/some/file.yml',
        '--plugins', 'json', 'python',
        '--abbreviation-files', 'one.txt', 'two.txt',
        '--',
        './path/to/the/stubs',
    ])
    assert args.config == '/some/file.yml'
    assert 'python' in args.plugins
    assert 'two.txt' in args.abbreviation_files
    assert args.path == './path/to/the/stubs'


def test_abbreviations(dbsg_config: configuration.Configuration):
    assert dbsg_config.abbreviations.match('api')
    assert dbsg_config.abbreviations.match('some_api_pkg')


def test_outcomes(dbsg_config: configuration.Configuration):
    assert dbsg_config.outcomes['helpdesk'] == 'HelpDesk'
    assert dbsg_config.outcomes['drweb'] == 'DrWEB'


def test_introspection_appendix(dbsg_config: configuration.Configuration):
    ia = dbsg_config.databases[0].schemes[0].introspection_appendix
    assert ia
    assert (777, 44, 0) in ia  # (object_id, subprogram_id, position)
    assert ia[777, 44, 0].new['custom_type_schema'] == 'BILLING'
    assert ia[777, 44, 0].new['custom_type'] == 'BILLS%ROWTYPE'


def test_fqdn(dbsg_config: configuration.Configuration):
    routine = dbsg_config.databases[0].schemes[0].exclude_routines[0]
    assert routine.schema == 'BILLING'
    assert routine.package == ''
    assert routine.routine == 'ESPESIALLY_NASTY_ROUTINE'
    assert str(routine) == 'BILLING.ESPESIALLY_NASTY_ROUTINE'
    assert repr(routine) == "'BILLING.ESPESIALLY_NASTY_ROUTINE'"


def test_schema(dbsg_config: configuration.Configuration):
    schema = dbsg_config.databases[0].schemes[0]
    assert schema.no_package_name == 'BILLING_NO_PKG'


# noinspection PyProtectedMember
def test_pool(dbsg_config: configuration.Configuration):
    pool = dbsg_config.databases[0].pool
    assert pool.user == 'user'
    assert pool.homogeneous
    assert pool.encoding == 'UTF-8'
    assert pool._dsn.host == '127.0.0.1'
    assert pool._dsn.port == 1521


# noinspection SqlNoDataSourceInspection,SqlResolve
def test_database(dbsg_config_with_mocked_session: configuration.Configuration):
    db = dbsg_config_with_mocked_session.databases[0]
    assert db.name == 'DB_NAME'
    assert len(db.schemes) == 3

    pool = db.connect()
    assert getattr(pool, 'fixture', {})

    cursor = pool.acquire().cursor()
    assert getattr(cursor, 'fixture', {})

    with cursor:
        cursor.execute('select * from t', {'a': 1})

    assert cursor.statement == 'select * from t'
    assert cursor.binds == {'a': 1}


def test_configuration(dbsg_config: configuration.Configuration):
    assert dbsg_config.plugins[0] == 'json'
    assert dbsg_config.path.name == 'stubs'
    assert dbsg_config.nls_lang is None
    assert environ['ORACLE_HOME'] == '/opt/oracle/instantclient_18_3'


if __name__ == '__main__':
    main(['-s', '-c', 'setup_tox.ini'])
