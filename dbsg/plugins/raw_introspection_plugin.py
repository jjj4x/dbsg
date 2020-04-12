"""RAW Introspection module."""
from dataclasses import astuple
from json import dumps

from dbsg.lib.plugin import PluginABC

REGISTRY_NAME = 'raw-introspection'


class Plugin(PluginABC):
    """RAW Introspection plugin."""

    def __init__(self, configuration, introspection, ir, **kwargs):
        """Initialize RAW Introspection plugin."""
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
        """Save RAW Introspection representation into an appropriate file."""
        kwargs = kwargs or self.kwargs
        path = self.configuration.path.absolute()
        path.mkdir(parents=True, exist_ok=True)
        for db in self.introspection:
            json = {}
            name = db.name.lower()
            for schema in db.schemes:
                json[schema.name.lower()] = [astuple(r) for r in schema.rows]
            data = dumps(json, **kwargs)
            (path / name).mkdir(exist_ok=True)
            file = path / name / f'{name}_raw.json'
            with file.open('w', encoding='utf8') as fh:
                fh.write(data)


RAWIntrospectionPlugin = Plugin  # for direct imports
