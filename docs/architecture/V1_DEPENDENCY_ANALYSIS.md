# V1 의존성 분석 (V1 Dependency Analysis)

- 작업: P0-01 V1 Architecture Inventory & Data Flow Audit (READ-ONLY)
- 감사 대상 커밋: `df6547e`
- 작성일: 2026-10-15
- 표기: `CONFIRMED` / `INFERRED` / `UNVERIFIED`. 코드 경로는 `src/carver_quant/` 기준이다.
- 이 문서는 **분석과 대안 제시**만 한다. 해결 코드는 작성하지 않았고, 결정은 P0-02 ADR에서 내린다.

---

## 1. 모듈 간 의존성 개요

전체 import 그래프는 [V1_INVENTORY.md](V1_INVENTORY.md) §4에 있다. 요약하면 다음과 같다.

| 관찰 | 근거 | 확인 |
|---|---|---|
| 순환 import는 없다 | 34개 모듈의 `from carver_quant.X import`를 추출해 확인 | CONFIRMED |
| 의존 방향은 대체로 "기본 타입 → 계산 → 스텝 → 러너 → 분석"이다 | V1_INVENTORY §4 | CONFIRMED |
| 예외 1: `data_quality → system_backtest` (데이터 계층이 러너에 의존) | `data_quality.py:7-9` | CONFIRMED |
| 예외 2: `performance → portfolio_backtest` (분석 계층이 포트폴리오 결과 타입에 묶여 있음) | `performance.py:6-8` | CONFIRMED |
| 예외 3: `portfolio_backtest → system_backtest` (`PreparedEWMACBacktest`라는 *EWMAC 전용* 준비 타입을 포트폴리오 러너가 입력으로 받음) | `portfolio_backtest.py:19-21, 33-36` | CONFIRMED |
| 예외 4: `contract_ledger → roll` (`ContractTrade` 타입이 `roll.py`에 정의되어 있음) | `contract_ledger.py:1` | CONFIRMED |
| 공용 시장 데이터 타입이 여러 모듈에 흩어져 있다: `ContractQuote`는 `roll_execution.py:15-18`, `ExecutionMarketDay`는 `system_backtest.py:28-47`, `ContractPrice`/`RollEvent`는 `futures_data.py` | — | CONFIRMED |

---

## 2. 역방향 의존: `data_quality.py → system_backtest.ExecutionMarketDay`

### 2.1 import 목적과 의존 범위

| 항목 | 내용 | 근거 |
|---|---|---|
| import 구문 | `from carver_quant.system_backtest import ExecutionMarketDay` | `data_quality.py:7-9` (CONFIRMED) |
| 사용 위치 | `validate_execution_days`의 **타입 주석**에만 쓴다. 생성자 호출이나 `isinstance` 검사는 없다 | `data_quality.py:97-101` (CONFIRMED) |
| 실제로 읽는 필드 | `date`, `daily_cash_vol_target`, `commission_per_contract`, `fx_to_base`, `slippage_ticks`, `quotes`(그리고 그 안의 `ContractQuote.bid/ask`) | `data_quality.py:105-190` (CONFIRMED) |
| 읽지 않는 필드 | `margin_per_contract_base`. margin 값의 유한성과 음수 여부는 검증하지 않는다 (가드레일 계산 시점에만 검사, `risk_guardrail.py:76-88`) | CONFIRMED |
| 런타임 결합 | `data_quality`를 import하면 `system_backtest`가 함께 로드되고, 이어서 `contract_aware_backtest`, `research_pipeline`, `forecast`, `volatility`(pandas)까지 로드된다 | CONFIRMED (import 체인) |
| 순환 여부 | 현재는 없다. `system_backtest`와 그 하위 모듈 어느 것도 `data_quality`를 import하지 않는다. `data_quality`를 import하는 곳은 `portfolio_system_backtest`뿐이다 | CONFIRMED |

### 2.2 변경 전파 가능성

- `ExecutionMarketDay`의 필드 이름이나 의미가 바뀌면 `data_quality`, `system_backtest`, `portfolio_backtest`(`day.margin_per_contract_base`, `day.quotes`를 직접 읽음, `portfolio_backtest.py:100-115`), `backtest_manifest`(fingerprint payload에 그대로 직렬화됨, `backtest_manifest.py:476-479`)까지 함께 영향을 받는다 (CONFIRMED). fingerprint가 바뀐다는 것은 **재현성 기준값이 바뀐다**는 뜻이다.
- 앞으로 `system_backtest`가 입력 검증을 위해 `data_quality`를 import하게 되면 **순환이 생긴다** (INFERRED). 지금 구조는 이 방향의 개선을 막고 있다.
- Paper/Live 경로가 생기면 같은 시장 데이터 타입(quote, fx, 체결 파라미터)이 필요해진다. 그때 Live 코드가 `system_backtest`(백테스트 러너)를 import해야 하는 구조가 된다 (INFERRED). 이는 CLAUDE.md §4의 "Backtest/Paper/Live는 같은 계산 로직을 재사용하고 모드별 코드를 분리"한다는 방향과 맞지 않는다.

### 2.3 `ExecutionMarketDay`의 책임 혼합

`ExecutionMarketDay`(`system_backtest.py:28-47`)는 성격이 다른 세 종류의 값을 한 타입에 담는다 (CONFIRMED).

| 종류 | 필드 | 성격 |
|---|---|---|
| 시장 관측값 | `date`, `quotes`, `fx_to_base` | 외부 데이터. 시각과 출처가 필요함 |
| 거래 비용 가정 | `commission_per_contract`, `slippage_ticks` | 브로커·전략 설정 |
| 위험 파라미터 | `daily_cash_vol_target`, `margin_per_contract_base` | 계좌·거래소 설정. `daily_cash_vol_target`은 포트폴리오 동적 모드에서 무시되고 덮어써짐 (`portfolio_backtest.py:428-433`) |

### 2.4 데이터 모델 분리 대안 (코드 작성 안 함)

| 대안 | 내용 | 장점 | 단점 / 위험 |
|---|---|---|---|
| **A. 공용 시장 데이터 모듈로 이동** | `ExecutionMarketDay`, `ContractQuote`(필요하면 `ContractPrice`, `RollEvent`까지)를 의존이 없는 모듈(예: `market_data.py`)로 옮긴다. 기존 위치에서는 재export해서 import 경로를 유지한다 | 변경이 가장 작다. 역방향 의존이 바로 사라진다. 기존 테스트의 import 경로를 유지할 수 있다 | 모듈 이동이므로 CLAUDE.md §5에 따라 승인이 필요하다. 책임 혼합(§2.3)은 그대로 남는다. 재export 경로가 두 개 공존하게 된다 |
| **B. 타입을 책임별로 분해** | 시장 관측(`quotes`, `fx`, 시각), 비용 가정(`commission`, `slippage`), 위험 파라미터(`vol target`, `margin`)를 각각 별도 타입으로 나누고, `ExecutionMarketDay`는 이들을 조합하는 호환용 타입으로 남긴다 | Paper/Live에서 시장 데이터 adapter와 설정을 깔끔하게 분리할 수 있다. 시각 필드를 추가하기 좋다 (GAP `F-02`) | 변경 범위가 넓다. manifest fingerprint 구조가 바뀌면 재현성 기준값이 바뀐다 (`backtest_manifest.py:476-479`) |
| **C. 검증기를 구조적 타입(Protocol)으로 변경** | `data_quality`가 구체 타입 대신 필요한 필드만 정의한 `Protocol`을 받게 한다. `backtest_manifest.py:34-46`의 `ManifestInstrumentInput`과 같은 방식이다 | import 의존이 사라진다. 이동하는 모듈이 없다. 런타임 동작이 바뀌지 않는다 | 타입 위치 문제(Live가 러너를 import하는 문제)는 해결되지 않는다. 정적 타입 검사기를 쓰지 않으면 이점이 작다 (현재 mypy 같은 도구는 설정되어 있지 않음, UNVERIFIED) |
| D. 현상 유지 + 규칙 문서화 | 지금 구조를 유지하고 "`system_backtest`는 `data_quality`를 import하지 않는다"는 규칙만 ADR에 남긴다 | 변경이 없다 | 근본 해결이 아니다. Paper/Live 단계에서 다시 다뤄야 한다 |

권고(INFERRED): P0-02에서 **A 또는 C를 단기안으로, B를 Paper Trading 설계 전의 목표 모델로** 결정하는 것이 위험 대비 효과가 크다. 어느 경우든 기존 306개 테스트는 import 경로를 바꾸지 않고 통과해야 한다.

---

## 3. 여러 백테스트 경로의 공존

### 3.1 경로 비교

| 비교 항목 | A. `backtest`/`daily_step` | B1. `roll_aware_daily_step` | B2. `contract_aware_backtest` | C. `system_backtest` | D. `portfolio_*` |
|---|---|---|---|---|---|
| 스텝 함수 | `run_daily_step` | `run_roll_aware_daily_step` | `run_contract_aware_daily_step` | B2와 같음 (러너도 B2) | B2 스텝을 직접 호출 |
| 날짜 | 없음 | 없음 | 없음 | 있음 (`day_dates`) | 있음 |
| 신호 생성 | 호출자 | 호출자 | 호출자 | 내부 (full 또는 PIT) | 내부 (항상 PIT) |
| t−1 정렬 | 호출자 | 호출자 | 호출자 | **내부 보장** | **내부 보장** |
| 월물 / roll | 없음 | 항상 roll | 선택 | 선택 | 선택 |
| FX | 없음 (1.0 고정) | 없음 | 있음 | 있음 | 있음 |
| 슬리피지 | 없음 | 없음 | 있음 | 있음 | 있음 |
| 버퍼링 | 없음 | 없음 | 스텝은 지원하지만 러너가 넘기지 않음 | 없음 | 있음 |
| 위험 예산 | 호출자 값 | 호출자 값 | 호출자 값 | 체결일 데이터 값 | legacy 또는 동적 (계좌 연동) |
| 가드레일 | 없음 | 없음 | 없음 | 없음 | 있음 (거래 후 검사, 예외로 중단) |
| 가격 연속성 검사 | 있음 `backtest.py:38-47` | 해당 없음 | 있음 `contract_aware_backtest.py:56-67` | B2 러너를 거치므로 있음 | **없음** |
| 데이터 검증 (`data_quality`) | 없음 | 없음 | 없음 | 없음 | 있음 `portfolio_system_backtest.py:106-116` |
| 성과 분석 | 불가 (결과 타입 불일치) | 불가 | 불가 | 불가 | `performance.py` |
| src 안의 호출자 | 없음 (테스트만) | 없음 (테스트만) | C | D (준비 단계) | 최상위 |

모두 CONFIRMED (코드 근거는 [V1_DATA_FLOW.md](V1_DATA_FLOW.md)).

### 3.2 공통으로 재사용하는 함수

다섯 경로 모두 아래 함수를 **같은 구현으로** 호출한다. 공식이 복제되어 있지 않다 (CONFIRMED).

- `pnl.calculate_gross_pnl`, `pnl.calculate_net_pnl`
- `account_ledger.update_account_value` (D는 계좌를 직접 합산 `portfolio_backtest.py:555-558`)
- `position.calculate_target_position` 계열과 `round_half_away_from_zero`
- `trade.calculate_trade_quantity`
- `execution.execute_market_order`와 `costs.calculate_total_trading_cost` (A는 직접, 나머지는 `roll_execution.execute_contract_trades`를 통해)

### 3.3 중복 구현 가능성이 있는 책임

| 책임 | 중복 위치 | 내용 | 확인 |
|---|---|---|---|
| 일간 회계 순서 (gross → target → trade → fill → cost → net → 계좌) | `daily_step.py:41-102`, `roll_aware_daily_step.py:73-127`, `contract_aware_daily_step.py:126-258` | 같은 순서를 세 번 손으로 구현함. 공식은 공유하지만 조립 코드는 복제되어 있음 | CONFIRMED |
| 날짜 루프 / 상태 전달 | `backtest.py:37-68`, `contract_aware_backtest.py:55-95`, `portfolio_backtest.py:284-634` | D는 B2 러너를 재사용하지 않고 루프를 다시 구현함. 그 결과 연속성 검사가 빠짐 | CONFIRMED |
| 일별 입력 조립 | `system_backtest.py:65-234`와 `:236-497` | full 경로와 PIT 경로가 거의 같은 루프를 따로 가짐 | CONFIRMED |
| 체결일 데이터 dict 구성과 중복 날짜 검사 | `system_backtest.py:80-88, 272-283`, `data_quality.py:106-109` | 같은 검사가 세 곳에 있음 | CONFIRMED |
| 가격 데이터 검증 | `futures_data.ContractPrice.__post_init__` `:12-17`, `data_quality.validate_contract_prices` `:12-45`, `build_back_adjusted_prices`의 중복 검사 `:57-64` | 같은 검사가 세 곳에 있음 | CONFIRMED |
| 롤 거래 생성 | `roll_aware_daily_step`과 `contract_aware_daily_step`이 모두 `generate_roll_and_rebalance_trades`를 씀. `generate_roll_trades`는 테스트에서만 씀 | 공유됨 (중복 아님) | CONFIRMED |
| 입력 payload 생성 | `backtest_manifest.py:405-517`와 `:519-631` | 같은 함수가 두 번 정의됨 | CONFIRMED |

### 3.4 입력 형식 차이

- A는 `BacktestDayInput`(날짜 없음, multiplier·tick이 일별 필드), B2/C는 `ContractAwareBacktestDayInput`(multiplier·tick은 `InstrumentSpec`에서 받음), D는 `PreparedEWMACBacktest` + `PortfolioSpec`이다 (CONFIRMED).
- 결과 타입도 `DailyStepResult`, `RollAwareDailyStepResult`, `ContractAwareDailyStepResult`, `PortfolioBacktestDayResult`로 모두 다르다. 그래서 성과 분석은 D에서만 쓸 수 있다 (CONFIRMED).

### 3.5 비용과 PnL 계산의 일관성

| 항목 | 일관성 | 근거 |
|---|---|---|
| gross PnL 공식 | 같음 | `pnl.py:4-36` 공유 |
| fx 적용 | **다름**. A와 B1은 fx를 넘기지 않아 1.0이 쓰임 | `daily_step.py:41-46, 86-92`, `roll_aware_daily_step.py:73-78, 103-110` |
| 슬리피지 | **다름**. A와 B1은 지원하지 않음 | 위와 같음 |
| 비용 분류 | **다름**. B1은 방향성 거래 비용을 0으로 두고 전부 roll 비용으로 집계함. B2는 둘을 구분하지 않고 `total_trading_cost` 하나로 집계함 | `roll_aware_daily_step.py:94, 112-117`, `contract_aware_daily_step.py:246-248` |
| 같은 날 같은 입력이면 B1과 B2(roll 지정)가 같은 총비용을 내는가 | 거래 생성 함수와 체결 함수가 같으므로 fx=1, 슬리피지=0이면 같을 것으로 보임 | INFERRED (비교 테스트 없음) |

### 3.6 앞으로 유지할 필요가 있는 호환 경로 (의견)

| 경로 | 권고 | 이유 |
|---|---|---|
| A (`backtest`/`daily_step`) | 손으로 계산한 기준 예제(reference test)로 **유지 검토** | `test_backtest_reproduces_manual_day_1_to_day_5` 같은 손계산 테스트의 기반이다. 운영 경로로는 쓰지 않음 (INFERRED) |
| B1 (`roll_aware_daily_step`) | **폐기 후보** (P0-02에서 결정) | B2가 기능을 모두 포함한다 (선택적 roll, fx, 슬리피지). src 호출자가 없다 |
| B2 (`contract_aware_*`) | **핵심으로 유지** | C와 D가 모두 이 스텝을 쓴다 |
| C (`system_backtest`) | 준비 단계는 유지. full-history 신호 경로의 위상은 결정 필요 | 최상위 경로(D)는 PIT만 쓴다. full 경로는 PnL 가격 시계열 생성에도 쓰인다 (`system_backtest.py:644-659`) |
| D (`portfolio_*`) | **운영 기준 경로** | 데이터 검증, PIT, 동적 위험 예산, 버퍼링, 가드레일, 성과, 재현성이 모두 연결된 유일한 경로다 |

이 표는 의견이다. "모든 경로를 하나로 합친다"는 결론을 전제로 하지 않았다.

### 3.7 통합할 때 기존 동작이 바뀔 위험

| 통합 시나리오 | 바뀔 수 있는 동작 | 영향받는 테스트 |
|---|---|---|
| D가 B2 러너(`run_contract_aware_backtest`)를 재사용 | 연속성 검사가 추가되어, 지금은 통과하던 입력이 실패할 수 있음. B2 러너에 buffer 인자를 추가해야 함 | `test_portfolio_backtest.py`, `test_portfolio_system_backtest.py`, `test_v1_acceptance.py` |
| A의 `daily_step`을 B2 스텝으로 대체 | A의 입력에 월물이 없어 adapter가 필요함. 비용 계산은 같을 것으로 보이지만 결과 타입이 다름 | `test_daily_step.py`, `test_backtest.py` (손계산 예제) |
| B1 제거 | 테스트 7개를 삭제해야 함. CLAUDE.md §5에 따라 승인 필요 | `test_roll_aware_daily_step.py` |
| full/PIT 준비 루프 통합 | PIT 경로는 연속 가격을 별도 시계열에서 찾는다. 통합하면서 이 분리가 깨지면 PnL이 왜곡됨 | `test_pit_replay_uses_pit_signal_but_continuous_price_for_pnl` |
| manifest payload 함수 중복 제거 | 본문이 같으므로 동작 변화 없음 (INFERRED) | `test_backtest_manifest.py` |
| `ExecutionMarketDay` 구조 변경 | 입력 fingerprint 값이 바뀜 | `test_backtest_manifest.py`, `test_backtest_result_bundle.py`, `test_v1_acceptance.py` |

---

## 4. ETF와 선물 지원 가능성

ETF 지원을 위해 구현을 바꾸지 않았다. 아래 내용은 현재 모델을 분석한 결과다.

### 4.1 데이터 모델별 판단

| 요소 | 현재 모델 | ETF에 그대로 쓸 수 있는가 | 판단 근거 |
|---|---|---|---|
| `InstrumentSpec` | symbol, currency, multiplier, tick_size `instrument.py:5-37` | **부분적으로 가능**. multiplier=1, tick_size=호가단위로 표현할 수 있음 | 자산 유형, 거래소, lot size, 공매도 가능 여부, 가격대별 호가단위가 없음. 일부 시장은 가격대마다 호가단위가 다르므로 고정 `tick_size` 하나로는 표현할 수 없음 (대상 시장의 규칙은 UNVERIFIED) |
| 포지션 수량 | `int` (계약 수 / 주 수) | **가능** | 주 단위 정수로 해석할 수 있음. 포지션 숫자가 커질 뿐 반올림 로직은 같음 |
| 포지션 사이징 공식 | vol 목표 ÷ (price vol × multiplier × fx) | **가능** | 자산 유형과 무관한 형태 (공식 수치 검증은 P0-04) |
| 시세 / 체결 객체 | `ContractQuote(bid, ask)`, `Fill(quantity, price)` | **가능** | 이름에 "Contract"가 붙어 있을 뿐 구조는 일반적임 |
| 월물 포지션 dict | `dict[월물, int]`, active 월물 하나 | 우회해서 가능 (월물 = 종목코드, roll 없음) | 개념이 맞지 않아 혼란스러움 (INFERRED) |
| 수수료 | 계약당 고정 `commission_per_contract` `costs.py:4-21` | **불가 (선물 전용)** | ETF는 보통 거래대금 비율(bps)과 최소 수수료 구조이고, 매도 시 세금이 붙을 수 있음 (대상 시장의 세율은 UNVERIFIED) |
| 스프레드·슬리피지 | mid 대비 체결가 비용, tick 단위 슬리피지 | **가능** | 구조가 일반적임 |
| FX | 일별 스칼라 | **가능** (해외 ETF) | 시점·출처 문제는 선물과 같음 |
| 가격 조정 | 가산 방식 roll back-adjustment `futures_data.py:47-179` | **불가 (선물 전용)** | ETF에는 분배금(배당)과 분할 조정이 필요하고, 보통 **곱셈 방식**임. 곱셈 조정은 상수 이동 불변성을 깨므로, full-history 경로에서는 look-ahead가 실제로 생김 (V1_DATA_FLOW §6, GAP `F-03`) |
| 변동성 | 가격 차이 기반 (pt/d) | 가능하지만 주의 필요 | 곱셈 조정된 가격에서는 가격 수준에 따라 vol 의미가 달라짐 (INFERRED) |
| Roll / 만기 | `RollEvent`, `roll.py`, `roll_execution.py` | **선물 전용**. ETF는 roll 이벤트 0건으로 우회 가능 | `roll_events=[]` 경로는 테스트됨 (`test_price_to_account_end_to_end`) |
| 계좌 회계 | 손익만 누적 (mark-to-market, 현금 이동 없음) | **부분적으로 가능** | ETF는 매수 대금이 현금에서 빠짐. 현금 부족으로 주문할 수 없는 상황, 미사용 현금 이자, 결제일(T+n)을 모델링하지 않음. 레버리지 1배 이하라면 손익 누적과 평가액이 같아지지만 **현금 제약을 검사하지 않음** (INFERRED) |
| Margin / Leverage 가드레일 | 거래소 증거금, gross leverage | 부분적으로 가능 | ETF는 증거금 대신 현금 100%가 필요함. gross leverage 한도(≤1.0)로 근사할 수 있음 (INFERRED) |
| 분배금 현금흐름 | 없음 | **없음** | 총수익(total return)을 계산하려면 필요함 |
| 공매도 | 음수 포지션을 그대로 허용 | 대상 시장 규칙에 따라 다름 | 공매도 제약 모델이 없음 (UNVERIFIED) |

### 4.2 공통 부분과 선물 전용 부분 정리

- **자산 유형과 무관하게 재사용할 수 있는 부분** (INFERRED): 변동성·forecast 계산(가격 시계열 입력만 맞으면), `position`, `buffering`, `portfolio`, `pnl`, `account_ledger`, `execution`의 체결가 결정, `costs`의 mid 대비 비용, `fx`, `performance`, manifest/fingerprint.
- **선물 전용 부분**: `futures_data`(가산 roll 조정), `roll`, `roll_execution`의 roll 의미, `contract_ledger`(월물별 장부), `contract_aware_daily_step`의 월물 상태 검증, 계약당 수수료, 증거금 기반 가드레일.
- **ETF에 새로 필요한 부분**: 가격 조정 방식 선택(곱셈·총수익), 비율 수수료와 세금, 현금 제약과 결제일, 분배금 현금흐름, 가격대별 호가단위(시장에 따라), 공매도 제약.

### 4.3 경계 문제

- `InstrumentSpec`을 확장할지, 자산 유형별로 타입을 나눌지 결정해야 한다 (P0-02).
- 비용 모델을 함수 하나에서 **교체 가능한 정책**으로 바꿀지 결정해야 한다. 지금은 `calculate_total_trading_cost`가 체결 함수 안에서 직접 호출된다 (`roll_execution.py:88-95`).
- 가격 조정 방식이 PIT 원칙과 직접 연결된다. 곱셈 조정을 도입하기 전에 PIT 경로를 기본으로 정해야 한다.

---

## 5. P0-02에서 결정해야 할 사항

| ID | 결정 사항 | 근거 문서 |
|---|---|---|
| D-01 | **공용 데이터 모델의 위치와 분해 방식**: `ExecutionMarketDay`, `ContractQuote`, `ContractPrice`, `RollEvent`를 어디에 둘지, 책임을 나눌지 (§2.4 대안 A~D) | 본 문서 §2 |
| D-02 | **운영 기준 백테스트 경로**를 지정하고, 나머지 경로의 위상(기준 예제 / 폐기 / 유지)을 정할 것 | §3.6 |
| D-03 | **체결 시점 모델**: 신호(t−1 종가) → 주문 → 체결(t일 어느 시각)을 정의하고, quote와 fx에 시각 필드를 둘지 | V1_DATA_FLOW §0, §6 |
| D-04 | **자산 유형 모델**: 선물과 ETF를 `InstrumentSpec` 하나로 표현할지, 별도 타입으로 나눌지. 비용 모델, 가격 조정 방식, 현금·증거금 회계를 어떻게 연결할지 | §4 |
| D-05 | **위험 가드레일의 의미**: 거래 후 예외로 중단하는 현재 방식 대신 거래 전 차단이나 축소를 할지. 일간 손실 한도와 drawdown 한도를 둘지. Backtest/Paper/Live에서 같은 구현을 공유할지 | GAP `F-04` |
| D-06 | **Warm-up 정책**: 최소 이력 길이를 설정으로 둘지. 이 결정은 P0-04의 수치 검증과 연결됨 | GAP `F-01` |
| D-07 | **다시장 달력 정렬 정책**: 휴장일이 다른 상품을 한 포트폴리오에서 어떻게 정렬할지 | GAP `A-06` |
| D-08 | **FX 데이터 모델**: 환율 시계열의 출처, 관측 시각, 수수료 통화 | V1_DATA_FLOW §6 |
| D-09 | **포지션 상태 모델**: 지금은 목표 포지션 = 새 포지션(전량 체결)이다 `contract_aware_daily_step.py:266`. Paper/Live에서 부분 체결과 미체결을 어떻게 반영할지 | GAP `A-07` |
| D-10 | **패키지 경계**: 하위 패키지 도입 여부, 계층 간 import 규칙(예: 데이터 계층 → 러너 금지), ADR 위치 | 본 문서 §1 |
| D-11 | **재현성 범위**: `code_version`을 Git과 연동할지, 데이터 vintage를 manifest에 포함할지 | GAP `A-09` |
| D-12 | **브로커·시장 Adapter 경계**: 시장과 브로커가 정해지지 않은 상태에서 인터페이스를 어디까지 미리 정할지 | CLAUDE.md §1, §4 |
