from abc import ABCMeta, abstractmethod
from logging import getLogger
from importlib import import_module
from typing import Iterator

from dbsg.lib.configuration import Configuration
from dbsg.lib.introspection import Introspection
from dbsg.lib.intermediate_representation import IR

LOG = getLogger(__name__)

REGISTRY = {}


class PluginMetaABC(ABCMeta):
    def __new__(mcs, name, bases, attrs):
        new = ABCMeta.__new__(mcs, name, bases, attrs)

        if not bases:
            return new

        if new.name() in REGISTRY:
            LOG.info(
                f'Skipping {name} ({new.name()}) registration. '
                f'A plugin with the same name is already in '
                f'REGISTRY: {REGISTRY[new.name()]}.'
            )
        else:
            REGISTRY[new.name()] = new

        return new


class PluginABC(metaclass=PluginMetaABC):
    configuration: Configuration = NotImplemented
    introspection: Introspection = NotImplemented
    ir: IR = NotImplemented

    @abstractmethod
    def save(self, **kwargs):
        """Implements Plugin's logic."""

    @classmethod
    @abstractmethod
    def name(cls):
        """Returns verbose name"""


class Handler:
    def __init__(
        self,
        configuration: Configuration,
        introspection: Introspection,
        ir: IR,
    ):
        # Preload all the standard plugins
        import_module('dbsg.plugins')

        self.configuration = configuration
        self.introspection = introspection
        self.ir = ir

    def __iter__(self) -> Iterator[PluginABC]:
        for name in self.configuration.plugins:
            if name not in REGISTRY:
                LOG.error(
                    f'The "{name}" plugin is not registered. Use '
                    f'{__name__}.PluginABC and your plugin will be '
                    f'registered automatically, or write a custom '
                    f'handler.'
                )
                continue

            plugin: PluginABC = REGISTRY[name](
                self.configuration,
                self.introspection,
                self.ir,
            )

            yield plugin
