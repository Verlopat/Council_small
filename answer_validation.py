"""Conservative formatting checks for known-answer smoke tests.

This is NOT a semantic or factual correctness judge.
"""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import re
from council.final_answers import extract_final_answer

NUMBER = r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?'


def _number(value: str):
    """Exact decimal and fraction comparison without float rounding."""
    try:
        pieces = value.replace(",", "").split("/")
        if len(pieces) == 1:
            return Fraction(Decimal(pieces[0]))
        if len(pieces) == 2:
            return Fraction(Decimal(pieces[0])) / Fraction(Decimal(pieces[1]))
    except (InvalidOperation, ZeroDivisionError, ValueError):
        pass
    return None


def matches_expected(response: str, expected: str) -> bool:
    """Accept simple final numeric answers even when formatted as a sentence.

    Examples: 156, 156.0, Answer: 156, The answer is **156**.,
    12 * 13 = 156. Do not accept an arbitrary mention of 156 in prose.
    """
    # Missing/empty model answers (including an abstaining vote6 baseline)
    # are incorrect, not a reason to abort the entire evaluation.
    if not isinstance(response, str) or not isinstance(expected, str):
        return False
    actual = response.strip()
    wanted = expected.strip()
    if not actual or not wanted:
        return False
    if actual == wanted:
        return True
    # Consistent with Council's candidate extraction: an explicitly labeled
    # final answer may be at the END of a sentence, not a separate line.
    scalar=extract_final_answer(actual)
    if wanted.lower() in {"yes","no","true","false"}:
        if scalar in {"yes","no","true","false"}:
            aliases={"true":"yes","yes":"yes","false":"no","no":"no"}
            return aliases[scalar]==aliases[wanted.lower()]
        # Symbolic truth tasks use an explicit terminal yes/no answer, not
        # arbitrary occurrences of "yes" somewhere in a proof.
        last=actual.splitlines()[-1].strip().replace("**","").strip()
        found=re.fullmatch(
            r"(?i)(?:(?:the\s+)?(?:final\s+)?answer\s*(?::|is|=)\s*)?"
            r"(yes|no|true|false)[.!]?",last)
        aliases={"true":"yes","yes":"yes","false":"no","no":"no"}
        return bool(found and aliases[found.group(1).lower()]==aliases[wanted.lower()])
    if wanted.casefold() in {"no solution", "no solution exists", "no solutions"}:
        return scalar == "no solution"
    if not (re.fullmatch(NUMBER, wanted) or
            re.fullmatch(rf"{NUMBER}\s*/\s*{NUMBER}", wanted)):
        return False
    if scalar is not None:
        return _number(scalar) is not None and _number(scalar) == _number(wanted)
    if not actual:
        return False

    final = actual.splitlines()[-1].strip()
    final = final.replace('**', '').replace(chr(96), '').strip()
    final = final.rstrip('.!').strip()
    if final.startswith(r'\boxed{') and final.endswith('}'):
        final = final[7:-1]

    number = None
    if re.fullmatch(NUMBER, final):
        number = final
    else:
        endings = (
            rf'(?i)(?:the\s+)?(?:final\s+)?(?:answer|result)\s*(?::|is|=)\s*({NUMBER})\Z',
            rf'(?i)(?:=|equals|is)\s*({NUMBER})\Z',
        )
        for pattern in endings:
            match = re.search(pattern, final)
            if match is not None:
                number = match.group(1)
                break

    if number is None:
        return False
    return _number(number) is not None and _number(number) == _number(wanted)
