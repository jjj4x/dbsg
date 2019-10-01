from dbsg.lib.configuration import Setup
from dbsg.lib.introspection import Inspect
from dbsg.lib.intermediate_representation import Abstract
from dbsg.lib.plugin import Handler


def main():
    configuration = Setup().configuration()
    introspection = Inspect(configuration).introspection()
    ir = Abstract(introspection).intermediate_representation()

    for plugin in Handler(configuration, introspection, ir):
        plugin.save()

    return 0


if __name__ == '__main__':
    main()
