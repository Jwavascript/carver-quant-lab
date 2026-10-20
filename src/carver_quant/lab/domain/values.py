"""Slice 1 값 검증: 정수 수량, Decimal 금액, UTC 시각, 식별자.

Slice 1 한정 규칙 (P0-03B-SLICE1, 전체 시스템의 수치·정규화 정책이 아니다):
- 수량은 int만 받는다. bool은 거부한다.
- 가격·금액·승수는 Decimal로 저장한다. 입력은 Decimal, int, 또는 ASCII 십진 리터럴 문자열(예: "101", "-0.25",
  "1.01E+2")만 받는다. float, 밑줄, 비ASCII 숫자, NaN·Infinity는 거부한다. int·Decimal 하위 클래스는 기본 타입으로 바꾼다.
- Decimal은 입력의 소수 자릿수(지수)를 보존한다 ("101.0"과 "101"은 구분됨). "+101", "0101"처럼 같은 계수·지수가 되는
  표기는 구분하지 않는다. 원본 응답 텍스트 보존은 이 Slice의 범위가 아니다 (원본 참조 형식은 ADR-0009 Q9-9).
  값 비교는 Decimal 수치 동일성이다 ("101", "101.0", "1.01E+2"는 같은 값). 반올림이나 허용 오차는 쓰지 않는다.
- 식별자는 정확한 str로 바꿔 저장한다 (str 하위 클래스를 그대로 담지 않음).

Slice 3: 현금·평가 계산은 `EXACT_DECIMAL_CONTEXT`를 쓴다 (trading_pnl의 문맥과 같은 설정).
"""

import re
from datetime import datetime, timedelta
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow

_DECIMAL_LITERAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")

# 덧셈·뺄셈·곱셈만 쓰는 금액 계산용 문맥. 정밀도 한계 없이 정확히 계산하고, 반올림이 생기면 Inexact로 즉시 실패한다.
EXACT_DECIMAL_CONTEXT = Context(
    prec=MAX_PREC,
    Emax=MAX_EMAX,
    Emin=MIN_EMIN,
    traps=[InvalidOperation, DivisionByZero, Overflow, Inexact],
)


def require_identifier(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a non-empty string without surrounding whitespace.")
    # str 하위 클래스의 비교·해시 재정의가 멱등 키나 비교 필드에 끼어들지 않게 정확한 str로 바꾼다.
    plain = str.__str__(value)
    if not plain or plain != plain.strip():
        raise ValueError(f"{name} must be a non-empty string without surrounding whitespace.")

    return plain


def require_optional_identifier(value: object, name: str) -> str | None:
    if value is None:
        return None

    return require_identifier(value, name)


def require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int (bool is not accepted).")

    return int(value)


def require_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{name} must not be a bool or float; use a decimal string or Decimal.")

    if isinstance(value, Decimal):
        result = Decimal(value)
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        if _DECIMAL_LITERAL.fullmatch(value) is None:
            raise ValueError(f"{name} must be an ASCII decimal literal such as '101' or '-0.25'.")
        result = Decimal(value)
    else:
        raise ValueError(f"{name} must be a Decimal, int, or decimal string.")

    if not result.is_finite():
        raise ValueError(f"{name} must be finite.")

    return result


def require_utc_instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")

    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be expressed in UTC.")

    return value
