from dataclasses import dataclass, field
from typing import MutableSequence, Union, Optional

from dbsg.lib.configuration import FQDN
from dbsg.lib.introspection import (
    COMPLEX_TYPES,
    IntrospectionRow,
    Introspection,
)

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
    def last_argument(self) -> COMPLEX_TYPES:
        return self.arguments[-1]

    def dispatch_argument(self, argument: Argument):
        # NOTE: Data Level == 0 is handled at the Routine level
        # NOTE: Data Level < direct_child_data_level is handled by Parents

        # Child that should be lifted into desired Data Level
        if argument.data_level > self.direct_child_data_level:
            # In this context, last_argument is always a ComplexArgument
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
    def last_argument(self) -> Argument:
        return self.arguments[-1]

    def dispatch_argument(self, argument: Argument):
        # Data Level == 0 should be placed at the Top
        if argument.data_level == 0:
            self.arguments.append(argument)
        # Data Level > 0 is a guarantee that the Arg should be nested
        else:
            # In this context, last_argument is always a ComplexArgument
            self.last_argument.dispatch_argument(argument)


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


class Abstract:
    def __init__(self, introspection: Introspection):
        self.introspection = introspection

    def intermediate_representation(self) -> IR:
        intermediate_representation = []

        for introspected in self.introspection:
            database = Database(name=introspected.name)
            routine: Optional[Routine] = None  # None before first iteration
            oid = sid = None

            # Can be multi-threaded/processed later
            for schema in introspected.schemes:

                for row in schema.rows:
                    if row.data_type not in COMPLEX_TYPES:
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