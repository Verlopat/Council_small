"""Safe, independent arithmetic checks for explicitly supplied expressions.

This checks the expression's arithmetic, NOT any unparsed natural-language claim.
No eval(), imports, arbitrary calls or model-generated Python execution.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass
from fractions import Fraction
import operator

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub,
           ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
           ast.Pow: operator.pow}

@dataclass(frozen=True)
class ArithmeticCheck:
    outcome: str
    actual: str | None
    expected: str
    scope: str
    limitation: str = "Only the explicit numeric expression was checked."

def calculate(expression: str) -> Fraction:
    if not isinstance(expression, str) or len(expression) > 250:
        raise ValueError("Expression too long or invalid")
    root = ast.parse(expression, mode="eval")

    def visit(node, depth=0) -> Fraction:
        if depth > 40:
            raise ValueError("Expression too deep")
        if isinstance(node, ast.Expression):
            return visit(node.body, depth + 1)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            if abs(node.value) > 10**12:
                raise ValueError("Integer operand too large")
            return Fraction(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = visit(node.operand, depth + 1)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            a, b = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, ast.Pow):
                if b.denominator != 1 or abs(b.numerator) > 32:
                    raise ValueError("Exponent not supported")
            if isinstance(node.op, (ast.Mod, ast.FloorDiv)):
                if a.denominator != 1 or b.denominator != 1:
                    raise ValueError("Modulo/floor division requires integers")
            if isinstance(node.op, ast.Div):
                if b == 0:
                    raise ZeroDivisionError()
                return a / b
            output = _BINARY[type(node.op)](a, b)
            if output.numerator.bit_length() > 4096 or output.denominator.bit_length() > 4096:
                raise ValueError("Intermediate result too large")
            return Fraction(output)
        raise ValueError("Unsupported arithmetic expression")
    return visit(root)

def check(expression: str, expected: int) -> ArithmeticCheck:
    if type(expected) is not int:
        raise TypeError("Expected result must be an integer")
    try:
        actual = calculate(expression)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return ArithmeticCheck("error", None, str(expected), expression)
    return ArithmeticCheck("pass" if actual == expected else "fail",
                           str(actual), str(expected), expression)
