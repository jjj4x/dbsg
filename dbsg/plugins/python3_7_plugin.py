from keyword import iskeyword
from logging import getLogger
from re import compile
from typing import MutableSequence, Match

from dbsg.lib.configuration import Configuration
from dbsg.lib.introspection import COMPLEX_TYPES
from dbsg.lib.intermediate_representation import Argument, Routine, Package
from dbsg.lib.plugin import PluginABC

LOG = getLogger(__name__)

REGISTRY_NAME = 'python3.7'

SNAKE_CASE = compile(r'^\w|_\w')
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
    'raw': 'typing.Union[str, bytes]',
    'date': 'datetime.datetime',
    'timestamp': 'datetime.datetime',
    'timestamp with time zone': 'datetime.datetime',
    'timestamp with local time zone': 'datetime.datetime',
    'ref cursor': 'typing.MutableSequence',
    'pl/sql boolean': 'bool',
    'binary_integer': 'int',
}
WS = '    '  # python indent (whitespaces)
LF = '\n'  # line feed (new line)


class Plugin(PluginABC):
    GENERIC_MODULE_TEMPLATE = '''\
"""
The package is auto-generated. Don't edit it by hand -- changes won't persist.
"""
import cx_Oracle


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
'''

    def __init__(self, configuration, introspection, ir, **kwargs):
        self.configuration = configuration
        self.introspection = introspection
        self.ir = ir
        self.kwargs = kwargs

    @classmethod
    def name(cls):
        return REGISTRY_NAME

    def save(self, **kwargs):
        path = self.configuration.path.absolute()
        path.mkdir(parents=True, exist_ok=True)
        (path / '__init__.py').touch(exist_ok=True)

        # Top-Level: stubs python package and its helpers
        with (path / 'generic.py').open('w', encoding='utf8') as fd:
            fd.write(self.GENERIC_MODULE_TEMPLATE)

        for db in self.ir:
            # DB-Level: db python package -- a placeholder for schema packages
            (path / db.name).mkdir(exist_ok=True)
            (path / db.name / '__init__.py').touch(exist_ok=True)

            for schema in db.schemes:
                # Schema-Level: schema python package of db package modules
                schema_path = path / db.name / schema.name
                schema_path.mkdir(exist_ok=True)
                (schema_path / '__init__.py').touch(exist_ok=True)

                for package in schema.packages:
                    # Package-Level: python module with its relevant content
                    python_module = PyModule(self.configuration, package)

                    for routine in package.routines:
                        python_module.add_method(routine)

                    module = schema_path / f'{package.name}.py'
                    with module.open('w', encoding='utf8') as fd:
                        fd.write(str(python_module))


Python37Plugin = Plugin


class PyModule:
    TEMPLATE = '''\
"""
The package is auto-generated. Don't edit it by hand -- changes won't persist.
{errors}
"""
{imports}

import cx_Oracle

import {path}.generic as generic

LOG = logging.getLogger(__name__)


# noinspection DuplicatedCode,PyPep8Naming
class {package_name}(generic.Stub):
{package_body}

'''

    def __init__(self, configuration: Configuration, package: Package):
        self.path = configuration.path
        # Abbreviations RegEx is made dynamically on the Configuration stage
        self.abbreviations = configuration.abbreviations
        self.outcomes = configuration.outcomes
        self.package = package
        self.name = self.abbreviated_capwords(package.name)

        self.imports = {'logging'}

        # Will be placed into the top docstring, if any
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
            path=self.path,
            errors=errors,
            imports='\n'.join(f'import {m}' for m in sorted(self.imports)),
            package_name=self.name,
            package_body='\n'.join(str(method) for method in self.methods),
        )

    def abbreviate(self, match: Match):
        word = match.group(0)
        return self.outcomes.get(word) or word.upper()

    @staticmethod
    def capitalize(match: Match):
        return match.group(0).replace('_', '').capitalize()

    def abbreviated_capwords(self, snake_case: str):
        abbreviated = self.abbreviations.sub(self.abbreviate, snake_case)
        return SNAKE_CASE.sub(self.capitalize, abbreviated)

    def add_method(self, routine: Routine):
        method = PyMethod(routine)
        self.imports.update(method.imports)
        self.errors.extend(method.errors)
        self.definitions.extend(method.definitions)
        self.methods.append(method)


class PyMethod:
    TEMPLATE = '''\
    def {name}(
        {signature}
    ):
        {body}
'''
    FUNCTION_INDENT = f'\n{2 * WS}'  # package class -> method body
    STATEMENTS_INDENT = f'\n{3 * WS}'  # package class -> method body -> with

    def __init__(self, routine: Routine):
        self.routine = routine

        # The info should be dispatched into Python Module (DB Package) Level
        self.imports = set()
        self.errors = []
        self.definitions = []

        # The name should be prepared, considering...
        name = routine.name
        # Python does't have native multidispatch
        name = name if not routine.overload else f'{name}_{routine.overload}'
        # The name should collide with Python's keywords
        name = name if not iskeyword(name) else f'{name}_'
        self.py_name = name

        # The keyword-only call should be enforced. But only if there are any
        # arguments
        self.py_def = ['self,', '*,'] if self.routine.has_ins else ['self,']

        # Procedures and Functions have different placeholders
        if self.routine.type == 'function':
            self.py_body = [  # Within with
                'inp = dict()',
                'cursor = self.cursor',
                'with cursor:',
                '    {cx_in}',
                '    {cx_out}',
                '    out = cursor.callfunc(',
                '        "{cx_call_name}",',
                '        {cx_func_out},',
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
                '    {cx_out}',
                '    cursor.callproc(',
                '       "{cx_call_name}",',
                '       keywordParameters=inp,',
                '    )',
                '    {cx_proc_out_end}',
            ]

        self.cx_call_name = routine.fqdn
        self.cx_in = []
        self.cx_out = []
        self.cx_func_out = ''
        self.cx_func_out_end = []
        self.cx_proc_out_end = ''

        # The calls have overhead, but have no side-effects
        self.process_arguments()

    def process_in_(self, arg: Argument, indent='', **kwargs):
        _ = indent
        __ = indent + '    '
        name = kwargs['name']
        py_type = kwargs['py_type']
        if arg.data_type in COMPLEX_TYPES:
            self.imports.add('typing')
            arg_ct = arg.custom_type_fqdn.upper()

            if arg.data_type in ('varray', 'table', 'pl/sql table'):
                if (
                    arg.arguments
                    and arg.last_argument.data_type in PY_SIMPLE_TYPES
                ):
                    nested_type = PY_SIMPLE_TYPES[arg.last_argument.data_type]
                    self.cx_in.append(f'{_}inp["{name}"] = {name}')
                else:
                    nested_type = 'typing.Mapping'
                    nested_arg_ct = arg.last_argument.custom_type_fqdn.upper()
                    self.cx_in.append(f'{_}inp["{name}"] = cursor.var(')
                    self.cx_in.append(f'{__}cx_Oracle.OBJECT,')
                    self.cx_in.append(f'{__}typename="{arg_ct}",')
                    self.cx_in.append(f'{_}).type.newobject()')
                    self.cx_in.append(f'{_}nested_type = cursor.var(')
                    self.cx_in.append(f'{__}cx_Oracle.OBJECT,')
                    self.cx_in.append(f'{__}typename="{nested_arg_ct}",')
                    self.cx_in.append(f'{_}).type')
                    self.cx_in.append(f'{_}for el in {name}:')
                    self.cx_in.append(f'{__}nested = nested_type.newobject()')
                    for nested_of_nested in arg.last_argument.arguments:
                        n = nested_of_nested.name
                        self.cx_in.append(f'{__}nested.{n.upper()} = el["{n}"]')
                    self.cx_in.append(f'{__}inp["{name}"].append(nested)')

                py_type = f'typing.MutableSequence[{nested_type}]'

            if arg.data_type in ('object', 'record', 'pl/sql record'):
                self.cx_in.append(f'{_}inp["{name}"] = cursor.var(')
                self.cx_in.append(f'{__}cx_Oracle.OBJECT,')
                self.cx_in.append(f'{__}typename="{arg_ct}",')
                self.cx_in.append(f'{_}).type.newobject()')
                for nested in arg.arguments:
                    n = nested.name
                    self.cx_in.append(
                        f'{_}inp["{name}"].{n.upper()} = {name}["{n}"]'
                    )

                py_type = f'typing.Mapping'

        else:
            self.cx_in.append(f'{_}inp["{name}"] = {name}')

        return py_type

    def process_in(self, arg: Argument, **kwargs):
        name = kwargs['name']
        if arg.defaulted:
            self.imports.add('typing')
            self.cx_in.append(f'if {name} is not generic.DEFAULTED:')
            py_type = self.process_in_(arg, indent='    ', **kwargs)
            py_in = f'{name}: typing.Optional[{py_type}] = generic.DEFAULTED,'
        else:
            py_type = self.process_in_(arg, indent='', **kwargs)
            py_in = f'{name}: {py_type},'

        self.py_def.append(py_in)

        if '.' in py_type:
            module, *_ = py_type.split('.')
            self.imports.add(module)

    def process_in_out(self, arg: Argument, **kwargs):
        # TODO: proc in/out
        name = kwargs['name']

        if arg.defaulted:
            LOG.warning('is not supported yet')

            py_in = f'{name}: typing.Optional[typing.Any] = generic.DEFAULTED,'
        else:
            py_in = f'{name}: typing.Any,'

        self.imports.add('typing')
        self.py_def.append(py_in)

    def process_function_out(self, arg: Argument, **kwargs):
        name = kwargs['name']
        cx_type = kwargs['cx_type']

        if arg.data_type == 'ref cursor':
            self.cx_func_out = cx_type
            self.cx_func_out_end.append('out = out.fetchall()')

        elif arg.data_type in COMPLEX_TYPES:
            self.cx_func_out = arg.name
            arg_ct = arg.custom_type_fqdn.upper()

            if arg_ct:
                typename = f'"{arg_ct}",'
            else:
                typename = f'"",  # FIXME: undefined; probably a %ROWTYPE'
                error_msg = (
                    f'FIXME: {self.routine.type.capitalize()} '
                    f'{self.py_name} ({self.cx_call_name}) has an undefined '
                    f'typename for {arg.in_out} argument "{arg.name}". '
                    f'It is probably a %ROWTYPE which you can provide via '
                    f'confing.'
                )
                LOG.warning(error_msg)
                self.errors.append(error_msg)

            cx_type = [
                f'{name} = cursor.var(',
                f'    cx_Oracle.OBJECT,',
                f'    typename={typename}',
                f')',
            ]
            self.cx_out.extend(cx_type)

            # TODO: currently only data_level == 1
            if arg.data_type in ('varray', 'table', 'pl/sql table'):
                # It seems that table-like args cannot have more that 1 nested
                # argument

                if arg.last_argument.data_type == 'object':
                    self.cx_func_out_end.append('out = [')
                    self.cx_func_out_end.append('    {')
                    self.cx_func_out_end.append(
                        '        attr.name.lower(): getattr(obj, attr.name)'
                    )
                    self.cx_func_out_end.append(
                        '        for attr in obj.type.attributes'
                    )
                    self.cx_func_out_end.append('    }')
                    self.cx_func_out_end.append('    for obj in out.aslist()')
                    self.cx_func_out_end.append(']')
                elif arg.last_argument.data_type in ('record', 'pl/sql record'):
                    self.cx_func_out_end.append(
                        '# FIXME: table of records is probably not supported '
                        'on library level!'
                    )
                    self.cx_func_out_end.append('out = [')
                    self.cx_func_out_end.append('    {')
                    for nested_of_nested in arg.last_argument.arguments:
                        n = nested_of_nested.name
                        self.cx_func_out_end.append(
                            f'        "{n}": rec.{n.upper()},'
                        )
                    self.cx_func_out_end.append('    }')
                    self.cx_func_out_end.append('    for rec in out or []')
                    self.cx_func_out_end.append(']')
                else:
                    self.cx_func_out_end.append('out = out.aslist()')

            if arg.data_type in ('object', 'record', 'pl/sql record'):
                self.cx_func_out_end.append('out = {')
                for nested in arg.arguments:
                    n = nested.name
                    self.cx_func_out_end.append(f'    "{n}": out.{n.upper()},')
                self.cx_func_out_end.append('}')

        else:
            self.cx_func_out = cx_type

    def process_procedure_out(self, arg: Argument, **kwargs):
        name = kwargs['name']
        cx_type = kwargs['cx_type']

        # TODO: possibly complex
        if arg.data_type == 'ref cursor':
            self.cx_out.append(f'inp["{name}"] = cursor.var(cx_Oracle.CURSOR)')
            get_val = f'    out["{name}"] = inp["{name}"].getvalue().fetchall()'

        elif arg.data_type in COMPLEX_TYPES:
            arg_ct = arg.custom_type_fqdn.upper()

            if arg.data_type in ('object', 'record', 'pl/sql record'):
                self.cx_out.append(f'inp["{name}"] = cursor.var(')
                self.cx_out.append(f'    cx_Oracle.OBJECT,')
                self.cx_out.append(f'    typename="{arg_ct}",')
                self.cx_out.append(f')')

            if arg.data_type in ('varray', 'table', 'pl/sql table'):
                if (
                    arg.arguments
                    and arg.last_argument.data_type
                    in PY_SIMPLE_TYPES
                ):
                    self.cx_in.append(f'inp["{name}"] = {name}')
                else:
                    # TODO: probably a table of records.
                    #  Should such args be post-processed?
                    self.cx_out.append(f'inp["{name}"] = cursor.var(')
                    self.cx_out.append(f'    cx_Oracle.OBJECT,')
                    self.cx_out.append(f'    typename="{arg_ct}",')
                    self.cx_out.append(f')')

            # TODO: complex objects handling
            get_val = f'    out["{name}"] = inp["{name}"].getvalue()'

        else:
            self.cx_out.append(f'inp["{name}"] = cursor.var({cx_type})')
            get_val = f'    out["{name}"] = inp["{name}"].getvalue()'

        # self.cx_out.append(f'out["{name}"] = inp["{name}"]')
        self.py_body.append(get_val)

    def process_arguments(self):
        # In ORACLE, defaulted arguments may be placed at any position
        # In Python, we should place them at the end
        for arg in self.routine.sorted_arguments:
            generic_info = {
                'cx_type': CX_SIMPLE_TYPES.get(arg.data_type),
                'py_type': PY_SIMPLE_TYPES.get(arg.data_type, 'object'),
                'name': arg.name if not iskeyword(arg.name) else f'{arg.name}_',
            }

            if arg.in_out == 'in':
                self.process_in(arg, **generic_info)
            elif arg.in_out == 'out' and self.routine.type == 'function':
                self.process_function_out(arg, **generic_info)
            elif arg.in_out == 'out' and self.routine.type == 'procedure':
                self.process_procedure_out(arg, **generic_info)
            else:  # proc in/out
                self.process_in_out(arg, **generic_info)

        if self.routine.type == 'procedure':
            if self.cx_out:
                self.cx_proc_out_end = 'out = dict()'
                self.py_body.append('return out')
            else:
                self.py_body.append('return None')
        else:
            self.py_body.append('return out')

    def __repr__(self):
        name = self.py_name
        signature = self.FUNCTION_INDENT.join(self.py_def)

        body_template = self.FUNCTION_INDENT.join(self.py_body)

        cx_in = (
            self.STATEMENTS_INDENT.join(self.cx_in)
            or '# No IN pre-processing'
        )
        cx_out = (
            self.STATEMENTS_INDENT.join(self.cx_out)
            or '# No OUT pre-processing'
        )
        cx_func_result_end = (
            self.STATEMENTS_INDENT.join(self.cx_func_out_end)
            or '# No Function OUT post-processing'
        )

        body = body_template.format(
            cx_in=cx_in,
            cx_call_name=self.cx_call_name,
            cx_func_out=self.cx_func_out,
            cx_func_out_end=cx_func_result_end,
            cx_proc_out_end=self.cx_proc_out_end,
            cx_out=cx_out,
        )

        return self.TEMPLATE.format(name=name, signature=signature, body=body)
