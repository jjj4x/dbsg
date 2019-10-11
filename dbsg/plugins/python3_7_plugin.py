from keyword import iskeyword
from logging import getLogger
from re import compile
from typing import MutableSequence, Match

from dbsg.lib.configuration import Configuration
from dbsg.lib.intermediate_representation import Argument, Routine, Package
from dbsg.lib.plugin import PluginABC

LOG = getLogger(__name__)

REGISTRY_NAME = 'python3.7'

SNAKE_CASE = compile(r'^\w|_\w')
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


# noinspection PyShadowingBuiltins,DuplicatedCode
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

        self.cx_call_name = routine.fqdn
        self.cx_in = []
        self.cx_func_out = ''
        self.cx_func_out_end = []
        self.cx_proc_out = []

        # The calls have overhead, but have no side-effects
        self.process_arguments()

    def process_in(self, arg: Argument, **kwargs):
        name = kwargs['name']
        py_type = kwargs['py_type']

        if arg.data_type in CX_COMPLEX_TYPES:
            LOG.warning(kwargs['error'])
            self.errors.append(kwargs['error'])
            py_type = 'object'
            # TODO: cx_prepare IN or IN/OUT
            cx_type = kwargs['cx_type']

        if arg.defaulted:
            py_in = f'{name}: {py_type} = generic.DEFAULTED,'
            self.cx_in.append(f'if {name} is not generic.DEFAULTED:')
            self.cx_in.append(f'    inp["{name}"] = {name}')
        else:
            py_in = f'{name}: {py_type},'
            self.cx_in.append(f'inp["{name}"] = {name}')

        self.py_def.append(py_in)

        if '.' in py_type:
            module, *_ = py_type.split('.')
            self.imports.add(module)

    def process_function_out(self, arg: Argument, **kwargs):
        cx_type = kwargs['cx_type']

        if arg.data_type in CX_COMPLEX_TYPES:
            LOG.warning(kwargs['error'])
            self.errors.append(kwargs['error'])
            cx_type = 'generic.TBD'
            # TODO: cx_prepare OUT

        if arg.data_type == 'ref cursor':
            self.cx_func_out_end.append('result = result.fetchall()')

        self.cx_func_out = cx_type

    def process_procedure_out(self, arg: Argument, **kwargs):
        name = kwargs['name']
        cx_type = kwargs['cx_type']

        out = []
        if arg.data_type in CX_COMPLEX_TYPES:
            LOG.warning(kwargs['error'])
            self.errors.append(kwargs['error'])
            out.append(f'inp["{name}"] = generic.TBD')
            # TODO: cx_prepare OUT
        else:
            out.append(f'inp["{name}"] = cursor.var({cx_type})')

        out.append(f'out.append(inp["{name}"])')

        self.cx_proc_out.extend(out)

    def process_arguments(self):
        # In ORACLE, defaulted arguments may be placed at any position
        # In Python, we should place them at the end
        for arg in self.routine.sorted_arguments:
            name = arg.name if not iskeyword(arg.name) else f'{arg.name}_'
            generic_info = {
                'cx_type': CX_SIMPLE_TYPES.get(arg.data_type),
                'py_type': PY_SIMPLE_TYPES.get(arg.data_type),
                'name': name,
                'error': (
                    f'{self.routine.type.capitalize()} '
                    f'{self.py_name} ({self.cx_call_name}) has unsupported '
                    f'"{arg.in_out}" argument "{name}": {arg.data_type}'
                ),
            }

            if arg.in_out != 'out':  # IN or IN/OUT arg
                self.process_in(arg, **generic_info)
            elif self.routine.type == 'function':  # OUT arg and FUNCTION
                self.process_function_out(arg, **generic_info)
            else:  # OUT arg and PROCEDURE
                self.process_procedure_out(arg, **generic_info)

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
        signature = self.FUNCTION_INDENT.join(self.py_def)

        body_template = self.FUNCTION_INDENT.join(self.py_body)

        cx_in = self.STATEMENTS_INDENT.join(self.cx_in)
        cx_func_result_end = self.STATEMENTS_INDENT.join(self.cx_func_out_end)
        cx_proc_out = self.STATEMENTS_INDENT.join(self.cx_proc_out)

        body = body_template.format(
            cx_in=cx_in,
            cx_call_name=self.cx_call_name,
            cx_func_out=self.cx_func_out,
            cx_func_out_end=cx_func_result_end,
            cx_proc_out=cx_proc_out,
        )

        return self.TEMPLATE.format(name=name, signature=signature, body=body)
