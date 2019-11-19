"""JSON plugin module."""
from dataclasses import asdict
from json import dumps

from dbsg.lib.plugin import PluginABC

REGISTRY_NAME = 'json'


class Plugin(PluginABC):
    """JSON plugin."""

    def __init__(self, configuration, introspection, ir, **kwargs):
        """Initialize JSON plugin."""
        self.configuration = configuration
        self.introspection = introspection
        self.ir = ir
        self.kwargs = kwargs or {
            'ensure_ascii': False,
            'indent': 4,
        }

    @classmethod
    def name(cls):
        """Alias in REGISTRY."""
        return REGISTRY_NAME

    def save(self, **kwargs):
        """Save JSON representation into an appropriate file."""
        kwargs = kwargs or self.kwargs
        path = self.configuration.path.absolute()
        path.mkdir(parents=True, exist_ok=True)
        for db in self.ir:
            data = dumps({db.name: asdict(db)}, **kwargs)
            (path / db.name).mkdir(exist_ok=True)
            file = path / db.name / f'{db.name}.json'
            with file.open('w', encoding='utf8') as fh:
                fh.write(str(data))


JSONPlugin = Plugin  # for direct imports
