from argparse import ArgumentParser
from collections import UserDict
from os import getenv
from sys import exit
from pathlib import Path
from typing import MutableSequence
from logging.config import dictConfig
from logging import Filter, getLogger


from pkg_resources import get_distribution
from marshmallow import Schema, fields, post_load
from yaml import SafeLoader, load, dump

log = getLogger(__name__)

VERSION = get_distribution('db-stubs-generator').version


def normalize_objects(
    schema: str,
    objects: MutableSequence[str]
) -> MutableSequence[MutableSequence[str]]:
    # Normalize:
    # 'schema.package.routine' -> ['schema', 'package', 'routine']
    # 'package.routine' -> ['schema', 'package', 'routine']
    # 'schema.routine' -> ['schema', '', 'routine']
    # 'routine' -> ['schema', '', 'routine']

    normalized = []
    for obj in objects or []:
        obj = obj.split('.')
        if obj[0] != schema or len(obj) == 1:
            obj.insert(0, schema)
        if len(obj) == 2:
            obj.insert(1, '')
        normalized.append(obj)
    return normalized


class APPVersionLoggingFilter(Filter):
    def filter(self, record):
        record.app_version = VERSION
        return True


class Config(UserDict):
    """
    DB Stubs Generator Config.

    It is a dict-like object.
    """

    def __init__(self, path=None, additional=None):
        super().__init__()

        parser = ArgumentParser()
        parser.add_argument(
            '--config',
            dest='path',
            default=None,
        )
        parser.add_argument(
            nargs='?',
            dest='path',
            default=None,
        )
        cli = parser.parse_args().__dict__  # CLI args take precedence

        path = path or cli.pop('path') or getenv('DBSG_CONF', 'dbsg_config.yml')
        additional = additional or cli or {}

        with open(path, 'r', encoding='utf8') as fd:
            data = load(fd, Loader=SafeLoader)

        data.update((k, v) for k, v in additional.items() if v is not None)

        self.data = self.validate(data, path)

        lg = self.data['logging']

        dictConfig(lg)

        log.debug(f'The config was loaded: {self.data}')

        log.info(
            f"The Root Logger [{lg['root']['level']}] "
            f"handlers: {', '.join(lg['root']['handlers'])}"
        )

        non_root_loggers = (
            '{0} [{1}]'.format(n, p['level']) for n, p in lg['loggers'].items()
        )
        log.info(f"Non Root Loggers: {', '.join(non_root_loggers)}")

    @staticmethod
    def validate(data, path):
        validator = ConfigSchema()
        data, errors = validator.load(data)
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
                sep='\n'
            )
            exit(1)
        return data


class DSNSchema(Schema):
    """
    https://cx-oracle.readthedocs.io/en/latest/module.html#cx_Oracle.makedsn
    """
    host = fields.String()
    port = fields.Integer()
    sid = fields.String(
        required=False,
        allow_none=True,
        missing=None,
    )
    service_name = fields.String(
        required=False,
        allow_none=True,
        missing=None,
    )


class PoolSchema(Schema):
    """
    https://cx-oracle.readthedocs.io/en/latest/module.html#cx_Oracle.Connection
    """
    user = fields.String()
    password = fields.String()
    dsn = fields.Nested(
        DSNSchema,
        required=True,
    )
    threaded = fields.Boolean(
        required=False,
        missing=True,
    )
    homogeneous = fields.Boolean(
        required=False,
        missing=True,
    )
    min = fields.Integer(
        required=False,
        missing=8,
    )
    max = fields.Integer(
        required=False,
        missing=8,
    )
    encoding = fields.String(
        required=False,
        allow_none=True,
        missing=None,
    )


class SchemesSchema(Schema):
    name = fields.String(
        required=True
    )
    no_package_name = fields.String(
        required=False,
        allow_none=True,
        missing=None,
    )
    exclude_packages = fields.List(
        fields.String(),
        required=False,
        allow_none=True,
        missing=None,
    )
    exclude_routines = fields.List(
        fields.String(),
        required=False,
        allow_none=True,
        missing=None,
    )
    include_routines = fields.List(
        fields.String(),
        required=False,
        allow_none=True,
        missing=None,
    )

    @post_load
    def post_load(self, schema):
        name = schema['name']
        if not schema['no_package_name']:
            schema['no_package_name'] = f'{name}_no_pkg'

        exclude_routines = schema.get('exclude_routines', [])
        include_routines = schema.get('include_routines', [])
        schema['exclude_routines'] = normalize_objects(name, exclude_routines)
        schema['include_routines'] = normalize_objects(name, include_routines)

        return schema


class DatabaseSchema(Schema):
    name = fields.String(
        required=True,
    )
    pool = fields.Nested(
        PoolSchema,
        required=True,
    )
    schemes = fields.Nested(
        SchemesSchema,
        required=True,
        many=True,
    )


class ConfigSchema(Schema):
    """Config Definition"""

    path = fields.String(
        required=False,
        missing='stubs',  # $(pwd)/stubs/
        desc='Абсолютный или относительный (PWD) путь для результата',
    )

    oracle_home = fields.String(
        required=False,
        allow_none=True,
        missing=None,
    )
    nls_lang = fields.String(
        required=False,
        allow_none=True,
        missing='American_America.AL32UTF8',
    )
    databases = fields.Nested(
        DatabaseSchema,
        required=True,
        many=True,
    )

    logging = fields.Dict(
        required=True,
    )

    @post_load
    def post_load(self, config):
        config['path'] = Path(config['path'])
        return config
