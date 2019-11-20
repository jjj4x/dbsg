"""Plugin utilities."""
from abc import ABCMeta, abstractmethod
from logging import getLogger
from importlib import import_module
from typing import Iterator

from dbsg.lib.configuration import Configuration
from dbsg.lib.introspection import Introspection
from dbsg.lib.intermediate_representation import IR

LOG = getLogger(__name__)

# WPS407 Found mutable module constant. It makes sense here.
REGISTRY = {}  # noqa: WPS407


class PluginMetaABC(ABCMeta):
    """
    Plugin Metaclass.

    Registers plugins for later aliasing.
    """

    # N804  first argument of a classmethod should be named 'cls'
    def __new__(mcs, name, bases, namespace, **kwargs):  # noqa: N804
        """Register all the unregistered plugins."""
        new = super().__new__(PluginMetaABC, name, bases, namespace, **kwargs)

        if not bases:
            return new

        if new.name() in REGISTRY:
            LOG.info(
                f'Skipping {name} ({new.name()}) registration. '
                + 'A plugin with the same name is already in '
                + f'REGISTRY: {REGISTRY[new.name()]}.'
            )
        else:
            REGISTRY[new.name()] = new

        return new


class PluginABC(metaclass=PluginMetaABC):
    """Plugin Interface."""

    configuration: Configuration = NotImplemented
    introspection: Introspection = NotImplemented
    ir: IR = NotImplemented

    @abstractmethod
    def save(self, **kwargs):
        """Implement Plugin's logic."""

    @classmethod
    @abstractmethod
    def name(cls):
        """Return verbose name."""


class Handler:
    """Default Plugin Handler."""

    def __init__(
        self,
        configuration: Configuration,
        introspection: Introspection,
        ir: IR,
    ):
        """Initialize Plugin Handler, preloading all the standard plugins."""
        # Preload all the standard plugins
        import_module('dbsg.plugins')

        self.configuration = configuration
        self.introspection = introspection
        self.ir = ir

    def __iter__(self) -> Iterator[PluginABC]:
        """
        Iterate over all the registered plugins.

        Log all the unregistered ones.
        """
        for name in self.configuration.plugins:
            if name not in REGISTRY:
                LOG.error(
                    f'The "{name}" plugin is not registered. Use '
                    + f'{__name__}.PluginABC and your plugin will be '
                    + 'registered automatically, or write a custom handler.'
                )
                continue

            plugin: PluginABC = REGISTRY[name](
                self.configuration,
                self.introspection,
                self.ir,
            )

            yield plugin
