from pytest import main

from dbsg.lib import configuration, introspection, intermediate_representation


def test_ir(dbsg_config_with_mocked_session: configuration.Configuration):
    ir = intermediate_representation.Abstract(
        introspection.Inspect(dbsg_config_with_mocked_session).introspection()
    ).intermediate_representation()
    assert ir


def test_database(dbsg_config_with_mocked_session: configuration.Configuration):
    ir = intermediate_representation.Abstract(
        introspection.Inspect(dbsg_config_with_mocked_session).introspection()
    ).intermediate_representation()

    db = ir[0]
    assert db.name == 'db_name'

    schema = db.schemes[0]
    assert schema.name == 'bills'

    package = schema.packages[0]
    assert package.name == 'bill_utils_pkg'

    routine = package.routines[0]
    assert routine.name == 'payroll'
    assert routine.type == 'procedure'
    assert routine.object_id == 180000
    assert str(routine.fqdn) == 'BILLS.BILL_UTILS_PKG.PAYROLL'
    assert routine.has_ins

    arg = routine.last_child
    assert arg.name == 'out_payroll_id'
    assert arg.in_out == 'out'
    assert arg.data_type == 'number'


if __name__ == '__main__':
    main(['-s', '-c', 'setup_tox.ini'])
