"""utils used by the HangupsBot core"""
# coding: utf-8
# pylint: disable=unused-import
import importlib
import logging
import os
import unicodedata
import traceback

from parsers import simple_parse_to_segments, segment_to_html
from permamem import name_from_hangups_conversation

BASE_PATH = os.path.dirname(os.path.dirname(__file__)) + '/'

def print_to_logger(*args, **dummys):
    """redirect the input to a logger with the name of the last entry in stack

    Args:
        args: tuple with entrys of any type
        dummys: dict, print kwargs that are not used
    """
    caller = traceback.extract_stack()[-2]
    module = caller.filename.replace(BASE_PATH, '').replace('/', '.').replace(
        '.__init__.py', '').replace('.py', '')
    logging.getLogger('%s.%s()' % (module, caller.name)).info(*args)

def remove_accents(text):
    """remove accents from unicode text, allows east asian languages through"""
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')

def unicode_to_ascii(text):
    """Transliterate unicode characters to ASCII"""
    return unicodedata.normalize('NFKD',
                                 text).encode('ascii', 'ignore').decode()

def class_from_name(module_name, class_name):
    """adapted from http://stackoverflow.com/a/13808375

    Args:
        module_name: string, modulepath relative to the main script
        class_name: string, class name in the module

    Returns:
        Class, requested item

    Raises:
        ImportError: module not found or error on loading
        AttributeError: module has no class named class_name
    """
    module = importlib.import_module(module_name)
    return getattr(module, class_name)
