from argparse import ArgumentParser
from dataclasses import dataclass, field
from logging.config import dictConfig
from logging import Filter, getLogger
from os import getenv, environ
from pathlib import Path
from re import compile
from sys import exit
from typing import (
    MutableMapping,
    MutableSequence,
    Tuple,
    Optional,
    Union,
    Pattern,
)

from cx_Oracle import SessionPool, makedsn
from marshmallow import Schema as MarshmallowSchema, post_load
from marshmallow.fields import Boolean, Dict, String, Integer, Nested, List
from pkg_resources import get_distribution
from yaml import SafeLoader, load, dump

LOG = getLogger(__name__)
VERSION = get_distribution('db-stubs-generator').version


# *****************************Additional Utilities*****************************
class APPVersionLoggingFilter(Filter):
    def filter(self, record):
        record.app_version = VERSION
        return True
# *****************************Additional Utilities*****************************


# *****************************Configuration Types*****************************
ObjectIDANDSubprogramIDANDArgumentPosition = Tuple[int, int, int]
ObjectIDANDSubprogramID = Tuple[int, int]
IntrospectionAppendixKey = Union[
    ObjectIDANDSubprogramIDANDArgumentPosition,
    ObjectIDANDSubprogramID
]


@dataclass
class IntrospectionAppendix:
    comment: str
    object_id: int
    subprogram_id: int
    position: Optional[int] = field(default=None)
    # Should match the spec of dbsg.lib.introspection.IntrospectionRow
    new: MutableMapping = field(init=False)

    def __init__(self, **kwargs):
        self.comment = kwargs.pop('comment')
        self.object_id = kwargs.pop('object_id')
        self.subprogram_id = kwargs.pop('subprogram_id')
        self.position = kwargs.pop('position', None)
        self.new = kwargs


@dataclass
class FQDN:
    # TODO: docstring

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
class Schema:
    name: str
    no_package_name: str = field(default='')

    introspection_appendix: MutableMapping[
        IntrospectionAppendixKey,
        IntrospectionAppendix
    ] = field(default_factory=dict)

    exclude_packages: MutableSequence[FQDN] = field(default_factory=list)
    exclude_routines: MutableSequence[FQDN] = field(default_factory=list)
    include_routines: MutableSequence[FQDN] = field(default_factory=list)

    included_packages: str = field(init=False)
    excluded_packages: str = field(init=False)
    included_routines: str = field(init=False)
    excluded_routines: str = field(init=False)
    included_routines_no_pkg: str = field(init=False)
    excluded_routines_no_pkg: str = field(init=False)

    def __post_init__(self):
        self.name = self.name.upper()

        no_pkg = self.no_package_name or f'{self.name}_no_pkg'
        self.no_package_name = no_pkg.upper()

        # The original data will be in conformance with type annotations after
        # __post_init__
        exclude_packages = []
        exclude_routines = []
        include_routines = []

        # Already prepared strings for introspection SQL "binding"
        included_packages = set()
        excluded_packages = set()
        included_routines = []
        excluded_routines = []
        included_routines_no_pkg = []
        excluded_routines_no_pkg = []

        # If there's include_routines, ONLY this routines will be introspected
        # noinspection PyTypeChecker
        for routine in self.normalize(self.name, self.include_routines):
            # noinspection PyArgumentList
            fqdn = FQDN(*routine)
            include_routines.append(fqdn)
            if fqdn.package:
                included_routines.append(repr(fqdn))
                included_packages.add(repr(fqdn.package))
            else:
                included_routines_no_pkg.append(repr(fqdn.routine))

        # noinspection PyTypeChecker
        for package in self.exclude_packages:
            # noinspection PyUnresolvedReferences
            package = package.upper()
            exclude_packages.append(package)
            # It doesn't make sense to exclude anything, if we've included
            # ONLY concrete routines
            if not include_routines:
                excluded_packages.add(repr(package))

        # noinspection PyTypeChecker
        for routine in self.normalize(self.name, self.exclude_routines):
            # noinspection PyArgumentList
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

    @staticmethod
    def normalize(
        name: str,
        objects: MutableSequence[str]
    ) -> MutableSequence[MutableSequence[str]]:
        """Normalize DB objects to their Pre-FQDN form.

        For example:
            'schema.package.routine' -> ['schema', 'package', 'routine']
            'package.routine' -> ['schema', 'package', 'routine']
            'schema.routine' -> ['schema', '', 'routine']
            'routine' -> ['schema', '', 'routine']
        """

        normalized = []
        for obj in objects or []:
            obj = obj.split('.')
            if obj[0] != name or len(obj) == 1:
                obj.insert(0, name)
            if len(obj) == 2:
                obj.insert(1, '')
            normalized.append(obj)

        return normalized


@dataclass
class DSN:
    """
    https://cx-oracle.readthedocs.io/en/latest/module.html#cx_Oracle.makedsn
    """
    host: str
    port: int
    sid: Optional[str] = field(default=None)
    service_name: Optional[str] = field(default=None)


@dataclass
class Pool:
    """
    https://cx-oracle.readthedocs.io/en/latest/module.html#cx_Oracle.Connection
    """
    user: str
    password: str
    dsn: Union[DSN, object]  # cx_Oracle.dsn
    threaded: bool = field(default=True)
    homogeneous: bool = field(default=True)
    min: int = field(default=8)
    max: int = field(default=8)
    encoding: Optional[str] = field(default=None)

    def __post_init__(self):
        self.dsn = makedsn(
            host=self.dsn.host,
            port=self.dsn.port,
            sid=self.dsn.sid,
            service_name=self.dsn.service_name,
        )


@dataclass
class Database:
    name: str
    pool: Pool
    schemes: MutableSequence[Schema]

    # Will be available after connection
    session_pool: SessionPool = field(init=False, repr=False)

    def __post_init__(self):
        self.name = self.name.upper()

    def connect(self) -> SessionPool:
        self.session_pool = SessionPool(
            user=self.pool.user,
            password=self.pool.password,
            dsn=self.pool.dsn,
            threaded=self.pool.threaded,
            homogeneous=self.pool.homogeneous,
            min=self.pool.min,
            max=self.pool.max,
            encoding=self.pool.encoding,
        )
        return self.session_pool

    def disconnect(self):
        ...  # TODO


@dataclass
class Configuration:
    databases: MutableSequence[Database]
    logging: dict
    plugins: MutableSequence[str]
    abbreviations: Pattern[str]
    outcomes: MutableMapping[str, str]
    path: Path = field(default='stubs')
    oracle_home: Optional[str] = field(default=None)
    nls_lang: Optional[str] = field(default='American_America.AL32UTF8')

    def __post_init__(self):
        # Setup Process' ENVs
        if self.oracle_home:
            environ['ORACLE_HOME'] = self.oracle_home
        if self.nls_lang:
            environ['NLS_LANG'] = self.nls_lang
# *****************************Configuration Types*****************************


# **************************Configuration Serializers**************************
# Serializers used for PRE-loading only. They guarantee that:
# 1. The conf will be statically typed
# 2. If there are any invalid/missed options, the errors will be caught
# 3. The errors will be printed
# 4. The options will be pre-casted to Python types
# 5. Post-loading all the complex data-structures into the corresponding
#    dataclasses, so the final config will be fully annotated

# Serializers aren't used for:
# 1. Final typecasting -- that's a dataclasses task. Because we want a typed
#    config, not some dynamic dict()
# 2. Providing default/fallback values. Again, that's a dataclasses task
class DSNSchema(MarshmallowSchema):
    host = String()
    port = Integer()
    sid = String(required=False, allow_none=True)
    service_name = String(required=False, allow_none=True)


class PoolSchema(MarshmallowSchema):
    user = String()
    password = String()
    dsn = Nested(DSNSchema, required=True)
    threaded = Boolean(required=False)
    homogeneous = Boolean(required=False)
    min = Integer(required=False)
    max = Integer(required=False)
    encoding = String(required=False, allow_none=True)

    @post_load
    def post_load(self, data):
        data['dsn'] = DSN(**data['dsn'])
        return data


class SchemesSchema(MarshmallowSchema):
    name = String(required=True)
    no_package_name = String(required=False, allow_none=True)
    introspection_appendix = List(Dict(), required=False, allow_none=True)
    exclude_packages = List(String(), required=False, allow_none=True)
    exclude_routines = List(String(), required=False, allow_none=True)
    include_routines = List(String(), required=False, allow_none=True)

    @post_load
    def post_load(self, data):
        introspection_appendix = {}
        for ia in data.get('introspection_appendix', []):
            if ia.get('position') is not None:
                key = ia['object_id'], ia['subprogram_id'], ia['position']
            else:
                key = ia['object_id'], ia['subprogram_id']
            introspection_appendix[key] = IntrospectionAppendix(**ia)
        data['introspection_appendix'] = introspection_appendix
        return data


class DatabaseSchema(MarshmallowSchema):
    name = String(required=True)
    pool = Nested(PoolSchema, required=True)
    schemes = Nested(SchemesSchema, required=True, many=True)

    @post_load
    def post_load(self, data):
        data['pool'] = Pool(**data['pool'])
        data['schemes'] = [Schema(**s) for s in data['schemes']]
        return data


class ConfigSchema(MarshmallowSchema):
    path = String(required=False)
    plugins = List(String(), required=True)
    abbreviation_files = List(String(), required=False)

    oracle_home = String(required=False, allow_none=True)
    nls_lang = String(required=False, allow_none=True)
    databases = Nested(DatabaseSchema, required=True, many=True)

    logging = Dict(required=True)

    @post_load
    def post_load(self, data):
        outcomes = {}
        words = []
        for file in data.pop('abbreviation_files', []):
            with open(file, 'r', encoding='utf8') as fd:
                for word in fd:
                    if not word or word.startswith('#'):
                        continue

                    if '#' in word:
                        word, *_ = word.split('#')

                    outcome = None
                    if '=' in word:
                        word, outcome = word.split('=')

                    word = word.strip()
                    words.append(word)
                    if outcome is not None:
                        outcomes[word] = outcome.strip()

        data['abbreviations'] = compile(rf'(\b|_)({"|".join(words)})(\b|_)')
        data['outcomes'] = outcomes
        data['databases'] = [Database(**db) for db in data['databases']]
        data['path'] = Path(data['path'])
        data['config'] = Configuration(**data)
        return data
# **************************Configuration Serializers**************************


# ******************************Configuration CLI******************************
CommandLineInterface = ArgumentParser()
CommandLineInterface.add_argument(
    '--config',
    dest='config',
    default=None,
)
CommandLineInterface.add_argument(
    nargs='?',
    dest='path',
    default=None,
)
CommandLineInterface.add_argument(
    '--plugins',
    nargs='*',
    dest='plugins',
    default=['json'],
)
CommandLineInterface.add_argument(
    '--abbreviation-files',
    nargs='*',
    dest='abbreviation_files',
    default=['default_abbreviations.txt'],
)
# ******************************Configuration CLI******************************


# **************************Configuration Entry Point**************************
class Setup:
    VALIDATOR = ConfigSchema()
    CLI: ArgumentParser = CommandLineInterface

    def __init__(self):
        cli = self.CLI.parse_args().__dict__ or {}
        dbsg_conf = cli.pop('config', None)

        # CLI args take precedence over YAML config
        self.cli = cli

        # CLI path takes precedence over ENV path
        self.path = dbsg_conf or getenv('DBSG_CONF', 'dbsg_config.yml')

    def merge_cli_with_file(self) -> MutableMapping:
        with open(self.path, 'r', encoding='utf8') as fh:
            data = load(fh, Loader=SafeLoader)

        data.update((k, v) for k, v in self.cli.items() if v is not None)

        return data

    @classmethod
    def validate_and_cast(cls, data, path) -> Configuration:
        valid, errors = cls.VALIDATOR.load(data)
        if errors:
            print(
                f"The '{path}' configuration is invalid.",
                'The following fields are missing/invalid:',
                dump(
                    errors,
                    default_flow_style=False,
                    indent=4,
                    explicit_start=True,
                    explicit_end=True
                ),
                f'After merging with CLI arguments, your config was: {data}',
                sep='\n'
            )
            exit(1)
        return valid['config']

    @staticmethod
    def activate_logging(config: Configuration) -> Configuration:
        log = config.logging

        dictConfig(log)

        root_level = log['root']['level']
        root_handlers = ', '.join(log['root']['handlers'])
        non_root_loggers = log['loggers'].items()
        non_root_loggers = (f'{n} [{p["level"]}]' for n, p in non_root_loggers)
        non_root_loggers = ', '.join(non_root_loggers)

        LOG.debug(f'The config was loaded: {log}')
        LOG.info(f"The Root Logger [{root_level}] handlers: {root_handlers}")
        LOG.info(f"Non Root Loggers: {non_root_loggers}")

        return config

    def configuration(self) -> Configuration:
        raw = self.merge_cli_with_file()
        valid = self.activate_logging(self.validate_and_cast(raw, self.path))
        return valid
# **************************Configuration Entry Point**************************
