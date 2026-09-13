"""Arithmetic evaluation as a standalone CLI, usable as a user-defined tool.

    python -m agentchat.tools.calculator "sqrt(2) * 3"

The obvious implementation — `python -c "import math; print({expression})"` — hands the model
a Python interpreter: `__import__("os").system(...)` is a valid "expression". The tool
executor deliberately does not sandbox commands (that elective was not chosen), so a preset
tool must not be the thing that opens the door.

So this parses the expression with `ast` and walks the tree, allowing only number literals,
arithmetic operators and a fixed table of `math` functions. Anything else — an attribute
access, a name that is not in the table, a call to something that is not a listed function —
is refused before evaluation. Exponents are bounded too, since `9**9**9` is arithmetic that
never returns.

stdlib only: user tools are subprocesses, and adding a dependency for them is not worth it.
"""

from __future__ import annotations

import argparse
import ast
import math
import operator
import sys

MAX_EXPRESSION_CHARS = 500
MAX_EXPONENT = 1000  # 2**1000 is instant; 9**9**9 is not

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

_FUNCTIONS = {
    name: getattr(math, name)
    for name in (
        "sqrt",
        "exp",
        "log",
        "log2",
        "log10",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "sinh",
        "cosh",
        "tanh",
        "floor",
        "ceil",
        "fabs",
        "factorial",
        "gcd",
        "hypot",
        "degrees",
        "radians",
        "copysign",
        "fmod",
        "trunc",
        "dist",
        "perm",
        "comb",
    )
}
_FUNCTIONS.update(abs=abs, round=round, min=min, max=max, sum=sum, pow=pow)

_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf, "nan": math.nan}


class CalcError(ValueError):
    """The expression is outside what this calculator is willing to evaluate."""


def _eval(node: ast.AST) -> float | int:  # noqa: C901 — one branch per allowed node type; splitting it hides the allowlist
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalcError(f"only numbers are allowed, got {node.value!r}")
        return node.value
    if isinstance(node, ast.BinOp):
        op = _BINARY.get(type(node.op))
        if op is None:
            raise CalcError(f"operator {type(node.op).__name__} is not allowed")
        left, right = _eval(node.left), _eval(node.right)
        if op is operator.pow and abs(right) > MAX_EXPONENT:
            raise CalcError(f"exponent {right} exceeds the limit of {MAX_EXPONENT}")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARY.get(type(node.op))
        if op is None:
            raise CalcError(f"operator {type(node.op).__name__} is not allowed")
        return op(_eval(node.operand))
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise CalcError(f"unknown name {node.id!r}")
    if isinstance(node, ast.Call):
        # Only a bare `name(...)` call, so `math.__loader__...` and friends never resolve.
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise CalcError("only the built-in math functions may be called")
        if node.keywords:
            raise CalcError("keyword arguments are not supported")
        return _FUNCTIONS[node.func.id](*(_eval(a) for a in node.args))
    if isinstance(node, ast.Tuple):
        return tuple(_eval(e) for e in node.elts)  # so min(1, 2) style calls still compose
    raise CalcError(f"{type(node).__name__} is not allowed in an expression")


def evaluate(expression: str) -> float | int:
    """Evaluate an arithmetic expression, refusing anything that is not arithmetic."""
    expression = expression.strip()
    if not expression:
        raise CalcError("empty expression")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise CalcError(f"expression longer than {MAX_EXPRESSION_CHARS} characters")
    # `math.sqrt(2)` is what a model tends to write; the dotted form is not parsed, so accept
    # the prefix textually rather than allowing attribute access in the tree.
    expression = expression.replace("math.", "")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise CalcError(f"could not parse the expression: {e.msg}") from e
    return _eval(tree)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate an arithmetic expression exactly.")
    parser.add_argument("expression", nargs="*", help="the expression (also read from stdin)")
    ns = parser.parse_args(argv)

    text = " ".join(ns.expression).strip() or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
    try:
        print(evaluate(text))
    except CalcError as e:
        print(f"[error] {e}")
        return 1
    except (ArithmeticError, ValueError, TypeError) as e:
        print(f"[error] {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
