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
| ADR (설계 결정 기록) | ADR-0001~0012 **ACCEPTED** (2026-10-16, 설계 원칙만 승인). **구현은 시작하지 않음** | `docs/adr/` (§7.1) |

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

> 아래는 **현재의 방향**이다. 논리 계층과 의존성 방향은 ACCEPTED [ADR-0004](docs/adr/0004-market-data-and-domain-boundaries.md)를 따른다. 물리적 배치는 ACCEPTED [ADR-0010](docs/adr/0010-physical-package-boundaries.md)의 원칙을 따른다: V1 모듈 34개는 현재 위치에 그대로 두고, 새 코드는 V1과 분리된 우산 하위 패키지(이름은 미정, 가칭 `carver_quant.lab`)에 둔다. 실제 패키지 생성과 모듈 이동은 별도 작업 명세와 승인 전에는 하지 않는다. 방향을 이유로 기존 구조를 바꾸지 않는다.
>
> 체결 시점과 손익 회계, warm-up과 거래 허용, 거래 전 위험 검사는 ACCEPTED ADR을 따른다: [ADR-0001](docs/adr/0001-execution-timing-and-valuation.md), [ADR-0002](docs/adr/0002-warmup-and-tradability.md), [ADR-0003](docs/adr/0003-pretrade-risk-policy.md). 데이터 경계, 백테스트 경로와 V1 호환, 선물·ETF 상품 모델은 [ADR-0004](docs/adr/0004-market-data-and-domain-boundaries.md), [ADR-0005](docs/adr/0005-backtest-paths-and-v1-compatibility.md), [ADR-0006](docs/adr/0006-futures-etf-instrument-model.md)을 따른다. 다시장 달력과 평가 시점, 다통화 NAV와 현금 원장, 주문·체결·포지션 생애주기는 [ADR-0007](docs/adr/0007-multi-market-calendar-and-valuation.md), [ADR-0008](docs/adr/0008-multi-currency-fx-accounting.md), [ADR-0009](docs/adr/0009-order-fill-and-position-lifecycle.md)을 따른다. 패키지 경계, 백테스트 재현성(golden master와 새 fingerprint), 브로커 Adapter 경계와 실패 처리는 [ADR-0010](docs/adr/0010-physical-package-boundaries.md), [ADR-0011](docs/adr/0011-backtest-reproducibility-and-schema-versioning.md), [ADR-0012](docs/adr/0012-broker-adapter-boundaries.md)을 따른다. 이 ADR들은 설계 원칙이며 아직 구현되지 않았다. 기존 V1 API는 현재 동작을 유지한다 (ADR-0001~0003 §8.0, ADR-0005).

- Python 중심 **Modular Monolith**
- **Functional Core / Imperative Shell**: 금융 계산은 부수효과 없는 순수 함수와 frozen dataclass로 작성하고, I/O·시간·브로커 호출은 바깥 계층에 둔다. 현재 `src/carver_quant/`에는 I/O, 현재 시각 조회, 난수 사용이 없다. 이 성질을 유지한다.
- 책임 분리: 데이터 / Forecast / Portfolio(사이징·위험) / Cost / Backtest / Execution
- 핵심 금융 계산 모듈에서 브로커 API를 직접 호출하지 않는다.
- Backtest, Paper, Live는 **같은 계산 로직**(forecast, 사이징, 비용, 가드레일)을 재사용한다. 모드별로 공식을 복제하지 않는다.
- 시장이나 브로커에 종속되는 기능은 **Adapter**로 분리한다.
- 실제 구조를 조사하기 전에는 대규모 디렉터리 개편을 하지 않는다. 현재 패키지는 하위 패키지 없는 평면 구조(`__init__.py` + 34개 모듈)다.

### 4.1 현재 구조와 방향 사이의 차이 (수정하지 말고 인지만 할 것)

- `data_quality.py`가 `system_backtest.ExecutionMarketDay`를 import한다. 데이터 계층이 백테스트 계층에 의존하는 역방향 의존이다. 해소 방향은 ADR-0004에서 승인되었지만, 방식(타입 이동 + 재export / 이동 없는 `TYPE_CHECKING`·`Protocol`)은 승인되지 않았다 (ADR-0004 Q4-1).
- 백테스트 경로가 여러 개 공존한다: `backtest.py`/`daily_step.py`(단일 상품) → `roll_aware_daily_step.py` → `contract_aware_*` → `system_backtest.py` → `portfolio_*`. ADR-0005에 따라 `run_combined_ewmac_portfolio_backtest`가 V1 기준 통합 진입점이고, 다섯 경로는 V1 재현·교육·비교 기준으로 보존한다. 기존 경로를 삭제하거나 새 엔진으로 재배선하지 않는다. 새 금융 기능은 새 연구 엔진(아직 없음)에만 넣는다.
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
- ACCEPTED ADR과 충돌하는 구현 (충돌이 필요하면 먼저 새 ADR을 제안하고 승인받는다)
- ADR의 Open Questions(한도 값, warm-up 길이, 체결 시각, FX 시점, 증거금 모델 등)를 임의로 정해 코드나 설정의 기본값으로 넣는 것

ADR이 승인되었다고 해서 그 내용을 바로 구현해도 된다는 뜻은 아니다. 실제 금융 코드 변경에는 **별도 작업 명세, 독립 수치 검증, 단위 테스트, 사용자 승인**이 각각 필요하다 (§3.2).

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
- 설계 결정은 ADR로 기록한다 (§7.1).
- 모든 감사·조사 결과는 다음 세 가지로 구분해 표시한다.
  - `CONFIRMED`: 코드나 실행 결과로 직접 확인함
  - `INFERRED`: 근거로부터 추론함
  - `UNVERIFIED`: 확인하지 못함
- 기존 코드 주석은 한국어로 되어 있다. 새 주석도 같은 스타일을 따른다.

### 7.1 ADR 관리 (2026-10-16 채택)

| 항목 | 규칙 |
|---|---|
| 위치 | `docs/adr/` |
| 파일 이름 | `NNNN-kebab-case-title.md`. 첫 번호 `0001`. 번호는 재사용하지 않는다 |
| 상태 | `PROPOSED` / `ACCEPTED` / `REJECTED` / `SUPERSEDED by NNNN`. **상태 변경은 사용자 승인으로만 한다** |
| 변경 | ACCEPTED ADR의 핵심 결정은 임의로 고치지 않는다. 결정을 바꾸려면 새 ADR로 대체한다. 오탈자, 링크, 명백한 문서 오류 수정은 허용하되 결정 내용은 바꾸지 않는다 |
| 기록 방식 | 확정된 정책과 미해결 세부사항(Open Questions)을 구분해서 쓴다. 승인 범위를 Status 절에 적는다 |

현재 ADR:

| ADR | 주제 | 상태 |
|---|---|---|
| [0001](docs/adr/0001-execution-timing-and-valuation.md) | 체결 시점과 손익 회계 (시점 계약, multi-instrument 회계, 이중 차감 금지) | ACCEPTED (정책 원칙) |
| [0002](docs/adr/0002-warmup-and-tradability.md) | Warm-up과 거래 허용 (Signal Eligibility, 프로필, LIVE fail-closed) | ACCEPTED (정책 원칙) |
| [0003](docs/adr/0003-pretrade-risk-policy.md) | 거래 전 위험 검사 (검증된 위험 축소, 포트폴리오 검사, Trading State, Kill Switch 제약) | ACCEPTED (정책 원칙) |
| [0004](docs/adr/0004-market-data-and-domain-boundaries.md) | 시장 데이터와 도메인 계층 경계 (도메인 계약 분리, 관측값·체결 가정·위험 입력 분리, 역방향 의존 금지, raw/조정 가격 구분, 관측·이용 가능 시각 구분, V1 재현성 보호) | ACCEPTED (설계 원칙) |
| [0005](docs/adr/0005-backtest-paths-and-v1-compatibility.md) | 백테스트 경로와 V1 호환 (V1 기준 진입점, 기존 경로 보존, 새 기능은 새 연구 엔진, 구조 변경 전 golden master 고정) | ACCEPTED (설계 원칙) |
| [0006](docs/adr/0006-futures-etf-instrument-model.md) | 선물·ETF 상품 모델 (Tagged Union + 합성, 상품 ID와 월물 ID 구분, 롤과 분배금·분할 분리, V1 `InstrumentSpec` 보호) | ACCEPTED (설계 원칙) |
| [0007](docs/adr/0007-multi-market-calendar-and-valuation.md) | 다시장 거래일과 평가 시점 (시각(instant) 기반 달력, UTC + IANA 타임존, 계좌 단위 일정, 상품별 데이터 상태 4종, 명시적 평가 정책, 주문 의도·제출·체결 가능 시각 구분) | ACCEPTED (설계 원칙) |
| [0008](docs/adr/0008-multi-currency-fx-accounting.md) | 다통화 FX와 현금 회계 (통화별 현금·자산, 기준통화 NAV와 분해 항등식, 통화별 현금 이벤트 원장, ADR-0001 `PnL[t]`를 거래 손익으로 유지, 수수료 정확히 한 번) | ACCEPTED (설계 원칙) |
| [0009](docs/adr/0009-order-fill-and-position-lifecycle.md) | 주문·체결·포지션 생애주기 (목표·실제·예상 포지션 분리, 주문 상태 11종, 체결 ID 멱등성과 동일성 검사, 정정 중 보수적 노출, `UNKNOWN` → `HALTED`) | ACCEPTED (설계 원칙) |
| [0010](docs/adr/0010-physical-package-boundaries.md) | 물리적 패키지 경계 (V1 모듈 보존, 새 코드는 분리된 우산 하위 패키지, 전부 이동 + shim 불채택, 계층·의존 규칙, 실주문 실행 경계 제한) | ACCEPTED (설계 원칙) |
| [0011](docs/adr/0011-backtest-reproducibility-and-schema-versioning.md) | 백테스트 재현성 (구조 변경 전 V1 golden, V1 인코더·fingerprint 불변, 새 schema·manifest와 구별되는 fingerprint, 데이터 내용을 반영한 입력 fingerprint, golden·금융 검증·차등 비교의 구분) | ACCEPTED (설계 원칙) |
| [0012](docs/adr/0012-broker-adapter-boundaries.md) | 브로커 Adapter 경계 (공통 port, 영속화 확인 후 전송, 쓰기 결과 4분류, 불명확 주문 자동 재제출 금지와 보수적 노출, 재시작 대조, 기능 검증 없는 Live 거부) | ACCEPTED (설계 원칙) |

- **ACCEPTED는 설계 원칙의 승인이다.** 구현 완료, 금융 계산의 정확성 검증, Live Trading 준비 완료를 뜻하지 않는다. ADR-0001~0012 모두 아직 구현되지 않았다. 구현에는 §5의 별도 작업 명세, 독립 수치 검증, 단위 테스트, 사용자 승인이 각각 필요하다.
- 미해결 금융 수치(한도, warm-up 길이, vol 하한)와 시장·브로커별 결정(체결 시각, 평가가격, FX 시점, 증거금 모델, 복구 절차)은 각 ADR의 Open Questions로 남아 있다. 요약은 [P0-02A_DECISION_SUMMARY.md](docs/architecture/P0-02A_DECISION_SUMMARY.md), [P0-02B_DECISION_SUMMARY.md](docs/architecture/P0-02B_DECISION_SUMMARY.md), [P0-02C1_DECISION_SUMMARY.md](docs/architecture/P0-02C1_DECISION_SUMMARY.md), [P0-02C2_DECISION_SUMMARY.md](docs/architecture/P0-02C2_DECISION_SUMMARY.md)에 있다.
- ADR-0004~0006에서 **승인되지 않은 선택** (구현 전에 사용자 결정이 필요하다. 전체 목록은 P0-02B 요약 §0.2):
  - 역방향 의존을 없애는 방식: 타입 이동 + 재export / 이동 없는 `TYPE_CHECKING`·`Protocol` (ADR-0004 Q4-1)
  - 새 `RESEARCH` API에서 날짜별 위험 예산 직접 입력을 허용할지 (ADR-0004 Q4-7). `LIVE`에서는 결정 시점 계좌와 위험 목표를 쓴다
  - 첫 구현 자산 유형: 선물 / ETF / 동시 (ADR-0005 Q5-8, ADR-0006 Q6-1)
  - golden master 테스트의 저장 형식, 상세 범위, 구현 시점 (ADR-0005 Q5-4, Q5-9)
- ADR-0007~0009에서 **승인되지 않은 선택** (구현 전에 사용자 결정이 필요하다. 전체 목록은 P0-02C1 요약 §0.2):
  - 평가 기본값: 의사결정·평가 시각, `MISSING_DATA`·`MARKET_CLOSED` 처리 정책, 공표 전 평가, 신선도 임계값, 장 밖 주문 접수, 닫힌 시장의 주문 의도 처리 (ADR-0007 Q7-1~Q7-9)
  - R1의 수수료 통화 확장: 상품 통화와 다른 수수료 통화의 운영 처리, 수수료 환산 시각, 브로커 환전 수수료 (ADR-0008 F8-3, F8-4, Q8-11). ADR-0001의 잠정 가정(`κ_fee = 상품 통화`)과 Q1-4는 그대로다
  - NAV 분해의 보고 관례(Q8-3), FX 공급자·시각·결측 정책, 기준통화, 이자, 수익률 방식 (ADR-0008 Q8-1~Q8-10)
  - 실제 브로커 동작: 상태 대응, 정정 원자성과 수량 의미, 체결 ID 범위, 주문 유형, 롤 순서, timeout (ADR-0009 Q9-1~Q9-11, D-12)
- ADR-0010~0012에서 **승인되지 않은 선택** (구현 전에 사용자 결정이 필요하다. 전체 목록은 P0-02C2 요약 §0.2):
  - 패키지 의존 예외: `risk → accounting`(PK-2), 새 코어의 V1 공식 함수 재사용(PK-9)과 ADR-0001 §8.0 해석, `ports`·`app`의 계층 분류. ACCEPTED ADR-0004 §6.2 표와 다르므로 **승인 전 사용 금지** (ADR-0010 Q10-2, Q10-4). 패키지 이름(Q10-1), 타임존 데이터 의존성(Q10-7)
  - golden 구현 세부: 저장 형식, fixture 목록, 구현 시점, 갱신 절차, 환경 간·차등 비교 허용 오차, 새 인코더 수치 규칙, `content_hash` canonicalization (ADR-0011 Q11-1~Q11-11, ADR-0005 Q5-4, Q5-6, Q5-9)
  - 브로커 운영 정책: 브로커 선정, Live 필수 기능과 검증 수준, 저장소와 내구성, 비정상 재시작 정책, `UNKNOWN` 상한 축소 조건, 기준 시각 없는 브로커, NAV 미확정 시 계좌 전체 차단(BR-13), `order_submitted_at` 정의, 수동 재제출과 Kill Switch 복구 (ADR-0012 Q12-1~Q12-16)
- 새 ADR이 기존 ACCEPTED ADR과 충돌하면 조용히 덮어쓰지 않는다. 충돌을 명시하고, 기존 ADR을 대체하는 별도 결정(새 ADR, `SUPERSEDED by NNNN`)과 사용자 승인을 거친다. ADR-0008의 수수료 확장이 ADR-0001을 바꾸지 않는 것이 그 예다.
- V1 경로의 구조를 바꾸기 전에 V1 결과와 fingerprint를 golden master로 먼저 고정한다 (ADR-0005, ADR-0011). golden 테스트를 실제로 작성하는 것은 별도 작업 명세와 승인이 필요하다. golden은 V1의 현재 출력을 고정할 뿐, 그 값이 금융적으로 옳다는 것을 증명하지 않는다. golden 회귀, 독립 금융 검증, 차등 비교는 서로 다른 검증이며 서로를 대신하지 않는다 (ADR-0011).

## 8. 실전 거래 안전 (향후 구현 시 필수 요건)

현재는 Live 기능이 없다. 아래 항목은 Paper/Live를 설계할 때 반드시 충족해야 하는 요건이다.

- Live Trading은 **기본 비활성**이다. 명시적 설정과 사용자 승인이 있을 때만 활성화한다.
- Research 실행 권한과 Live 실행 권한(자격증명, 설정)을 분리한다.
- AI가 단독으로 전략을 실전으로 승격하지 않는다. 승격은 사용자가 결정한다.
- 주문 상태가 불명확하면(timeout, 응답 유실 등) **무조건 재주문하지 않는다**. 먼저 상태를 조회하고 대조한다.
- 주문, 체결, 계좌 상태를 브로커 기준으로 **Reconciliation**한다. 불일치가 있으면 신규 주문을 중단한다.
- 위험 한도(leverage, margin, 손실 한도 등)를 위반하면 신규 주문을 차단한다.
- Kill Switch와 복구 절차는 별도 문서로 설계한다. 구현 전 설계 승인이 필요하다.
