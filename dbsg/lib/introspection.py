from dataclasses import dataclass, field
from typing import MutableSequence, Optional
from threading import Lock, Thread
from logging import getLogger

from cx_Oracle import Connection, Cursor, SessionPool

from dbsg.lib.configuration import Configuration, Schema

LOG = getLogger(__name__)

INTROSPECTION_DB_ADD_NEW_SCHEMA_LOCK = Lock()

COMPLEX_TYPES = (
    'varray',
    'table',
    'record',
    'pl/sql table',
    'pl/sql record',
)

# noinspection SqlNoDataSourceInspection,SqlResolve
INTROSPECTION_WITH_PACKAGE_SQL = """
select
    ao.owner schema,
    ao.object_name package,
    1 is_package,
    ap.procedure_name routine,
    case when exists (
        select null from all_arguments
        where
            object_id = ap.object_id
            and subprogram_id = ap.subprogram_id
            and argument_name is null
            and in_out = 'OUT'
    ) then 'FUNCTION' else 'PROCEDURE'
    end routine_type,
    ap.object_id object_id,
    ap.overload overload,
    aa.subprogram_id subprogram_id,
    case when (
        aa.argument_name is null
        and aa.in_out = 'OUT'
        and aa.data_level = 0
    ) then '_DBSG_RESULT' else aa.argument_name
    end argument,
    aa.position position,
    aa.sequence sequence,
    aa.data_level data_level,
    aa.data_type data_type,
    aa.type_owner custom_type_schema,
    aa.type_name custom_type_package,
    aa.type_subname custom_type,
    aa.defaulted defaulted,
    aa.default_value default_value,
    aa.in_out in_out
from
    sys.all_objects ao,
    sys.all_procedures ap,
    sys.all_arguments aa
where
    ao.owner = ap.owner
    and ao.object_name = ap.object_name
    and aa.object_id = ap.object_id
    and aa.subprogram_id = ap.subprogram_id
    and ao.object_type = 'PACKAGE'
    and procedure_name is not null
    and ao.owner = :schema
    -- May be relevant, may be not
    -- and ao.status = 'VALID'
    -- and ao.temporary = 'N'
    -- and ao.generated = 'N'
    -- Filter:
""".strip()

# noinspection SqlNoDataSourceInspection,SqlResolve
INTROSPECTION_WITHOUT_PACKAGE_SQL = """
select
    ao.owner schema,
    :no_package_name package,
    0 is_package,
    ap.object_name routine,
    ao.object_type routine_type,
    ap.object_id object_id,
    ap.overload overload,
    aa.subprogram_id subprogram_id,
    case when aa.argument_name is null and aa.in_out = 'OUT'
        then '_DBSG_RESULT'
        else aa.argument_name
    end argument,
    aa.position position,
    aa.sequence sequence,
    aa.data_level data_level,
    aa.data_type data_type,
    aa.type_owner custom_type_schema,
    aa.type_name custom_type_package,
    aa.type_subname custom_type,
    aa.defaulted defaulted,
    aa.default_value default_value,
    aa.in_out in_out
from
    sys.all_objects ao,
    sys.all_procedures ap,
    sys.all_arguments aa
where
    ao.owner = ap.owner
    and ao.object_name = ap.object_name
    and aa.object_id = ap.object_id
    and aa.subprogram_id = ap.subprogram_id
    and ao.object_type in ('FUNCTION', 'PROCEDURE')
    and ao.owner = :schema
    -- May be relevant, may be not
    -- and ao.status = 'VALID'
    -- and ao.temporary = 'N'
    -- and ao.generated = 'N'
    -- Filter:
""".strip()

INTROSPECTION_ORDER_CLAUSE = (
    'order by package, object_id, subprogram_id, sequence, position'
)

# *****************************INTROSPECTION TYPES*****************************
@dataclass
class IntrospectionRow:
    schema: str
    package: str
    is_package: bool
    routine: str
    routine_type: str
    object_id: int
    overload: int
    subprogram_id: int
    argument: str
    position: int
    sequence: int
    data_level: int
    data_type: str
    custom_type_schema: Optional[str]
    custom_type_package: Optional[str]
    custom_type: Optional[str]
    defaulted: bool
    default_value: None  # Currently isn't supported in Oracle; always NULL
    in_out: str

    def __post_init__(self):
        self.is_package = True if self.is_package else False
        self.defaulted = True if self.defaulted == 'Y' else False
        self.overload = int(self.overload or 0)
        # Lowercase every string, so we won't think about it anymore
        # noinspection PyUnresolvedReferences
        for attribute_name in self.__dataclass_fields__:
            attribute_value = getattr(self, attribute_name, None)
            if isinstance(attribute_value, str):
                setattr(self, attribute_name, attribute_value.lower())


@dataclass
class IntrospectionSchema:
    name: str
    no_package_name: str
    rows: MutableSequence[IntrospectionRow] = field(default_factory=list)


@dataclass
class IntrospectionDatabase:
    name: str
    schemes: MutableSequence[IntrospectionSchema] = field(default_factory=list)


Introspection = MutableSequence[IntrospectionDatabase]
# *****************************INTROSPECTION TYPES*****************************


# **************************Introspection Entry Point**************************
class Inspect:
    def __init__(self, conf: Configuration):
        self.conf = conf
        self.result: Introspection = []

    @staticmethod
    def _introspect_one_schema(
        session_pool: SessionPool,
        schema: Schema,
        introspection_db: IntrospectionDatabase,
    ):
        sql = []
        binds = {'schema': schema.name}
        included_routines_from_packages = (
            f"    and ao.owner "
            f"|| '.' "
            f"|| ao.object_name "
            f"|| '.' "
            f"|| ap.procedure_name in ({schema.included_routines})"
        )
        included_routines_without_packages = (
            f'  and aa.object_name in ({schema.included_routines_no_pkg})'
        )
        excluded_packages = (
            f"  and ao.object_name not in ({schema.excluded_packages})"
        )
        excluded_routines_from_packages = (
            f"  and ao.owner "
            f"|| '.' "
            f"|| ao.object_name "
            f"|| '.' "
            f"|| ap.procedure_name not in ({schema.excluded_routines})"
        )
        excluded_routines_without_packages = (
            f"  and ao.owner "
            f"|| '.' "
            f"|| ap.object_name "
            f"not in ({schema.excluded_routines_no_pkg})"
        )

        # If there are ANY Includes, then fetch only specified concrete objects
        if schema.include_routines:
            if schema.included_packages and not schema.included_routines_no_pkg:
                sql.append(INTROSPECTION_WITH_PACKAGE_SQL)
                sql.append(included_routines_from_packages)

            if schema.included_packages and schema.included_routines_no_pkg:
                sql.append(INTROSPECTION_WITH_PACKAGE_SQL)
                sql.append(included_routines_from_packages)
                sql.append('union all')
                sql.append(INTROSPECTION_WITHOUT_PACKAGE_SQL)
                sql.append(included_routines_without_packages)

                binds['no_package_name'] = schema.no_package_name

            if not schema.included_packages and schema.included_routines_no_pkg:
                sql.append(INTROSPECTION_WITHOUT_PACKAGE_SQL)
                sql.append(included_routines_without_packages)

                binds['no_package_name'] = schema.no_package_name

        # Else, fetch everything excluding "exclude"
        else:
            sql.append(INTROSPECTION_WITH_PACKAGE_SQL)

            if schema.exclude_packages:
                sql.append(excluded_packages)

            if schema.exclude_routines:
                sql.append(excluded_routines_from_packages)

            sql.append('union all')
            sql.append(INTROSPECTION_WITHOUT_PACKAGE_SQL)

            if schema.excluded_routines_no_pkg:
                sql.append(excluded_routines_without_packages)

            binds['no_package_name'] = schema.no_package_name

        sql.append(INTROSPECTION_ORDER_CLAUSE)

        sql = '\n'.join(sql)
        LOG.info(repr(f'-- Use print() to format the msg\n-- {binds}\n{sql};'))

        # Fetch all the rows at once
        connection: Connection = session_pool.acquire()
        with connection.cursor() as cursor:
            cursor: Cursor = cursor
            cursor.execute(sql, binds)
            cursor.rowfactory = IntrospectionRow
            rows: MutableSequence[IntrospectionRow] = cursor.fetchall()

        introspection_schema = IntrospectionSchema(
            name=schema.name,
            no_package_name=schema.no_package_name,
            rows=rows,
        )

        # A guarantee that DB's schemas will be placed in series
        with INTROSPECTION_DB_ADD_NEW_SCHEMA_LOCK:
            introspection_db.schemes.append(introspection_schema)

    def introspection(self) -> Introspection:
        introspection = []
        # Fork and process each schema in a separate thread
        threads = []
        for db in self.conf.databases:
            introspection_db = IntrospectionDatabase(name=db.name)
            introspection.append(introspection_db)

            session_pool = db.connect()
            for schema in db.schemes:
                thread = Thread(
                    target=self._introspect_one_schema,
                    args=(session_pool, schema, introspection_db),
                    daemon=True,
                )
                threads.append(thread)
                thread.start()

        # Block and Join
        for thread in threads:
            thread.join()

        self.result = introspection

        return introspection
# **************************Introspection Entry Point**************************