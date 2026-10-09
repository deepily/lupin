#!/usr/bin/env python3
"""
Unit tests for cosa.repo.symindex.need_input: the stripped need-writer input.

Each test builds a throwaway package under tmp_path and asks for a member by its dotted id.
"""

import pytest

from cosa.repo.symindex import need_input as ni


MODULE_SOURCE = '''"""Module docstring that is not part of any member."""

import json


def parse_result_block( raw_text, strict=False ):
    """
    Parse the result block in raw_text, as parse_result_block does for every caller.

    Returns a dict, or None when strict is False and nothing is found.
    """
    data = json.loads( raw_text )
    if strict and not data: raise ValueError( "parse_result_block found nothing" )
    return data


class ResultBlockReader:
    """Reads a result block for the reader's owner."""

    def __init__( self, source_path ):
        self.source_path = source_path

    def read_block( self, limit=10 ):
        """Read up to limit lines from source_path."""
        with open( self.source_path ) as handle:
            return handle.readlines()[ :limit ]
'''


@pytest.fixture
def src_root( tmp_path ):
    """A src root holding pkg_alpha/sub_beta/mod_gamma.py."""
    pkg = tmp_path / "pkg_alpha" / "sub_beta"
    pkg.mkdir( parents=True )
    ( tmp_path / "pkg_alpha" / "__init__.py" ).write_text( "" )
    ( pkg / "__init__.py" ).write_text( "" )
    ( pkg / "mod_gamma.py" ).write_text( MODULE_SOURCE )
    return str( tmp_path )


FUNC_ID  = "pkg_alpha.sub_beta.mod_gamma.parse_result_block"
CLASS_ID = "pkg_alpha.sub_beta.mod_gamma.ResultBlockReader"
METH_ID  = "pkg_alpha.sub_beta.mod_gamma.ResultBlockReader.read_block"


def test_resolve_member_splits_module_from_qualname( src_root ):
    path, qualname = ni.resolve_member( METH_ID, src_root )
    assert path.endswith( "pkg_alpha/sub_beta/mod_gamma.py" )
    assert qualname == "ResultBlockReader.read_block"


def test_resolve_member_unknown_id_raises( src_root ):
    with pytest.raises( ValueError, match="no module file" ):
        ni.resolve_member( "pkg_alpha.nothing.here.fn", src_root )


def test_resolve_member_package_init( tmp_path ):
    pkg = tmp_path / "solo"
    pkg.mkdir()
    ( pkg / "__init__.py" ).write_text( "def helper():\n    return 1\n" )
    path, qualname = ni.resolve_member( "solo.helper", str( tmp_path ) )
    assert path.endswith( "solo/__init__.py" )
    assert qualname == "helper"


def test_kind_of_each_member( src_root ):
    assert ni.build_input( FUNC_ID, src_root ).kind  == "function"
    assert ni.build_input( METH_ID, src_root ).kind  == "method"
    assert ni.build_input( CLASS_ID, src_root ).kind == "class"


def test_missing_qualname_raises( src_root ):
    with pytest.raises( ValueError, match="not found" ):
        ni.build_input( "pkg_alpha.sub_beta.mod_gamma.ghost", src_root )


def test_function_input_has_no_own_name_or_param_names( src_root ):
    text = ni.build_input( FUNC_ID, src_root ).text
    assert "parse_result_block" not in text
    assert "raw_text" not in text
    assert "strict" not in text
    assert "NAME" in text and "ARG1" in text and "ARG2" in text


def test_function_input_keeps_behaviour( src_root ):
    text = ni.build_input( FUNC_ID, src_root ).text
    assert "json.loads" in text
    assert "ValueError" in text
    assert "Returns a dict" in text


def test_class_input_strips_class_method_and_params( src_root ):
    text = ni.build_input( CLASS_ID, src_root ).text
    for leaked in ( "ResultBlockReader", "read_block", "source_path", "limit", "mod_gamma", "sub_beta", "pkg_alpha" ):
        assert leaked not in text, leaked
    assert "CLASS" in text and "open(" in text


def test_method_input_strips_enclosing_class( src_root ):
    text = ni.build_input( METH_ID, src_root ).text
    assert "ResultBlockReader" not in text
    assert "read_block" not in text
    assert "source_path" not in text


def test_self_and_cls_are_not_replaced( src_root ):
    text = ni.build_input( METH_ID, src_root ).text
    assert "self" in text


def test_module_docstring_is_not_included( src_root ):
    assert "Module docstring" not in ni.build_input( FUNC_ID, src_root ).text


def test_longer_names_replaced_before_their_substrings( tmp_path ):
    pkg = tmp_path / "pk"
    pkg.mkdir()
    ( pkg / "__init__.py" ).write_text( "" )
    ( pkg / "m.py" ).write_text( "def run( item, item_count ):\n    return item + item_count\n" )
    result = ni.build_input( "pk.m.run", str( tmp_path ) )
    assert "item" not in result.text and "_count" not in result.text
    assert result.text.count( "ARG" ) == 4


def test_forbidden_names_lists_every_stripped_identifier( src_root ):
    result = ni.build_input( FUNC_ID, src_root )
    assert { "parse_result_block", "raw_text", "strict", "mod_gamma", "sub_beta", "pkg_alpha" } <= set( result.forbidden )


def test_real_member_from_the_tree_is_stripped():
    """A real sampled member read from the shipped source, not a hand-built one."""
    import os
    root   = os.environ[ "LUPIN_ROOT" ] + "/src"
    result = ni.build_input( "cosa.agents.tfe_to_cc.prompts.output_contract.parse_result_block", root )
    assert result.kind == "function"
    assert len( result.text ) > 50
    assert "parse_result_block" not in result.text
    assert result.forbidden, "stripping found no identifiers to remove"
