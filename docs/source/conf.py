from datetime import datetime
from email import message_from_string
from os import environ, path, sys

from pkg_resources import get_distribution


# ********************************META Settings********************************
DIST = get_distribution('db-stubs-generator')
META = message_from_string(DIST.get_metadata('METADATA'))
# ******************************************************************************


# *******************************Dynamic Settings*******************************
# on_rtd is whether we are on readthedocs.org
on_rtd = environ.get('READTHEDOCS', None) == 'True'

# Used to alter sphinx configuration for the Dash documentation build
dash_build = environ.get('DASHBUILD', False) == 'True'
# ******************************************************************************


# ********************************Path Settings********************************
# Include the root of the dbsg project
sys.path.insert(0, path.abspath('../..'))

# Path to custom themes
sys.path.append(path.abspath('_themes'))
# ******************************************************************************


# *******************************Sphinx Settings*******************************
# RST Reference:
# https://www.sphinx-doc.org/en/master/usage/restructuredtext/index.html
# Sphinx Configuration:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
# Sphinx Internationalization:
# https://www.sphinx-doc.org/en/master/usage/advanced/intl.html
# Sphinx Directives
# https://www.sphinx-doc.org/en/master/usage/restructuredtext/directives.html
# Sphinx Objects
# https://www.sphinx-doc.org/en/master/usage/restructuredtext/domains.html

version = DIST.version
release = version
author = META['Author']
project = META['Summary']
# noinspection PyShadowingBuiltins
copyright = f'{datetime.now().year}, {author}'

source_suffix = {
    '.rst': 'restructuredtext',
    '.txt': 'restructuredtext',
    '.md': 'markdown',
}

source_encoding = 'utf8'

master_doc = "index"

keep_warnings = True

# The default language to highlight source code in.
highlight_language = 'python3'

language = 'en'

html_theme = 'alabaster'

# ******************************************************************************


# **************************Sphinx Extensions Settings**************************
extensions = [
    # https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html
    'sphinx.ext.autodoc',
    # https://www.sphinx-doc.org/en/master/usage/extensions/viewcode.html
    'sphinx.ext.viewcode',
    # https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html
    'sphinx.ext.intersphinx',
    # https://www.sphinx-doc.org/en/master/usage/extensions/githubpages.html
    'sphinx.ext.githubpages',
]

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
}
# autodoc_default_options = {
#     # 'members': 'var1, var2',
#     # 'member-order': 'bysource',
#     # 'special-members': '__init__',
#     # 'undoc-members': True,
#     'exclude-members': [
#         'APPVersionLoggingFilter',
#     ],
# }

# ******************************************************************************


# Other:
# https://opensource.com/article/19/11/document-python-sphinx
# https://www.writethedocs.org/guide/
