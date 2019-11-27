=============
Configuration
=============

.. automodule:: dbsg.lib.configuration
    :members:
    :exclude-members:
      APPVersionLoggingFilter,
      DSNSchema,
      PoolSchema,
      SchemesSchema,
      DatabaseSchema,
      ConfigSchema,
    :show-inheritance:

.. class:: CommandLineInterface

    Bases: :py:class:`ArgumentParser <python:argparse.ArgumentParser>`

    DBSG CLI interface.

    An instance of :py:class:`ArgumentParser <python:argparse.ArgumentParser>`
    So, you can either inject your own instance of the class, or use
    add_argument method to add some custom arguments.

    .. method:: add_argument(...)

      Add new CLI argument.

      The reference can be found :py:meth:`here <python:argparse.ArgumentParser.add_argument>`
