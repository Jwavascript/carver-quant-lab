# CLAUDE.md — Carver Quant Lab

이 파일은 이 저장소에서 작업하는 Claude Code와 개발자가 지켜야 할 공통 규칙이다.
환경과 테스트의 세부 사항은 [docs/architecture/DEVELOPMENT_BASELINE.md](docs/architecture/DEVELOPMENT_BASELINE.md)와 [docs/quality/TEST_BASELINE.md](docs/quality/TEST_BASELINE.md)에 있다. 이 파일과 두 문서의 내용이 충돌하면 작업을 멈추고 보고한다.

---

## 1. 프로젝트 목적

- Robert Carver의 *Systematic Trading* 계열 원칙을 참고하는 **개인용 systematic trading platform**
- 단순 백테스트에 그치지 않고 Research → Paper Trading → 제한된 Live Trading까지 확장하는 것이 목표
- **현재 단계: Phase 0 — Architecture Baseline**
- 거래 시장과 브로커: **미정**
- 예상 자본: 2,000만~5,000만 원
- 운용 방식: 일간 신호(daily signal), 하루 1회 사용자 점검
- 위험 성향: 제한된 손실 허용 (limited loss tolerance)

## 2. 현재 상태: 구현 vs 계획

존재하지 않는 기능을 이미 있는 것처럼 쓰지 않는다. 아래 표가 현재 기준이다 (2026-10-15, 커밋 `258e564` 기준).

| 영역 | 상태 | 실제 위치 (`src/carver_quant/`) |
|---|---|---|
| 데이터: futures 가격, roll event, back-adjustment, point-in-time back-adjustment | 구현됨 | `futures_data.py`, `data_quality.py` |
| Forecast: EWMAC, forecast scaling/cap, 복합 trend forecast(FDM) | 구현됨 | `forecast.py`, `combined_forecast.py`, `volatility.py`, `research_pipeline.py` |
| 포지션 사이징, vol target, buffering | 구현됨 | `position.py`, `risk_target.py`, `portfolio.py`, `buffering.py` |
| 비용: commission, spread, slippage(tick 단위), FX 환산 | 구현됨 | `costs.py`, `execution.py`, `fx.py` |
| Roll 거래, contract ledger | 구현됨 | `roll.py`, `roll_execution.py`, `contract_ledger.py` |
| 백테스트: 단일 상품, contract-aware, 포트폴리오 | 구현됨 | `backtest.py`, `daily_step.py`, `roll_aware_daily_step.py`, `contract_aware_*.py`, `system_backtest.py`, `portfolio_*.py` |
| 위험 가드레일: gross leverage, margin usage | 구현됨 (백테스트 내부) | `risk_guardrail.py`, `backtest_config.py` |
| 성과 분석, 재현성 manifest·fingerprint | 구현됨 | `performance.py`, `backtest_manifest.py`, `backtest_result_bundle.py` |
| 실제 데이터 수집·저장 (파일, DB, 외부 API) | **없음** | — 모든 입력은 호출자가 메모리 객체로 넘김 |
| Paper Trading, Live Trading, 브로커 Adapter | **없음** | — |
| 주문 상태 관리, Reconciliation, Kill Switch | **없음** | — |
| Survivorship bias 처리 | **없음** | — |
| ADR | **없음** | P0-02에서 작성 예정 |

`execution.py`의 `execute_market_order`는 **시뮬레이션 체결**이다. 실제 주문 기능이 아니다.

## 3. 금융 정확성 규칙

### 3.1 빠뜨리거나 임의로 가정하면 안 되는 항목

변경 작업이 아래 항목에 영향을 줄 수 있다면 영향 여부를 반드시 명시한다. 값을 모르면 기본값을 지어내지 말고 질문한다.

| 항목 | 현재 처리 (확인 수준) |
|---|---|
| Look-ahead Bias | point-in-time back-adjustment(`build_back_adjusted_prices_as_of`)와 PIT signal 경로가 있음 (CONFIRMED: 코드 존재) |
| 신호 계산 시점 vs 주문 시점 | 전일(t−1) signal로 당일(t) bid/ask에서 체결 (CONFIRMED: `system_backtest.py` 루프) |
| 거래 수수료 (Commission) | 계약당 commission (CONFIRMED) |
| Bid-Ask Spread | `ContractQuote` bid/ask, `calculate_spread_cost` (CONFIRMED) |
| Slippage | 정수 tick 단위 `slippage_ticks`, 기본값 0 (CONFIRMED). 기본값 0은 낙관적 가정이므로 결과 보고 시 명시한다 |
| Contract Multiplier / Tick Size | `InstrumentSpec.multiplier`, `tick_size`, `validate_price_on_tick` (CONFIRMED) |
| Currency 및 FX | 일별 스칼라 `fx_to_base`, 기본값 1.0 (CONFIRMED). 환율 시계열의 출처와 시점 정합성은 미정 |
| Position Rounding | `round_half_away_from_zero` (CONFIRMED) |
| Futures Expiry 및 Roll | roll event 입력 기반 (CONFIRMED). 만기일 일정은 자동 생성하지 않음 |
| Margin 및 Leverage | `PortfolioRiskPolicy` (max gross leverage, max margin usage) (CONFIRMED) |
| Missing Data | 가격이나 quote가 없으면 `ValueError`로 즉시 실패(fail-fast) (CONFIRMED). 보간하지 않음 |
| Survivorship Bias | 처리 없음 (CONFIRMED: 관련 코드 없음) |
| 데이터 수정·오류 가능성 | `data_quality.py` 검증만 있음. 데이터 버전(vintage) 관리는 없음 |

### 3.2 금융 공식 작성 규칙

- 모든 금융 공식(새로 만들거나 수정하는 것)에는 **입력, 출력, 단위, 전제조건, 예외조건**을 명시한다. 단위 예: 가격 포인트, 통화, 계약 수, 연율/일율, %, 소수.
- 금융 공식을 변경할 때는 다음 두 가지가 필요하다.
  1. 구현과 **독립적인 기준 계산**(손으로 계산한 숫자 예제 또는 별도 스크립트)
  2. 그 숫자를 검증하는 **단위 테스트**
- `pytest.approx`의 허용 오차는 근거 없이 넓히지 않는다.
- 잘못된 입력에는 `ValueError`로 즉시 실패하는 기존 관례를 따른다. NaN이나 0을 조용히 대입하지 않는다.

## 4. 아키텍처 방향 (잠정)

> 아래는 **현재의 방향**이다. 최종 결정은 P0-02 ADR에서 확정한다. ADR이 나오기 전에는 방향을 이유로 기존 구조를 바꾸지 않는다.

- Python 중심 **Modular Monolith**
- **Functional Core / Imperative Shell**: 금융 계산은 부수효과 없는 순수 함수와 frozen dataclass로 작성하고, I/O·시간·브로커 호출은 바깥 계층에 둔다. 현재 `src/carver_quant/`에는 I/O, 현재 시각 조회, 난수 사용이 없다. 이 성질을 유지한다.
- 책임 분리: 데이터 / Forecast / Portfolio(사이징·위험) / Cost / Backtest / Execution
- 핵심 금융 계산 모듈에서 브로커 API를 직접 호출하지 않는다.
- Backtest, Paper, Live는 **같은 계산 로직**(forecast, 사이징, 비용, 가드레일)을 재사용한다. 모드별로 공식을 복제하지 않는다.
- 시장이나 브로커에 종속되는 기능은 **Adapter**로 분리한다.
- 실제 구조를 조사하기 전에는 대규모 디렉터리 개편을 하지 않는다. 현재 패키지는 하위 패키지 없는 평면 구조(`__init__.py` + 34개 모듈)다.

### 4.1 현재 구조와 방향 사이의 차이 (수정하지 말고 인지만 할 것)

- `data_quality.py`가 `system_backtest.ExecutionMarketDay`를 import한다. 데이터 계층이 백테스트 계층에 의존하는 역방향 의존이다.
- 백테스트 경로가 여러 개 공존한다: `backtest.py`/`daily_step.py`(단일 상품) → `roll_aware_daily_step.py` → `contract_aware_*` → `system_backtest.py` → `portfolio_*`. 공통 로직 재사용 원칙과의 정합성은 P0-02에서 검토한다.
- 책임 분리는 모듈 이름 수준에서만 이루어져 있다. 하위 패키지 경계는 없다.
- 기존 코드에는 docstring이 전혀 없다 (§3.2 규칙과의 차이). 기존 함수에 docstring을 일괄 추가하는 작업은 별도 승인을 받은 뒤에 한다.

## 5. 작업 절차

모든 작업은 다음 순서를 따른다.

1. 기존 코드와 테스트 조사
2. 작업 명세와 변경 범위 확인 (모호하면 질문)
3. 금융적 영향과 위험 식별 (§3.1 표 기준)
4. 필요한 테스트를 먼저 작성
5. 최소 범위 구현
6. 전체 회귀 테스트 (`python -m pytest -q -W error`)
7. 변경 파일 목록, 테스트 결과, 미검증 사항 보고

### 명시적 승인 없이 하지 않는 것

- 금융 계산 공식 변경 (상수 변경 포함. 예: `AFTS_EWMAC_SCALARS`, `AFTS_TREND_RULE_SETS`, forecast cap 20)
- 기존 테스트 삭제 또는 약화 (assert 제거, 허용 오차 확대, skip/xfail 추가)
- 대규모 리팩터링, 모듈 이동이나 이름 변경
- 실전 브로커 주문 기능 활성화
- 전략의 자동 실전 배포
- API 키나 계좌 비밀정보를 코드, 테스트, 로그, 문서, 커밋에 저장
- `git push --force`, `git reset --hard`, 미커밋 변경 폐기, 기존 파일 삭제
- `pyproject.toml`의 `requires-python` 변경, 의존성 범위 확대

작업 명세에 다음 단계로 넘어가지 말라는 지시가 있으면, 해당 작업에서 멈추고 보고한다.

## 6. 테스트와 환경

| 항목 | 기준 |
|---|---|
| Python | 3.14 (`requires-python = ">=3.14"`) |
| 검증된 환경 | Android Termux (aarch64), Python 3.14.6, pandas 3.0.6, pytest 9.1.1 |
| 설치 | `python -m pip install -e ".[test]"` (저장소 루트의 `.venv/`) |
| Termux | 반드시 `python -m venv --system-site-packages .venv`로 만들고 `pkg install python-pandas` 필요 |
| 표준 테스트 | `python -m pytest -q` |
| 엄격 테스트 | `python -m pytest -q -W error` |
| 현재 기준 | **306 passed**, 경고 0 |
| 일반 Linux / CI | 미검증 |

- 테스트는 **프로젝트를 설치한 뒤** 실행한다. `PYTHONPATH=src` 방식은 표준이 아니다.
- 테스트 수가 306에서 바뀌면, 추가·삭제된 테스트와 그 이유를 보고한다.
- 테스트는 네트워크나 외부 파일에 의존하지 않는다. 이 성질을 유지한다.

## 7. 문서와 출처

- 금융 개념은 한국어로 쓰되 영어 원어를 병기한다. 예: 변동성 목표(volatility target), 예측 분산 승수(Forecast Diversification Multiplier, FDM).
- Carver 저서의 주장과 이 프로젝트의 자체 설계 제안을 구분해서 쓴다.
- 책의 페이지나 표를 직접 확인하지 못했다면 페이지 번호나 인용문을 추정해서 쓰지 않는다. 출처를 확인하지 못한 수치는 `UNVERIFIED`로 표시한다.
  - 현재 `forecast.py`의 `AFTS_EWMAC_SCALARS`와 `combined_forecast.py`의 `AFTS_TREND_RULE_SETS`(FDM)는 코드에 출처 표기가 없다. 원전과 대조하지 않았으므로 상태는 **UNVERIFIED**다.
- 구현 전에 입력, 출력, 전제조건, 예외조건, 인수 테스트를 먼저 정의한다.
- 설계 결정은 ADR로 기록한다. 위치는 P0-02에서 정한다.
- 모든 감사·조사 결과는 다음 세 가지로 구분해 표시한다.
  - `CONFIRMED`: 코드나 실행 결과로 직접 확인함
  - `INFERRED`: 근거로부터 추론함
  - `UNVERIFIED`: 확인하지 못함
- 기존 코드 주석은 한국어로 되어 있다. 새 주석도 같은 스타일을 따른다.

## 8. 실전 거래 안전 (향후 구현 시 필수 요건)

현재는 Live 기능이 없다. 아래 항목은 Paper/Live를 설계할 때 반드시 충족해야 하는 요건이다.

- Live Trading은 **기본 비활성**이다. 명시적 설정과 사용자 승인이 있을 때만 활성화한다.
- Research 실행 권한과 Live 실행 권한(자격증명, 설정)을 분리한다.
- AI가 단독으로 전략을 실전으로 승격하지 않는다. 승격은 사용자가 결정한다.
- 주문 상태가 불명확하면(timeout, 응답 유실 등) **무조건 재주문하지 않는다**. 먼저 상태를 조회하고 대조한다.
- 주문, 체결, 계좌 상태를 브로커 기준으로 **Reconciliation**한다. 불일치가 있으면 신규 주문을 중단한다.
- 위험 한도(leverage, margin, 손실 한도 등)를 위반하면 신규 주문을 차단한다.
- Kill Switch와 복구 절차는 별도 문서로 설계한다. 구현 전 설계 승인이 필요하다.
