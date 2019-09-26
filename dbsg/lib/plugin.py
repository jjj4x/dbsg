from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from dbsg.lib.configuration import Configuration
from dbsg.lib.introspection import Introspection
from dbsg.lib.intermediate_representation import IR


class PluginABC(ABC):
    path: Optional[Path] = NotImplemented
    configuration: Optional[Configuration] = NotImplemented
    introspection: Optional[Introspection] = NotImplemented
    ir: IR = NotImplemented

    @abstractmethod
    def save(self, **kwargs) -> IR:
        """Implements Plugin's logic and returns Intermediate Representation"""
