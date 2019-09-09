from dataclasses import dataclass, field, asdict
from keyword import iskeyword
from pathlib import Path
from typing import MutableSequence, MutableMapping, Optional, Union
from threading import Thread, Lock
from os import environ
from logging import getLogger
from json import dumps
from yaml import dump
from re import compile, sub

from cx_Oracle import Connection, Cursor, SessionPool, makedsn

from dbsg.config import Config

# NOTE: About Forward Declarations.
#  One way:
#   https://docs.python.org/3/whatsnew/3.7.html#pep-563-postponed-evaluation-of-annotations
#  Another way:
#   https://stackoverflow.com/a/36286947

LOG = getLogger('dbsg.generator')
INTROSPECTION_DB_ADD_NEW_SCHEMA_LOCK = Lock()
CX_COMPLEX_TYPES = (
    'varray',
    'table',
    'record',
    'pl/sql table',
    'pl/sql record',
)
CX_SIMPLE_TYPES = {
    'number': 'cx_Oracle.NUMBER',
    'varchar2': 'cx_Oracle.STRING',
    'nvarchar2': 'cx_Oracle.NCHAR',
    'char': 'cx_Oracle.FIXED_CHAR',
    'nchar': 'cx_Oracle.FIXED_NCHAR',
    'clob': 'cx_Oracle.CLOB',
    'blob': 'cx_Oracle.BLOB',
    'date': 'cx_Oracle.DATETIME',
    'ref cursor': 'cx_Oracle.CURSOR',
    'pl/sql boolean': 'cx_Oracle.BOOLEAN',
    'binary_integer': 'cx_Oracle.LONG_BINARY',
}
PY_SIMPLE_TYPES = {
    'number': 'float',
    'varchar2': 'str',
    'nvarchar2': 'str',
    'char': 'str',
    'nchar': 'str',
    'clob': 'typing.Union[str, bytes]',
    'blob': 'typing.Union[str, bytes]',
    'date': 'datetime.datetime',
    'ref cursor': 'typing.ImmutableSequence',
    'pl/sql boolean': 'bool',
    'binary_integer': 'int',
}
PY_INDENT = '    '
LF = '\n'
# TODO: a proper solution for abbreviations
ABBR_DICT = compile(r'(api|http|sql|html)')

# TODO: define output types for cursors and multiple outputs

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


# *****************************INTROSPECTION TYPES*****************************
@dataclass
class FQDN:
    schema: str
    package: str  # maybe blank
    routine: str

    def __init__(self, *args):
        self.schema, self.package, self.routine = (a.upper() for a in args)

    def __str__(self):
        return f'{self.schema}.{self.package}.{self.routine}'.replace('..', '.')

    def __repr__(self):
        return repr(str(self))


@dataclass
class SchemaSetup:
    name: str
    no_package_name: str
    exclude_packages: MutableSequence[str]
    # ['schema', 'package', 'routine'] before __post_init__, FQDN after
    exclude_routines: MutableSequence[Union[MutableSequence, FQDN]]
    include_routines: MutableSequence[Union[MutableSequence, FQDN]]

    def __post_init__(self):
        self.name = self.name.upper()
        self.no_package_name = self.no_package_name.upper()

        exclude_packages = []
        exclude_routines = []
        include_routines = []
        included_packages = set()
        excluded_packages = set()
        included_routines = []
        excluded_routines = []
        included_routines_no_pkg = []
        excluded_routines_no_pkg = []

        # If there's include_routines, ONLY this routines will be introspected
        for routine in self.include_routines:
            fqdn = FQDN(*routine)
            include_routines.append(fqdn)
            if fqdn.package:
                included_routines.append(repr(fqdn.routine))
                included_packages.add(repr(fqdn.package))
            else:
                included_routines_no_pkg.append(repr(fqdn.routine))

        for package in self.exclude_packages:
            package = package.upper()
            exclude_packages.append(package)
            # It doesn't make sense to exclude anything, if we've included
            # ONLY concrete routines
            if not include_routines:
                excluded_packages.add(repr(package))

        for routine in self.exclude_routines:
            fqdn = FQDN(*routine)
            exclude_routines.append(fqdn)
            # It doesn't make sense to exclude anything, if we've included
            # ONLY concrete routines
            if include_routines:
                continue
            if fqdn.package:
                excluded_routines.append(repr(fqdn))
            else:
                excluded_routines_no_pkg.append(repr(fqdn))

        self.exclude_packages = exclude_packages
        self.exclude_routines = exclude_routines
        self.include_routines = include_routines

        self.included_packages = ', '.join(included_packages)
        self.excluded_packages = ', '.join(excluded_packages)

        self.included_routines = ', '.join(included_routines)
        self.included_routines_no_pkg = ', '.join(included_routines_no_pkg)
        self.excluded_routines = ', '.join(excluded_routines)
        self.excluded_routines_no_pkg = ', '.join(excluded_routines_no_pkg)


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
class IntrospectionDatabase:
    name: str
    pool: SessionPool
    schemes: MutableSequence[SchemaSetup]
    rows: MutableSequence[IntrospectionRow] = field(default_factory=list)


Introspection = MutableSequence[IntrospectionDatabase]
# *****************************INTROSPECTION TYPES*****************************


# **********************INTERMEDIATE REPRESENTATION TYPES**********************
Argument = Union['SimpleArgument', 'ComplexArgument']


@dataclass
class SimpleArgument:  # Flat
    name: str
    position: int
    sequence: int
    data_level: int
    data_type: str
    custom_type_schema: Optional[str]
    custom_type_package: Optional[str]
    custom_type: Optional[str]
    defaulted: bool
    default_value: None  # Always NULL, even if it's defaulted
    in_out: str

    @classmethod
    def from_row(cls, row: IntrospectionRow):
        return cls(
            name=row.argument,
            position=row.position,
            sequence=row.sequence,
            data_level=row.data_level,
            data_type=row.data_type,
            custom_type_schema=row.custom_type_schema,
            custom_type_package=row.custom_type_package,
            custom_type=row.custom_type,
            defaulted=row.defaulted,
            default_value=row.default_value,
            in_out=row.in_out,
        )


@dataclass
class ComplexArgument(SimpleArgument):  # with Nested Arguments
    arguments: MutableSequence[Argument] = field(default_factory=list)

    @property
    def direct_child_data_level(self):
        """If ComplexArgument has lvl == 2, its arguments have lvl == 3"""
        return self.data_level + 1

    @property
    def last_argument(self) -> Argument:
        return self.arguments[-1]

    def dispatch_argument(self, argument: Argument):
        # NOTE: Data Level == 0 is handled at the Routine level
        # NOTE: Data Level < direct_child_data_level is handled by Parents

        # Child that should be lifted into desired Data Level
        if argument.data_level > self.direct_child_data_level:
            self.last_argument.dispatch_argument(argument)
        # Direct Child that should be placed at the Top
        else:
            self.arguments.append(argument)


@dataclass
class Routine:
    name: str
    type: str
    object_id: int
    overload: Optional[int]
    subprogram_id: int
    fqdn: FQDN = field(init=False)  # Set manually or in from_row
    arguments: MutableSequence[Argument] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: IntrospectionRow):
        routine = cls(
            name=row.routine,
            type=row.routine_type,
            object_id=row.object_id,
            overload=row.overload,
            subprogram_id=row.subprogram_id,
        )
        routine.fqdn = FQDN(
            row.schema,
            row.package if row.is_package else '',
            row.routine
        )
        return routine

    @property
    def last_complex_argument(self) -> ComplexArgument:
        return self.arguments[-1]

    def dispatch_argument(self, argument: Argument):
        # Data Level == 0 should be placed at the Top
        if argument.data_level == 0:
            self.arguments.append(argument)
        # Data Level > 0 is a guarantee that the Arg should be nested
        else:
            self.last_complex_argument.dispatch_argument(argument)


@dataclass
class Package:
    name: str
    is_package: bool
    routines: MutableSequence[Routine] = field(default_factory=list)


@dataclass
class Schema:
    name: str
    packages: MutableSequence[Package] = field(default_factory=list)


@dataclass
class Database:
    name: str
    schemes: MutableSequence[Schema] = field(default_factory=list)

    def __post_init__(self):
        self.name = self.name.lower()

    def dispatch_routine(self, row: IntrospectionRow, routine: Routine):
        """Dispatch the Routine into appropriate <schema.package>"""
        if self.schemes and row.schema == self.schemes[-1].name:
            schema = self.schemes[-1]
        else:
            schema = Schema(name=row.schema)
            self.schemes.append(schema)

        if schema.packages and row.package == schema.packages[-1].name:
            package = schema.packages[-1]
        else:
            package = Package(name=row.package, is_package=row.is_package)
            schema.packages.append(package)

        package.routines.append(routine)


IR = MutableSequence[Database]
# **********************INTERMEDIATE REPRESENTATION TYPES**********************


class Generator:
    def __init__(self, conf: MutableMapping, path: Optional[Path] = None):
        self.conf = conf
        self.path: Path = path or conf['path']  # TODO: rewrite path handling
        self.databases: Introspection = []

    def connect(self):
        # Setup Process' ENVs
        if self.conf['oracle_home']:
            environ['ORACLE_HOME'] = self.conf['oracle_home']
        if self.conf['nls_lang']:
            environ['NLS_LANG'] = self.conf['nls_lang']

        # Prepare Databases for introspection
        for db in self.conf.pop('databases'):
            db['name'] = db['name'].upper()

            db['schemes'] = [SchemaSetup(**s) for s in db['schemes']]

            db['pool']['dsn'] = makedsn(**db['pool']['dsn'])
            db['pool'] = SessionPool(**db['pool'])

            self.databases.append(IntrospectionDatabase(**db))

        return self

    def disconnect(self):
        # TODO
        # for db in self.databases:
        #     db.pool.close()
        return self

    @staticmethod
    def _introspect_one_schema(db: IntrospectionDatabase, schema: SchemaSetup):
        binds = {'schema': schema.name}

        # Then fetch only concrete objects
        if schema.include_routines:
            if schema.included_packages:
                sql = [
                    INTROSPECTION_WITH_PACKAGE_SQL,
                    f'  and ao.object_name in ({schema.included_packages})',
                    f'  and aa.object_name in ({schema.included_routines})',
                    'union all',
                ]
            else:
                sql = []

            if schema.included_routines_no_pkg:
                binds['no_package_name'] = schema.no_package_name
                sql.extend([
                    INTROSPECTION_WITHOUT_PACKAGE_SQL,
                    f'  and aa.object_name in '
                    f'({schema.included_routines_no_pkg})',
                ])
        # Else, fetch everything excluding "exclude"
        else:
            binds['no_package_name'] = schema.no_package_name
            sql = [INTROSPECTION_WITH_PACKAGE_SQL]

            if schema.exclude_packages:
                sql.append(
                    f"  and ao.owner "
                    f"|| '.' "
                    f"|| ao.object_name not in ({schema.excluded_packages})"
                )

            if schema.exclude_routines:
                sql.append(
                    f"  and ao.owner "
                    f"|| '.' "
                    f"|| ao.object_name "
                    f"|| '.' "
                    f"|| aa.object_name not in ({schema.excluded_routines})"
                )

            sql.extend([
                'union all',
                INTROSPECTION_WITHOUT_PACKAGE_SQL,
            ])

            if schema.excluded_routines_no_pkg:
                sql.append(
                    f"  and ao.owner "
                    f"|| '.' "
                    f"|| ao.object_name "
                    f"|| '.' "
                    f"|| aa.object_name "
                    f"not in ({schema.excluded_routines_no_pkg})"
                )

        # TODO: some conditions may be redundant
        sql.append(
            'order by package, object_id, subprogram_id, sequence, position'
        )
        sql = '\n'.join(sql)
        LOG.info(repr(f'-- Use print() to format the msg\n-- {binds}\n{sql};'))

        # Fetch all the rows at once
        connection: Connection = db.pool.acquire()
        with connection.cursor() as cursor:
            cursor: Cursor = cursor
            cursor.execute(sql, binds)
            cursor.rowfactory = IntrospectionRow
            new_schema = cursor.fetchall()

        # A guarantee that DB's schemas will be placed in series
        with INTROSPECTION_DB_ADD_NEW_SCHEMA_LOCK:
            db.rows.extend(new_schema)

        db.pool.release(connection)

    def introspection(self, databases: Introspection = None) -> Introspection:
        # Pre-introspection -> Introspection
        # DB introspection, metadata aggregation
        # If SessionPools weren't closed, the method is repeatable

        # Fork and process each schema in a separate thread
        threads = []
        for db in databases or self.databases:
            db.result = []  # Reset any previous result; repeat introspection
            for schema in db.schemes:
                thread = Thread(
                    target=self._introspect_one_schema,
                    args=(db, schema),
                    daemon=True,
                )
                threads.append(thread)
                thread.start()

        # Block and Join
        for thread in threads:
            thread.join()

        return databases or self.databases

    def intermediate_representation(
        self,
        databases: Introspection = None
    ) -> IR:

        intermediate_representation = []

        for introspected in databases or self.databases:
            database = Database(name=introspected.name)
            routine: Optional[Routine] = None  # None before first iteration
            oid = sid = None
            for row in introspected.rows:
                if row.data_type not in CX_COMPLEX_TYPES:
                    argument = SimpleArgument.from_row(row)
                else:
                    argument = ComplexArgument.from_row(row)

                # The Sentinels:
                # subprogram_id is unique for non-package routines
                # object_id is unique for package routines
                if oid != row.object_id or sid != row.subprogram_id:
                    routine = Routine.from_row(row)
                    database.dispatch_routine(row, routine)

                routine.dispatch_argument(argument)

                oid = row.object_id
                sid = row.subprogram_id

            intermediate_representation.append(database)

        return intermediate_representation

    def __call__(self, *args, **kwargs) -> IR:
        return self.intermediate_representation(self.introspection())


class JSONSerializer:
    def __init__(self, ir: Optional[IR] = None):
        self.ir = ir

    def save(self, path: Path, ir: Optional[IR] = None) -> IR:
        path = path.absolute()
        path.mkdir(parents=True, exist_ok=True)
        for db in ir or self.ir:
            json_db = dumps(
                {db.name: asdict(db)},
                ensure_ascii=False,
                indent=4,
            )
            (path / db.name).mkdir(exist_ok=True)
            file = path / db.name / f'{db.name}.json'
            with file.open('w', encoding='utf8') as fd:
                fd.write(str(json_db))
        return ir or self.ir


class YAMLSerializer:
    def __init__(self, ir: Optional[IR] = None):
        self.ir = ir

    def save(self, path: Path, ir: Optional[IR] = None) -> IR:
        path = path.absolute()
        path.mkdir(parents=True, exist_ok=True)
        for db in ir or self.ir:
            yaml_db = dump(
                {db.name: asdict(db)},
                allow_unicode=True,
                default_flow_style=False,
                line_break=True,
                indent=4,
                explicit_start=True,
                explicit_end=True,
                sort_keys=False,
            )
            (path / db.name).mkdir(exist_ok=True)
            file = path / db.name / f'{db.name}.yml'
            with file.open('w', encoding='utf8') as fd:
                fd.write(str(yaml_db))
        return ir or self.ir


class PyModule:
    TEMPLATE = '''\
"""
The package is auto-generated. Don't edit it by hand -- changes won't persist.
{errors}
"""
{imports}

import cx_Oracle

LOG = logging.getLogger(__name__)


class Stub:
    def __init__(self, connection: cx_Oracle.Connection):
        self.connection = connection

    @property
    def cursor(self) -> cx_Oracle.Cursor:
        return self.connection.cursor()


class DEFAULTED:
    """Is defaulted"""


class TBD:
    """The argument is not supported, yet"""


# noinspection PyShadowingBuiltins,DuplicatedCode
class {package_name}(Stub):
{package_body}

'''

    def __init__(self, package: Package):
        self.package = package

        self.imports = {'logging'}
        self.errors = []
        self.definitions = []
        self.methods: MutableSequence[PyMethod] = []

    def __repr__(self):
        errors = ''
        if self.errors:
            errors = (
                '\nErrors (unsupported data types, etc):\n'
                + '\n'.join(f'  {i}. {e}' for i, e in enumerate(self.errors, 1))
            )

        return self.TEMPLATE.format(
            errors=errors,
            imports='\n'.join(f'import {m}' for m in sorted(self.imports)),
            package_name=self.capwords(self.package.name),
            package_body='\n'.join(str(func) for func in self.methods),
        )

    @staticmethod
    def capwords(snake_case: str):
        # TODO: make a dictionary
        with_abbreviations = ABBR_DICT.sub(
            lambda m: m.group(0).upper(),
            snake_case
        )
        return sub(
            r'^\w|_\w',
            lambda m: m.group(0).replace('_', '').capitalize(),
            with_abbreviations
        )

    def add_method(self, routine: Routine):
        func = PyMethod(routine)
        self.imports.update(func.imports)
        self.errors.extend(func.errors)
        self.methods.append(func)


class PyMethod:
    TEMPLATE = '''\
    def {name}(
        {signature}
    ):
        {body}
'''
    INDENT = f'\n{2 * PY_INDENT}'  # package class -> method body
    WITH_INDENT = f'\n{3 * PY_INDENT}'  # package class -> method body -> with

    def __init__(self, routine: Routine):
        self.routine = routine

        name = routine.name
        name = name if not routine.overload else f'{name}_{routine.overload}'
        name = name if not iskeyword(name) else f'{name}_'
        self.py_name = name
        self.py_signature = []
        self.py_body = []

        self.imports = set()
        self.errors = []

        self.cx_call_name = routine.fqdn
        self.cx_in = []
        self.cx_func_out = ''
        self.cx_func_out_end = []
        self.cx_proc_out = []

        # Optimizations:
        self.is_args = any(a for a in routine.arguments if a.in_out != 'out')
        self.sorted_args: MutableSequence[Argument] = list(
            sorted(self.routine.arguments, key=lambda a: a.defaulted)
        )

        # The call has cost, but has no side-effects
        # So, it may be called more then once
        self.init_arguments()

    def init_arguments(self):
        # Reset data from previous calls, if any
        self.py_signature = ['self,', '*,'] if self.is_args else ['self,']
        if self.routine.type == 'function':
            self.py_body = [  # Within with
                'inp = dict()',
                'cursor = self.cursor',
                'with cursor:',
                '    {cx_in}',
                '    result = cursor.callfunc(',
                '        "{cx_call_name}",',
                '        {cx_func_out},',
                '        parameters=[],',
                '        keywordParameters=inp,',
                '    )',
                '    {cx_func_out_end}'
            ]
        else:
            self.py_body = [  # Within with
                'inp = dict()',
                'cursor = self.cursor',
                'with cursor:',
                '    {cx_in}',
                '    {cx_proc_out}',
                '    cursor.callproc(',
                '       "{cx_call_name}",',
                '       parameters=[],',
                '       keywordParameters=inp,',
                '    )',
            ]
        self.cx_in = []
        self.cx_func_out = ''
        self.cx_func_out_end = []
        self.cx_proc_out = []

        # In ORACLE, defaulted arguments may be placed at any position
        # In Python, we should place them at the end
        for arg in self.sorted_args:
            cx_type = CX_SIMPLE_TYPES.get(arg.data_type)
            py_type = PY_SIMPLE_TYPES.get(arg.data_type)
            arg_name = arg.name if not iskeyword(arg.name) else f'{arg.name}_'

            msg = (
                f'{self.routine.type.capitalize()} '
                f'{self.py_name} ({self.cx_call_name}) has unsupported '
                f'"{arg.in_out}" argument "{arg_name}": {arg.data_type}'
            )

            # IN or IN/OUT arg
            if arg.in_out != 'out':
                if arg.data_type in CX_COMPLEX_TYPES:
                    LOG.warning(msg)
                    self.errors.append(msg)
                    py_type = 'object'
                    # TODO: cx_prepare IN or IN/OUT

                py_in = f'{arg_name}: {py_type},'
                if arg.defaulted:
                    py_in = py_in[:-1] + ' = DEFAULTED,'
                    self.cx_in.extend([
                        f'if {arg_name} is not DEFAULTED:',
                        f'    inp["{arg_name}"] = {arg_name}'
                    ])
                else:
                    self.cx_in.append(f'inp["{arg_name}"] = {arg_name}')

                self.py_signature.append(py_in)

                if '.' in py_type:
                    module, *_ = py_type.split('.')
                    self.imports.add(module)

            # OUT arg and FUNCTION
            elif self.routine.type == 'function':
                if arg.data_type in CX_COMPLEX_TYPES:
                    LOG.warning(msg)
                    self.errors.append(msg)
                    cx_type = 'TBD'
                    # TODO: cx_prepare OUT

                if arg.data_type == 'ref cursor':
                    self.cx_func_out_end.append('result = result.fetchall()')

                self.cx_func_out = cx_type

            # OUT arg and PROCEDURE
            else:
                out = []
                if arg.data_type in CX_COMPLEX_TYPES:
                    LOG.warning(msg)
                    self.errors.append(msg)
                    out.append(f'inp["{arg_name}"] = TBD')
                    # TODO: cx_prepare OUT
                else:
                    out.append(f'inp["{arg_name}"] = cursor.var({cx_type})')

                out.append(f'out.append(inp["{arg_name}"])')

                self.cx_proc_out.extend(out)

        if self.routine.type == 'procedure':
            if self.cx_proc_out:
                self.cx_proc_out.insert(0, 'out = []')
                self.py_body.append('result = [arg.getvalue() for arg in out]')
                self.py_body.append('return result')
            else:
                self.py_body.append('return None')
        else:
            self.py_body.append('return result')

    def __repr__(self):
        name = self.py_name
        signature = self.INDENT.join(self.py_signature)

        body_template = self.INDENT.join(self.py_body)
        cx_in = self.WITH_INDENT.join(self.cx_in)
        cx_func_result_end = self.WITH_INDENT.join(self.cx_func_out_end)
        cx_proc_out = self.WITH_INDENT.join(self.cx_proc_out)

        body = body_template.format(
            cx_in=cx_in,
            cx_call_name=self.cx_call_name,
            cx_func_out=self.cx_func_out,
            cx_func_out_end=cx_func_result_end,
            cx_proc_out=cx_proc_out,
        )

        return self.TEMPLATE.format(name=name, signature=signature, body=body)


class PythonSerializer:
    def __init__(self, ir: Optional[IR] = None):
        self.ir = ir

    def save(self, path: Path, ir: Optional[IR] = None) -> IR:
        path = path.absolute()
        path.mkdir(parents=True, exist_ok=True)
        for db in ir or self.ir:
            (path / db.name).mkdir(exist_ok=True)
            (path / db.name / '__init__.py').touch(exist_ok=True)

            for schema in db.schemes:
                schema_path = path / db.name / schema.name
                schema_path.mkdir(exist_ok=True)
                (schema_path / '__init__.py').touch(exist_ok=True)

                for package in schema.packages:
                    py_module = PyModule(package)

                    for routine in package.routines:
                        py_module.add_method(routine)

                    module = schema_path / f'{package.name}.py'
                    with module.open('w', encoding='utf8') as fd:
                        fd.write(str(py_module))

        return ir or self.ir


def main():
    config = Config()
    generator = Generator(config).connect()
    try:
        ir = generator()
    finally:
        generator.disconnect()

    ir = JSONSerializer().save(generator.path, ir)
    ir = YAMLSerializer().save(generator.path, ir)
    PythonSerializer().save(generator.path, ir)

    return 0


if __name__ == '__main__':
    main()
