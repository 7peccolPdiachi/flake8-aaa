import ast
import os
import re
from typing import List, Set

from asttokens.util import Token

test_file_pattern = re.compile(r'test(_.*|s)?\.py$')


def is_test_file(filename: str) -> bool:
    """
    Check that path to file being checked passed by flake8 looks like a pytest
    test file.
    """
    return bool(test_file_pattern.match(os.path.basename(filename)))


def first_non_blank_char(line: str) -> int:
    for pos, char in enumerate(line):
        if not char.isspace():
            return pos
    return 0


class TestFuncLister(ast.NodeVisitor):
    """
    Helper to walk the ast Tree and find functions that looks like tests.
    Matching function nodes are kept in ``_found_func`` attr.
    """

    def __init__(self, skip_noqa: bool):
        super(TestFuncLister, self).__init__()
        self.skip_noqa = skip_noqa
        self._found_funcs: List[ast.FunctionDef] = []

    def visit_FunctionDef(self, node):
        if node.name.startswith('test'):
            if not self.skip_noqa or not node.first_token.line.strip().endswith('# noqa'):
                self._found_funcs.append(node)

    def get_found_funcs(self) -> List[ast.FunctionDef]:
        return self._found_funcs


def find_test_functions(tree: ast.AST, skip_noqa: bool = False) -> List[ast.FunctionDef]:
    """
    Collect functions that look like tests.

    Args:
        tree
        skip_noqa: Flag used by command line debugger to skip functions that
            are marked with "# noqa". Defaults to ``False``.
    """
    function_finder = TestFuncLister(skip_noqa)
    function_finder.visit(tree)
    return function_finder.get_found_funcs()


def node_is_result_assignment(node: ast.AST) -> bool:
    """
    Args:
        node: An ``ast`` node.

    Returns:
        bool: ``node`` corresponds to the code ``result =``, assignment to the
        ``result `` variable.
    """
    if isinstance(node, ast.Assign):
        return len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "result"

    if isinstance(node, ast.AnnAssign):
        return node.target.id == "result"  # type: ignore

    return False


def node_is_pytest_raises(node: ast.AST) -> bool:
    """
    Args:
        node: An ``ast`` node, augmented with ASTTokens

    Returns:
        bool: ``node`` corresponds to a With node where the context manager is
        ``pytest.raises``.
    """
    return isinstance(node, ast.With) and get_first_token(node).line.strip().startswith('with pytest.raises')


def node_is_unittest_raises(node: ast.AST) -> bool:
    """
    ``node`` corresponds to a With node where the context manager is unittest's
    ``self.assertRaises``.
    """
    return isinstance(node, ast.With) and get_first_token(node).line.strip().startswith('with self.assertRaises')


def node_is_noop(node: ast.AST) -> bool:
    """
    Node does nothing.
    """
    return isinstance(node.value, ast.Str) if isinstance(node, ast.Expr) else isinstance(node, ast.Pass)


def function_is_noop(function_node: ast.FunctionDef) -> bool:
    """
    Function does nothing - is just ``pass`` or docstring.
    """
    return all(node_is_noop(n) for n in function_node.body)


def format_errors(num_errors: int) -> str:
    """
    Formats a Function's errors for command line use.
    """
    if num_errors == 1:
        return '    1 | ERROR\n'
    return ' {:>4} | ERRORS\n'.format(num_errors)


def get_first_token(node: ast.AST) -> Token:
    """
    Wrapper to solve typing errors. mypy complains that ``ast.AST`` has no
    property ``first_token`` or ``last_token``. That's because these are added
    by the asttokens library. For now, this ignoring of type, which I think is
    required to get mypy to pass at this time, is encapsulated in this helper
    function.
    """
    return node.first_token  # type: ignore


def get_last_token(node: ast.AST) -> Token:
    """
    Performs same purpose as get_first_token.
    """
    return node.last_token  # type: ignore


def add_node_parents(root: ast.AST) -> None:
    """
    Adds "parent" attribute to all child nodes of passed node.

    Code taken from https://stackoverflow.com/a/43311383/1286705
    """
    for node in ast.walk(root):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore


def build_footprint(node: ast.AST, first_line_no: int) -> Set[int]:
    """
    Generates a list of lines that the passed node covers, relative to the
    marked lines list - i.e. start of function is line 0.
    """
    return set(
        range(
            get_first_token(node).start[0] - first_line_no,
            get_last_token(node).end[0] - first_line_no + 1,
        )
    )


def filter_arrange_nodes(nodes: List[ast.stmt], max_line_number: int) -> List[ast.stmt]:
    """
    Finds all nodes that are before the ``max_line_number`` and are not
    docstrings or ``pass``.
    """
    return [
        node for node in nodes if node.lineno < max_line_number and not isinstance(node, ast.Pass)
        and not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Str))
    ]


def filter_assert_nodes(nodes: List[ast.stmt], min_line_number: int) -> List[ast.stmt]:
    """
    Finds all nodes that are after the ``min_line_number``
    """
    return [node for node in nodes if node.lineno > min_line_number]


class StringyLineVisitor(ast.NodeVisitor):
    """
    Find lines that look like strings. For each found, calculate its footprint.
    """

    def __init__(self, first_line_no: int):
        super().__init__()
        self.first_line_no: int = first_line_no
        self.footprints: Set[int] = set()

    def visit_Str(self, node) -> None:
        self.add_footprint(node)

    def visit_JoinedStr(self, node) -> None:
        self.add_footprint(node)

    def add_footprint(self, node) -> None:
        self.footprints.update(build_footprint(node, self.first_line_no))


def find_stringy_lines(tree: ast.AST, first_line_no: int) -> Set[int]:
    """
    Finds all lines that contain a string in a tree, usually a function. These
    lines will be ignored when searching for blank lines.

    JoinedStr can contain Str nodes and FormattedValue nodes - the inner nodes
    are not tokenised, so cause build_footprint() to raise AttributeErrors when
    it attempts to inspect the tokens on these nodes.

    See https://greentreesnakes.readthedocs.io/en/latest/nodes.html#JoinedStr
    """
    str_visitor = StringyLineVisitor(first_line_no)
    str_visitor.visit(tree)
    return str_visitor.footprints
