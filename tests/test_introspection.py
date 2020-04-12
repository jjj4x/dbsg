from pytest import main

from dbsg.lib import configuration, introspection


def test_probably_supported_types():
    assert not (
        {
            'ref cursor',
            'object',
            'varray',
            'table',
            'record',
            'pl/sql table',
            'pl/sql record',
        }
        ^ set(introspection.COMPLEX_TYPES)
    )


def test_introspection_row():
    row = introspection.IntrospectionRow(
        schema='BILLING',
        package='BILLING_PAC',
        is_package=1,
        routine='CALC_BC',
        routine_type='FUNCTION',
        object_id=1,
        overload=None,
        subprogram_id=1,
        argument='_DBSG_RESULT',
        position=1,
        sequence=1,
        data_level=0,
        data_type='NUMBER',
        custom_type_schema=None,
        custom_type_package=None,
        custom_type=None,
        defaulted='Y',
        default_value=None,
        in_out='OUT',
    )
    assert row.schema == 'billing'
    assert isinstance(row.is_package, bool)
    assert row.overload == 0
    assert row.argument == '_dbsg_result'
    assert isinstance(row.defaulted, bool)
    assert row.defaulted


def test_introspection(
        dbsg_config_with_mocked_session: configuration.Configuration
):
    i = introspection.Inspect(dbsg_config_with_mocked_session).introspection()
    db = i[0]
    assert db.name == 'DB_NAME'

    schema = db.schemes[0]
    assert schema.name == 'BILLING'

    row = schema.rows[0]
    assert row.schema == 'bills'
    assert row.routine == 'payroll'
    assert row.argument == 'in_customer'
    assert row.data_type == 'varchar2'


if __name__ == '__main__':
    main(['-s', '-c', 'setup_tox.ini'])
