# Copyright: (c) 2026, Richard Lynch
# GNU General Public License v3.0+ (see https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
"""AnsiballZ ships a module with the module_utils FILES its imports name. `from <...>.module_utils
import name` is resolved as the submodule module_utils/name.py, and when that is a function defined
in module_utils/__init__.py the module fails on the target with "Could not find imported module
support code" -- while every in-process unit test passes, because Python resolves the attribute.
Found 2026-11-07 on the first live run of alertmanager_silence 1.1.0 (require_common). So every
module_utils import in a module must name a file (or import the package itself, by its own name)."""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

HERE = pathlib.Path(
    __file__
)  # not resolved: the collection may be a link into an ansible_collections tree
COLLECTION = HERE.parents[4]
ROOT = COLLECTION.parents[2]  # the ansible_collections/ tree these tests run in
MODULES = sorted((COLLECTION / "plugins" / "modules").glob("*.py"))
PREFIX = re.compile(
    r"^ansible_collections\.([a-z0-9_]+)\.([a-z0-9_]+)\.plugins\.module_utils(?:\.(.+))?$"
)


def _module_utils_dir(ns: str, coll: str) -> pathlib.Path:
    return ROOT / "ansible_collections" / ns / coll / "plugins" / "module_utils"


def _imports(path: pathlib.Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            m = PREFIX.match(node.module)
            if m:
                yield node.module, m.group(1), m.group(2), m.group(3), [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.endswith(".plugins"):
            # `from ansible_collections.<ns>.<coll>.plugins import module_utils [as x]`: the package.
            yield node.module, None, None, None, [a.name for a in node.names]


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_every_module_utils_import_names_a_file(module):
    for dotted, ns, coll, sub, names in _imports(module):
        if ns is None:
            assert names == ["module_utils"], f"{module.name}: `from {dotted} import {names}`"
            continue
        base = _module_utils_dir(ns, coll)
        if sub:
            target = base.joinpath(*sub.split("."))
            assert (
                target.with_suffix(".py").is_file() or (target / "__init__.py").is_file()
            ), f"{module.name}: {dotted} is not a module_utils file"
            continue
        # `from <...>.module_utils import X`: each X must be a submodule FILE, never a function.
        for name in names:
            target = base / name
            assert target.with_suffix(".py").is_file() or (target / "__init__.py").is_file(), (
                f"{module.name}: `from {dotted} import {name}` names an attribute of __init__.py, "
                "which AnsiballZ cannot ship; import a module_utils FILE by name instead"
            )
