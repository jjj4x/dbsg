==================
DB Stubs Generator
==================

DBSG is a CLI utility and backend libraries which can:
  * Introspect Oracle databases, schemas, and packages, looking for
    procedure and function signatures
  * Generate an intermediate representation using the introspection results
  * Serialize the representation into some final format.
    Currently, JSON and Python 3.7 code generation are supported

The final goal is the ability to generate Python stubs automatically,
so that they can be used to call corresponding DB routines right away,
without tonnes of manual boilerplate. For example:

.. code-block:: python

    class MyPackage(generic.Stub):
        def deactivate_client_bonus(
            self,
            *,
            username: str,
            manager: str,
            options: typing.Optional[typing.Mapping] = generic.DEFAULTED,
        ):
            inp = dict()
            cursor = self.cursor
            with cursor:
                inp["username"] = username
                inp["manager"] = manager
                if options is not generic.DEFAULTED:
                    inp["options"] = cursor.var(
                        cx_Oracle.OBJECT,
                        typename="MY_SCHEMA.MY_TYPES.OPTIONS_T",
                    ).type.newobject()
                    inp["options"].IN_TICKET = options["in_ticket"]
                    inp["options"].IN_QUEUE = options["in_queue"]
                    inp["options"].IN_DESCRIPTION = options["in_description"]
                # No OUT pre-processing
                cursor.callproc(
                   "MY_SCHEMA.MY_PACKAGE.DEACTIVATE_CLIENT_BONUS",
                   keywordParameters=inp,
                )

            return None

         ...  # some other routines


Installing
==========

Currently the project isn't hosted on PyPI, so use can install it
manually:

.. code-block:: text

    python3 setup.py install

The same but with `pip`:

.. code-block:: text

    pip3 install .  # setup.py should be in ./


A Simple Example
================

After installation, the `dbsg` CLI utility will be available:

.. code-block:: text

    dbsg --help

You can configure it, customizing the sample config:

.. code-block:: text

    mv config_sample.yml dbsg_config.yml
    cat dbsg_config.yml

.. code-block:: yaml

    ---
    path: stubs

    oracle_home: /opt/oracle/instantclient_18_3

    nls_lang: null

    abbreviation_files:
      - default_abbreviations.txt

    databases:
      - name: db_name
        pool:
          user: user
          password: pass
          threaded: true
          homogeneous: true
          min: 8
          max: 8
          encoding: UTF-8
          dsn:
            host: 127.0.0.1
            port: 1521
            sid: null
            service_name: some
        schemes:
          - name: billing

Call the `dbsg` with some working configuration:

.. code-block:: text

    LD_LIBRARY_PATH=/path/to/oracle/instantclient/lib dbsg --plugins json python3.7

The stubs (by default) will be placed under the ./stubs directory:

.. code-block:: text

    ls -l stubs

Each stub package inherits from the:

.. code-block:: python

    class Stub:
        def __init__(self, connection: cx_Oracle.Connection):
            self.connection = connection

        @property
        def cursor(self) -> cx_Oracle.Cursor:
            return self.connection.cursor()

The resulting stub routines will be under their stub packages. Some
of them may be procedures:

.. code-block:: python

    class BillingPackage(generic.Stub):
        def get_client_stats_bc(
            self,
            *,
            client: str,
        ):
            inp = dict()
            cursor = self.cursor
            with cursor:
                inp["in_client"] = in_login
                inp["out_price"] = cursor.var(cx_Oracle.NUMBER)
                inp["out_bc_date"] = cursor.var(cx_Oracle.DATETIME)
                inp["out_promised_payment_sum"] = cursor.var(cx_Oracle.NUMBER)
                inp["out_client_balance"] = cursor.var(cx_Oracle.NUMBER)
                cursor.callproc(
                   "MY_SCHEMA.BILLING_PACKAGE.GET_CLIENT_STATS_BC",
                   keywordParameters=inp,
                )
                out = dict()
                out["out_price"] = inp["out_price"].getvalue()
                out["out_bc_date"] = inp["out_bc_date"].getvalue()
                out["out_price_rounded"] = inp["out_price_rounded"].getvalue()
                out["out_promised_payment_sum"] = inp["out_promised_payment_sum"].getvalue()
                out["out_client_balance"] = inp["out_client_balance"].getvalue()
            return out

        ...  # some other routines

Others might be functions:

.. code-block:: python

    class BonusesPac(generic.Stub):
        def bp_bonuses(
            self,
            *,
            in_sum: float,
            in_discount: float,
            in_pay_day: datetime.datetime,
        ):
            inp = dict()
            cursor = self.cursor
            with cursor:
                inp["in_sum"] = in_sum
                inp["in_discount"] = in_discount
                inp["in_pay_day"] = in_pay_day
                # No OUT pre-processing
                out = cursor.callfunc(
                    "MY_SCHEMA.BONUS_PAC.BP_CHARGE_BONUSES_BY_PAYMENT_F",
                    cx_Oracle.NUMBER,
                    keywordParameters=inp,
                )
                # No Function OUT post-processing
            return out

        ...  # some other routines

You can use stubs in your code or tests. For example:

.. code-block:: python

    from datetime import datetime
    from unittest import TestCase, main

    from cx_Oracle import connect, makedsn

    from stubs.my_db.my_schema.bonuses_pac import BonusesPac


    class Tests(TestCase):
        def setUp(self):
            dsn = makedsn(
                'host',
                1521,
                'sid',
            )
            self.connection = connect('user', 'pass', dsn)

        def tearDown(self) -> None:
            self.connection.rollback()

        def test_bp_bonuses(self):
            pkg = BonusesPac(self.connection)
            result = pkg.bp_bonuses(
                in_sum=1000,
                in_discount=2000,
                in_pay_day=datetime.now(),
            )
            self.assertEqual(result, 100)


Warning
=======

The project is currently on its alpha stage.
