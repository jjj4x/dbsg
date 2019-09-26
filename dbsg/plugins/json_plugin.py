from dataclasses import asdict
from json import dumps

from dbsg.lib.plugin import PluginABC


class Plugin(PluginABC):
    def __init__(self, path, ir, **kwargs):
        self.path = path
        self.ir = ir
        self.kwargs = kwargs or {
            'ensure_ascii': False,
            'indent': 4,
        }

    def save(self, **kwargs):
        kwargs = kwargs or self.kwargs
        path = self.path.absolute()
        path.mkdir(parents=True, exist_ok=True)
        for db in self.ir:
            data = dumps({db.name: asdict(db)}, **kwargs)
            (path / db.name).mkdir(exist_ok=True)
            file = path / db.name / f'{db.name}.json'
            with file.open('w', encoding='utf8') as fh:
                fh.write(str(data))
        return self.ir


JSONPlugin = Plugin
