# -*- coding: utf-8 -*-
#
# Configuration file for the Sphinx documentation builder.
#
# This file does only contain a selection of the most common options. For a
# full list see the documentation:
# http://www.sphinx-doc.org/en/master/config

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.

import collections
import os
import pathlib
import sys
import functools

import click
import docutils.nodes
from sphinx.errors import SphinxError
from sphinx.util import logging
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.abspath('.'))
sys.path.insert(0, os.path.abspath('..'))

from wildland.cli.cli_main import main as CMD_MAIN
import manhelper

# -- Project information -----------------------------------------------------

project = 'Wildland'
copyright = '2020, Invisible Things Lab'
author = 'Invisible Things Lab'

# The short X.Y version
version = ''
# The full version, including alpha/beta/rc tags
release = ''


# -- General configuration ---------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
#
# needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.doctest',
    'sphinx.ext.intersphinx',
    # 'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
    'sphinx_autodoc_typehints',
    'sphinx.ext.todo',
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
#
# source_suffix = ['.rst', '.md']
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = None

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = None


rst_prolog = '''
.. |~| unicode:: 0xa0
   :trim:
'''

nitpicky = True
nitpick_ignore = [
    ('envvar', 'EDITOR'),
    ('envvar', 'VISUAL'),
    ('py:class', 'T'),
    ('py:class', 'click.core.Option'),
    ('py:class', 'fuse.Stat'),
]

todo_include_todos = True

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'alabaster'

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
#
# html_theme_options = {}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

# Custom sidebar templates, must be a dictionary that maps document names
# to template names.
#
# The default sidebars (for documents that don't match any pattern) are
# defined by theme itself.  Builtin themes are using these templates by
# default: ``['localtoc.html', 'relations.html', 'sourcelink.html',
# 'searchbox.html']``.
#
# html_sidebars = {}


# -- Options for HTMLHelp output ---------------------------------------------

# Output file base name for HTML help builder.
htmlhelp_basename = 'wildlanddoc'


# -- Options for LaTeX output ------------------------------------------------

latex_elements = {
    # The paper size ('letterpaper' or 'a4paper').
    #
    # 'papersize': 'letterpaper',

    # The font size ('10pt', '11pt' or '12pt').
    #
    # 'pointsize': '10pt',

    # Additional stuff for the LaTeX preamble.
    #
    # 'preamble': '',

    # Latex figure (float) alignment
    #
    # 'figure_align': 'htbp',
}

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (master_doc, 'wildland.tex', 'Wildland Documentation',
     'Invisible Things Lab', 'manual'),
]


# -- Options for manual page output ------------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [
    ('manpages/wl', 'wl', 'Wildland command-line interface', [author], 1),
    ('manpages/wl-container', 'wl-container', 'Container management', [author], 1),
    ('manpages/wl-storage', 'wl-storage', 'Storage management', [author], 1),
    ('manpages/wl-user', 'wl-user', 'Wildland user management', [author], 1),

    ('manpages/wl-sign', 'wl-sign', 'Sign manifests', [author], 1),
    ('manpages/wl-verify', 'wl-verify', 'Verify signatures', [author], 1),
    ('manpages/wl-edit', 'wl-edit', 'Edit manifests', [author], 1),

    ('manpages/wl-start', 'wl-start', 'Mount the whole Wildland FUSE filesystem', [author], 1),
    ('manpages/wl-stop', 'wl-stop', 'Unmount the whole Wildland FUSE filesystem', [author], 1),
    ('manpages/wl-mount', 'wl-mount',
     'Mount the whole Wildland FUSE filesystem (renamed to start))', [author], 1),

    ('manpages/wl-get', 'wl-get', 'Get a file from wildland', [author], 1),
    ('manpages/wl-put', 'wl-put', 'Put a file into wildland', [author], 1),
]

# what should be documented:
cnt_subcommands = collections.Counter(
    f'manpages/wl-{subcmd}'
    for subcmd in CMD_MAIN.commands
)
cnt_subcommands['manpages/wl'] = 1
cnt_man_pages = collections.Counter(source
    for source, *_ in man_pages)
cnt_man_sources = collections.Counter(str(p.with_suffix(''))
    for p in pathlib.Path().glob('manpages/*.rst')
    if not p.stem == 'index')

# barf if something is wrong:
assert cnt_man_pages == cnt_man_sources, (
    'mismatch files vs man_pages in conf.py: '
    f'{set(cnt_man_pages).symmetric_difference(cnt_man_sources)}')
assert cnt_subcommands == cnt_man_pages, ('under- or overdocumented commands: '
    f'{set(cnt_subcommands).symmetric_difference(cnt_man_pages)}')

class ManpageCheckVisitor(docutils.nodes.SparseNodeVisitor):
    def __init__(self, doctree, command, command_options, command_refids):
        super().__init__(doctree)
        self.stem = command
        self.command_options = command_options
        self.command_refids = command_refids

        self.current_command = None

    def visit_target(self, node):
        try:
            refid = node['refid']
        except KeyError:
            return
        log.debug('target refid=%s self.stem=%r', refid, self.stem)
        if refid.startswith(self.stem):
            try:
                self.current_command = self.command_refids[refid]
            except KeyError:
                raise SphinxError(f'invalid command: {refid}')

            self.command_options.discard((self.current_command, None))

    def visit_desc(self, node):
        if node.get('desctype') != 'option':
            raise docutils.nodes.SkipChildren()

    def visit_desc_name(self, node):
        opt = str(node[0])
        try:
            self.command_options.remove((self.current_command, opt))
        except KeyError:
            raise SphinxError(
                f'invalid or double-documented option {opt} '
                f'for command {self.current_command.name}')

def _collect_cmd_opts(cmd, prefix):
    yield (cmd, None)
    for param in cmd.params:
        if not isinstance(param, click.Option):
            continue
        for opt in (*param.opts, *param.secondary_opts):
            yield (cmd, opt)

def _collect_refids(cmd, prefix):
    yield ('-'.join((*prefix, cmd.name)), cmd)

def check_man(app, env):
    command_options = set(manhelper.walk_group(CMD_MAIN, _collect_cmd_opts))
    command_refids = dict(manhelper.walk_group(CMD_MAIN, _collect_refids))

    for docname in env.found_docs:
        log.info('docname: %r', docname)
        dirname, command = os.path.split(docname)
        if dirname != 'manpages':
            continue
        doctree = env.get_doctree(docname)

        log.info('checking manpage for %s', command)
        doctree.walk(ManpageCheckVisitor(doctree,
            command, command_options, command_refids))

    if command_options:
        for cmd, opt in command_options:
            if opt is None:
                log.info('undocumented command %s (%s)',
                    cmd.name, _describe_command(cmd))
            else:
                log.info('undocumented option %s for command %s (%s)',
                    opt, cmd.name, _describe_command(cmd))
        log.warn('undocumented options and/or commands')

def _describe_command(cmd):
    callback = cmd.callback

    if isinstance(callback, functools.partial):
        callback = callback.func

    while callback.__code__.co_filename.endswith('/click/decorators.py'):
        try:
            callback = callback.__wrapped__
        except AttributeError:
            # functools.wraps not used to create decorator; while theoretically
            # possible, click authors won't make such mistake, so this shouldn't
            # happen; trying to guess by introspecting __code__ and __closure__
            # is not worth the effort in this unlikely case
            break

    return f'{callback.__code__.co_filename}:{callback.__code__.co_firstlineno}'

# -- Options for Texinfo output ----------------------------------------------

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (master_doc, 'wildland', 'Wildland Documentation',
     author, 'wildland', 'One line description of project.',
     'Miscellaneous'),
]


# -- Options for Epub output -------------------------------------------------

# Bibliographic Dublin Core info.
epub_title = project

# The unique identifier of the text. This can be a ISBN number
# or the project homepage.
#
# epub_identifier = ''

# A unique identification for the text.
#
# epub_uid = ''

# A list of files that should not be packed into the epub file.
epub_exclude_files = ['search.html']


# -- Extension configuration -------------------------------------------------

# -- Options for intersphinx extension ---------------------------------------

# Example configuration for intersphinx: refer to the Python standard library.
intersphinx_mapping = {'https://docs.python.org/': None}


def setup(app):
    app.connect('env-check-consistency', check_man)
