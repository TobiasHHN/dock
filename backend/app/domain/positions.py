"""Fractional Indexes für `position` (L 1): Strings, die byteweise sortiert werden (`COLLATE "C"`).

Port des Verfahrens von `fractional-indexing` (Basis 62, Kopfzeichen `a`..`z` / `A`..`Z` für die Länge des
Ganzzahlteils). Das Frontend muss dasselbe Verfahren verwenden, damit beide Seiten gültige Positionen vergeben.
`between(a, b)` liefert einen Wert echt zwischen `a` und `b`; `None` heißt: kein Nachbar (Anfang bzw. Ende).
"""
from __future__ import annotations

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
SMALLEST_INTEGER = "A" + "0" * 26
INTEGER_ZERO = "a0"


def _midpoint(a: str, b: str | None) -> str:
    zero = DIGITS[0]
    if b is not None and a >= b:
        raise ValueError(f"{a} >= {b}")
    if a.endswith(zero) or (b is not None and b.endswith(zero)):
        raise ValueError("Position darf nicht auf 0 enden")
    if b is not None:
        n = 0
        while (a[n] if n < len(a) else zero) == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _midpoint(a[n:], b[n:])
    digit_a = DIGITS.index(a[0]) if a else 0
    digit_b = DIGITS.index(b[0]) if b is not None else len(DIGITS)
    if digit_b - digit_a > 1:
        return DIGITS[round(0.5 * (digit_a + digit_b))]
    if b is not None and len(b) > 1:
        return b[:1]
    return DIGITS[digit_a] + _midpoint(a[1:], None)


def _integer_length(head: str) -> int:
    if "a" <= head <= "z":
        return ord(head) - ord("a") + 2
    if "A" <= head <= "Z":
        return ord("Z") - ord(head) + 2
    raise ValueError(f"ungültige Position (Kopfzeichen {head!r})")


def _integer_part(key: str) -> str:
    length = _integer_length(key[0])
    if length > len(key):
        raise ValueError(f"ungültige Position {key!r}")
    return key[:length]


def _increment(x: str) -> str | None:
    head, digs = x[0], list(x[1:])
    carry = True
    for i in range(len(digs) - 1, -1, -1):
        if not carry:
            break
        d = DIGITS.index(digs[i]) + 1
        if d == len(DIGITS):
            digs[i] = DIGITS[0]
        else:
            digs[i] = DIGITS[d]
            carry = False
    if carry:
        if head == "Z":
            return "a" + DIGITS[0]
        if head == "z":
            return None
        head = chr(ord(head) + 1)
        if head > "a":
            digs.append(DIGITS[0])
        else:
            digs.pop()
    return head + "".join(digs)


def _decrement(x: str) -> str | None:
    head, digs = x[0], list(x[1:])
    borrow = True
    for i in range(len(digs) - 1, -1, -1):
        if not borrow:
            break
        d = DIGITS.index(digs[i]) - 1
        if d == -1:
            digs[i] = DIGITS[-1]
        else:
            digs[i] = DIGITS[d]
            borrow = False
    if borrow:
        if head == "a":
            return "Z" + DIGITS[-1]
        if head == "A":
            return None
        head = chr(ord(head) - 1)
        if head < "Z":
            digs.append(DIGITS[-1])
        else:
            digs.pop()
    return head + "".join(digs)


def between(a: str | None, b: str | None) -> str:
    """Position echt zwischen `a` und `b` (`None` = offenes Ende)."""
    if a is not None and b is not None and a >= b:
        raise ValueError(f"{a} >= {b}")
    if a is None and b is None:
        return INTEGER_ZERO
    if a is None:
        ib = _integer_part(b)
        fb = b[len(ib):]
        if ib == SMALLEST_INTEGER:
            return ib + _midpoint("", fb)
        if ib < b:
            return ib
        res = _decrement(ib)
        if res is None:
            raise ValueError("kann nicht verkleinert werden")
        return res
    if b is None:
        ia = _integer_part(a)
        fa = a[len(ia):]
        i = _increment(ia)
        return i if i is not None else ia + _midpoint(fa, None)
    ia, ib = _integer_part(a), _integer_part(b)
    fa, fb = a[len(ia):], b[len(ib):]
    if ia == ib:
        return ia + _midpoint(fa, fb)
    i = _increment(ia)
    if i is None:
        raise ValueError("kann nicht vergrößert werden")
    if i < b:
        return i
    return ia + _midpoint(fa, None)

