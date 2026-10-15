# V1 갭 분석 (V1 Gap Analysis)

- 작업: P0-01 V1 Architecture Inventory & Data Flow Audit (READ-ONLY)
- 감사 대상 커밋: `df6547e`
- 작성일: 2026-10-15
- 관련 문서: [../architecture/V1_INVENTORY.md](../architecture/V1_INVENTORY.md), [../architecture/V1_DATA_FLOW.md](../architecture/V1_DATA_FLOW.md), [../architecture/V1_DEPENDENCY_ANALYSIS.md](../architecture/V1_DEPENDENCY_ANALYSIS.md)
- 코드 경로는 `src/carver_quant/` 기준이다.

이 문서는 **초기 위험 식별**이다. 공식의 수치가 맞는지는 판정하지 않았다. 금융 무결성의 최종 검증은 P0-04에서 한다. 이 감사에서 코드와 테스트는 수정하지 않았다.

---

## 0. 분류 기준

### 0.1 우선순위 (작업 명세 기준)

| 등급 | 의미 |
|---|---|
| P0 | 실전 거래나 금융 결과를 심각하게 왜곡할 수 있는 문제 |
| P1 | 아키텍처를 확장하기 전에 해결하거나 설계해야 하는 문제 |
| P2 | 유지보수성과 가독성 개선 문제 |
| P3 | 장기 개선 후보 |

### 0.2 심각도와 근거 확실성은 따로 표기한다

- **심각도**: High / Medium / Low. 문제가 실제로 발생했을 때 영향의 크기다.
- **확실성**:
  - `CONFIRMED`: 코드나 실행 결과로 확인함
  - `INFERRED`: 근거로부터 추론함
  - `UNVERIFIED`: 확인하지 못함

  메커니즘(코드가 실제로 그렇게 동작함)과 영향(결과가 왜곡됨)의 확실성이 다르면 둘 다 적는다.

### 0.3 감사 중 실행한 검증

| 검증 | 결과 |
|---|---|
| `python -m pytest -q -W error` (Windows 11, Python 3.14.7, pandas 3.0.5, pytest 9.1.1) | 306 passed, 경고 0 |
| side-effect grep (I/O, 시각, 난수, 네트워크) | 0건 |
| 일회성 probe 1: full-history와 PIT의 forecast 동일성 (roll 2회, 120일) | forecast 최대 차이 2.8e-13, vol 최대 차이 1.7e-15, adjusted 수준이 다른 날 80/120 |
| 일회성 probe 2: `run_roll_aware_daily_step`에 `roll_from == roll_to` 입력 | 거부하지 않음. 같은 월물에서 −5, +100 체결 (필요량은 95, 실제 거래량 105) |

probe 스크립트는 세션 scratchpad에만 두었고 저장소에는 추가하지 않았다.

---

## 1. 우선순위별 요약

| ID | 등급 | 심각도 | 확실성 | 제목 | 권장 단계 |
|---|---|---|---|---|---|
| F-01 | **P0** | High | 메커니즘 CONFIRMED / 영향 INFERRED | warm-up 정책이 없어 표본 2~3개로 vol을 추정하고 포지션을 정함 | P0-02 결정, P0-04 검증 |
| F-02 | **P0** | High | 메커니즘 CONFIRMED / 영향 INFERRED | 체결 시점이 정의되어 있지 않고, 체결가와 평가가격의 기준이 다름 | P0-02 결정, P0-04 검증 |
| F-03 | P1 | High (발생 시) | CONFIRMED (현재는 무해, probe) | full-history 신호 경로가 상수 이동 불변성에 우연히 의존함. 회귀 테스트 없음 | P0-04 |
| F-04 | P1 | High (Live) | CONFIRMED | 가드레일이 거래 후 예외로 중단하는 방식이고 포트폴리오 경로에만 있음. 손실 한도와 Kill Switch 없음 | P0-02 설계 |
| F-05 | P1 | Medium | CONFIRMED | 비용 기본값이 낙관적임 (슬리피지 0, 계약당 수수료만) | P0-04, 보고 규칙 |
| F-06 | P1 | Medium | UNVERIFIED (시점) | FX 스칼라 하나를 여러 시점에 겸용함. 수수료 통화 가정 | P0-02, P0-04 |
| F-07 | P1 | Medium | UNVERIFIED | roll event의 생성 규칙과 출처가 정의되어 있지 않음. 하루 전량 롤 | P0-02, Phase 1 |
| F-08 | P1 | Medium | CONFIRMED | 항상 전량 체결. 유동성과 부분 체결 모델 없음 | Phase 1 (Paper 설계) |
| F-09 | P1 | Medium | CONFIRMED | 금융 상수의 출처가 확인되지 않음 (scalar, FDM, 10, 0.7, 256 등) | P0-04 |
| F-10 | P1 | Medium | CONFIRMED (부재) | survivorship bias와 데이터 vintage 처리 없음 | Phase 1 |
| F-11 | P2 | Medium | CONFIRMED | legacy 위험 예산을 호출자가 공급함 (look-ahead 가능성) | P0-04 |
| F-12 | P2 | Medium | CONFIRMED | 계좌가 0 이하가 되어도 legacy 모드에서는 계속 진행됨 | P0-04 |
| F-13 | P2 | Low | CONFIRMED | 경로 A와 B1은 fx와 슬리피지를 무시함 | P0-02 (경로 위상 결정) |
| F-14 | P2 | Low | CONFIRMED (probe) | `roll_aware_daily_step`이 같은 월물로의 롤을 허용하고 방향성 비용을 0으로 둠 | P0-02 (폐기 여부) |
| F-15 | P3 | Low | CONFIRMED | 성과 지표 관례 (무위험수익률 0, 산술 연율화) | Phase 1 |
| A-01 | P1 | Medium | CONFIRMED | 역방향 의존 `data_quality → system_backtest` | P0-02 |
| A-02 | P1 | Medium | CONFIRMED | `ExecutionMarketDay`에 여러 책임이 섞여 있음 | P0-02 |
| A-03 | P1 | Medium | CONFIRMED | 백테스트 경로 다섯 개가 조립 코드를 중복 구현함 | P0-02 |
| A-06 | P1 | Medium | CONFIRMED | 다시장 달력 정렬 정책 없음 (날짜가 정확히 같아야 함) | P0-02 |
| A-07 | P1 | Medium | CONFIRMED | 포지션 상태 = 목표 포지션 (전량 체결 가정이 박혀 있음) | P0-02, Phase 1 |
| A-04 | P2 | Medium | CONFIRMED | `contract_aware_backtest`가 margin 필드를 조용히 무시하고 buffer를 전달할 수 없음 | P0-03 후보 |
| A-05 | P2 | Medium | 메커니즘 CONFIRMED / 발생 가능성 INFERRED (낮음) | 포트폴리오 러너에 가격 연속성 검사가 없음 | P0-03 후보 |
| A-08 | P2 | Low | CONFIRMED | 성과 분석이 포트폴리오 결과 타입에 묶여 있음 | P0-02 |
| A-09 | P2 | Medium | CONFIRMED | 재현성 범위가 제한적임 (code_version 수동, vintage 없음, 체결 내역 미포함) | P0-02 |
| A-10 | P2 | Low | INFERRED | PIT 신호를 O(n²)으로 재계산함 (긴 이력에서 성능 문제) | Phase 1 |
| A-11 | P2 | Low | CONFIRMED | 중복 정의, 실행되지 않는 코드, 자리채움 값 | P0-03 후보 |
| A-13 | P2 | Low | CONFIRMED | docstring과 공식 명세 없음 (CLAUDE.md §3.2와 차이) | 별도 승인 후 |
| A-12 | P3 | Low | CONFIRMED | 같은 검증이 여러 곳에 있고 서로 조금씩 다름 | P0-03 후보 |
| A-14 | P3 | Low | CONFIRMED | 느슨한 타입과 EWMAC 전용 이름의 범용 사용 | Phase 1 |
| A-15 | P3 | Low | CONFIRMED | IDM 상한 없음, 동일가중 고정, 거래일 256 고정 | Phase 1 |

P0-03의 범위는 저장소 문서에 정의되어 있지 않다 (UNVERIFIED). 이 문서에서 "P0-03 후보"는 *테스트 보강이나 저위험 정리 작업*을 잠정적으로 배정한 것이다.

---

## 2. 금융 무결성 위험 (F)

### F-01 [P0] warm-up 정책 부재

- **문제**: vol EWMA가 `min_periods=2`라서 **세 번째 관측일부터** vol이 생기고, 그날부터 forecast도 생긴다. slow EWMA(fast 64일 때 span 256)와 long-run vol(window 2560, `min_periods=1`)의 warm-up은 강제하지 않는다. 그래서 표본 2~3개로 추정한 vol로 위험 정규화와 포지션 사이징을 모두 한다.
- **근거 코드**: `volatility.py:65-75`, `volatility.py:173-176`, `forecast.py:190-206`, `system_backtest.py:115-121` (`None`만 건너뜀)
- **영향받는 기능**: forecast, 평균 포지션 (`position.py:88-91`: vol이 작을수록 포지션이 커짐), 시스템·포트폴리오 백테스트의 초기 구간, 그리고 앞으로 Live에서 새 상품을 추가할 때
- **발생 조건**: 이력이 짧은 상품, 백테스트 시작 직후, 초기 가격 변화가 우연히 작은 경우
- **현재 테스트**: 있음. 다만 **현재 동작을 고정하는 방향**이다. `tests/test_research_pipeline.py:60-84`는 index 2에서 forecast가 존재한다고 assert한다. 초기 포지션이 과대해지지 않는지 검사하는 테스트는 없다.
- **권장 단계**: P0-02에서 정책을 결정하고 (D-06), P0-04에서 수치를 검증한다.
- **수정 시 테스트 위험**: **High**. 6~8일짜리 짧은 시계열로 만든 다수 테스트(`test_system_backtest.py`, `test_combined_system_backtest.py`, `test_portfolio_*`, `test_v1_acceptance.py`)가 index 2부터 거래가 시작된다는 사실에 의존한다. warm-up을 바꾸려면 테스트 데이터를 다시 설계해야 하고, CLAUDE.md §5에 따라 승인이 필요하다.

### F-02 [P0] 체결 시점 미정의 / 체결가와 평가가격의 기준 불일치

- **문제**: (1) `ExecutionMarketDay.quotes`에는 관측 시각이 없다. (2) 당일 거래 수량은 당일 PnL에 반영되지 않고, 새 포지션은 *당일 adjusted 종가*부터 평가된다. 체결가는 mid 대비 비용으로만 반영된다. 따라서 **quote mid가 당일 종가와 같다는 가정이 숨어 있지만** 코드는 이를 검증하지 않는다. 테스트는 모두 mid를 종가에 맞춰 놓는다.
- **근거 코드**: `system_backtest.py:28-47`, `contract_aware_daily_step.py:126-132` (gross PnL), `roll_execution.py:84-95` (mid 대비 비용), `daily_step.py:82-92`. 테스트 예: `tests/test_system_backtest.py:164-275`
- **영향받는 기능**: 모든 PnL, 비용 측정, 백테스트와 Paper/Live 결과의 비교 가능성
- **발생 조건**: quote를 시가나 장중 가격으로 공급할 때. 운용 방식(전일 신호, 당일 장중 주문)을 그대로 백테스트에 넣으면 체결 시점과 평가 시점 사이의 손익이 누락되거나 왜곡된다 (INFERRED).
- **현재 테스트**: 없음 (mid와 종가가 다를 때의 동작이나 거부를 검사하는 테스트 없음)
- **권장 단계**: P0-02에서 체결 시점 모델을 결정하고 (D-03), P0-04에서 회계 등식을 검증한다.
- **수정 시 테스트 위험**: Medium. 검증만 추가한다면 기존 테스트는 대부분 통과할 것이다 (mid = 종가이므로, INFERRED). 회계 모델을 바꾸면 손계산 기대값이 전부 바뀐다.

### F-03 [P1] full-history 신호 경로가 상수 이동 불변성에 의존함

- **문제**: `build_ewmac_research_signals`와 `build_combined_ewmac_research_signals`는 미래 roll이 포함된 back-adjusted 시계열로 신호를 만든다. 현재 규칙(EWMA 차이, 가격 차이 기반 vol)은 상수 이동에 불변이라서 PIT 결과와 수치적으로 같다 (probe로 확인). 하지만 이 성질을 **보장하는 테스트가 없고**, 가격 수준에 의존하는 규칙이나 곱셈 조정(ETF)을 도입하면 즉시 look-ahead가 된다.
- **근거 코드**: `research_pipeline.py:48-52, 160-164`, `system_backtest.py:499-588`. 미래 roll이 과거 수준을 바꾸는 것을 보여 주는 테스트: `tests/test_futures_data.py:337` `test_offline_back_adjustment_can_revise_historical_levels`
- **영향받는 기능**: `prepare_ewmac_backtest`, `run_ewmac_system_backtest`, `prepare_combined_ewmac_backtest`. 최상위 포트폴리오 경로는 PIT를 쓰므로 해당하지 않는다 (`portfolio_system_backtest.py:136-156`, CONFIRMED).
- **발생 조건**: 새 규칙이나 새 가격 조정 방식을 추가할 때
- **현재 테스트**: 없음. full 경로의 미래 데이터 테스트(`test_future_raw_price_does_not_change_past_signals`, `test_future_price_does_not_change_past_combined_blended_signals`)는 모두 `roll_events=[]`이다.
- **권장 단계**: P0-04. full 경로와 PIT 경로의 동일성 테스트를 추가할지 검토한다.
- **수정 시 테스트 위험**: Low (테스트 추가만 필요)

### F-04 [P1] 위험 가드레일의 의미와 범위

- **문제**: `validate_risk_snapshot`은 한도를 넘으면 `ValueError`를 던지고 **백테스트 전체가 중단**된다. 거래를 막거나 줄이는 기능이 없고, 거래가 시뮬레이션된 *후에* 검사한다. 단일 상품 경로(A, B, C)에는 가드레일이 없다. 일간 손실 한도, drawdown 한도, Kill Switch도 없다.
- **근거 코드**: `risk_guardrail.py:188-210`, `portfolio_backtest.py:560-579`
- **영향받는 기능**: 위험 관리 전반. CLAUDE.md §8 요건("위험 한도를 위반하면 신규 주문을 차단한다")과 다르다.
- **발생 조건**: leverage나 margin 한도를 넘는 날
- **현재 테스트**: 있음. `test_portfolio_rejects_gross_leverage_limit_breach`, `test_portfolio_rejects_margin_usage_limit_breach`가 **중단 동작을 고정**하고 있다.
- **권장 단계**: P0-02 설계 (D-05). 구현은 Phase 1 이후
- **수정 시 테스트 위험**: Medium. 의미를 "차단"으로 바꾸면 위 두 테스트의 기대값이 바뀐다.

### F-05 [P1] 비용 기본값이 낙관적임

- **문제**: `slippage_ticks` 기본값이 0이다 (`execution.py:67`, `system_backtest.py:40`, `contract_aware_backtest.py:28`). 수수료는 계약당 고정이다. 스프레드는 입력 quote에 전적으로 의존하고, quote가 없을 때의 보수적 대체값은 없다. 경로 A와 B1은 슬리피지를 지원하지 않는다.
- **근거 코드**: 위 위치, `costs.py:4-21`
- **영향받는 기능**: 순손익, 회전율 판단
- **발생 조건**: 기본값으로 백테스트할 때
- **현재 테스트**: 슬리피지 1 tick 시나리오는 있다 (`test_full_10_day_acceptance_with_one_tick_slippage`). 기본값의 보수성에 대한 규칙은 없다.
- **권장 단계**: P0-04 (비용 가정 문서화). 결과를 보고할 때 "슬리피지 0"을 명시하는 규칙은 이미 CLAUDE.md §3.1에 있다.
- **수정 시 테스트 위험**: 기본값을 바꾸면 High. 다수의 손계산 기대값이 바뀐다.

### F-06 [P1] FX 시점과 수수료 통화

- **문제**: t일 `fx_to_base` 스칼라 하나를 t−1→t gross PnL 전체, t일 사이징, t일 비용, t일 가드레일 명목가치에 모두 쓴다. 환율의 관측 시각과 출처가 정의되어 있지 않다. 수수료는 상품 통화로 가정하고 fx로 환산한다.
- **근거 코드**: `contract_aware_daily_step.py:126-159, 235-244`, `costs.py:105-113`, `portfolio_backtest.py:129-136`
- **영향받는 기능**: 기준 통화 손익, 사이징
- **발생 조건**: 기준 통화와 상품 통화가 다를 때 (예: KRW 계좌로 USD 선물 거래)
- **현재 테스트**: KRW 기준통화와 일별 fx 시나리오가 있다 (`test_contract_aware_backtest_uses_krw_base_currency`, `test_contract_aware_backtest_uses_daily_fx_rate`). 시점 정합성 테스트는 없다.
- **권장 단계**: P0-02 (D-08), P0-04
- **수정 시 테스트 위험**: Medium

### F-07 [P1] roll event 출처와 롤 실행 방식

- **문제**: roll event는 외부 입력이다. 생성 규칙(만기 기준, 거래량 교차 등)과 그 정보를 언제 알 수 있는지가 정의되어 있지 않다. 롤은 roll일 하루에 전량을 같은 quote로 체결한다. 만기일 일정은 자동으로 만들지 않는다 (CLAUDE.md §3.1과 일치).
- **근거 코드**: `futures_data.py:20-36`, `system_backtest.py:145-154`, `roll.py:29-53`
- **영향받는 기능**: back-adjustment, roll 비용, 시점 무결성
- **발생 조건**: 사후 정보로 roll 날짜를 정한 데이터를 쓸 때 (look-ahead), 유동성이 얇은 날 전량 롤할 때
- **현재 테스트**: roll 경로의 기능 테스트는 많다. 출처와 시점 규칙은 코드 밖의 문제다.
- **권장 단계**: P0-02 (데이터 계약), Phase 1 (데이터 수집 설계)
- **수정 시 테스트 위험**: Low (문서와 계약 정의가 우선)

### F-08 [P1] 전량 체결 가정

- **문제**: `execute_market_order`는 항상 요청 수량 전체를 체결한다. 거래량과 유동성 제약, 부분 체결, 체결 실패 모델이 없다.
- **근거 코드**: `execution.py:106-109`
- **영향받는 기능**: Paper/Live 설계, 대량 거래 시 비용
- **발생 조건**: 포지션이 시장 유동성에 비해 클 때. 예상 자본(2,000만~5,000만 원)에서는 영향이 작을 것으로 보인다 (INFERRED).
- **현재 테스트**: 전량 체결을 가정한 테스트만 있다.
- **권장 단계**: Phase 1 (Paper Trading 설계)
- **수정 시 테스트 위험**: Medium

### F-09 [P1] 금융 상수의 출처 미확인

- **문제**: `AFTS_EWMAC_SCALARS`, `AFTS_TREND_RULE_SETS`, cap 20, 평균 forecast 10, slow/fast 비율 4, vol span 32, long-run window 2560, 단기 vol 가중치 0.7, 거래일 256, 버퍼 0.10에 출처 표기가 없다. 단기 vol 가중치 0.7은 결합 경로에서 하드코딩되어 있어 설정할 수 없다.
- **근거 코드**: [V1_INVENTORY.md](../architecture/V1_INVENTORY.md) §6, `research_pipeline.py:102`
- **영향받는 기능**: forecast 크기, 포지션 크기
- **발생 조건**: 항상
- **현재 테스트**: 값을 고정하는 테스트는 있다 (예: `test_afts_ewmac16_config`). 원전과 대조하는 테스트는 없다.
- **권장 단계**: P0-04 (원전 대조). 값을 바꾸려면 CLAUDE.md §5에 따라 승인이 필요하다.
- **수정 시 테스트 위험**: 값을 바꾸면 High

### F-10 [P1] Survivorship bias와 데이터 vintage

- **문제**: 상장폐지·거래 중단 상품을 처리하지 않는다. 데이터 수정 이력(vintage)을 관리하지 않는다. 데이터 검증은 형식 검증뿐이다 (`data_quality.py`).
- **근거 코드**: 관련 코드 없음 (CONFIRMED: 부재)
- **영향받는 기능**: 상품 유니버스 선택, 재현성
- **발생 조건**: 실제 데이터를 도입할 때
- **현재 테스트**: 없음
- **권장 단계**: Phase 1 (데이터 계층 설계)
- **수정 시 테스트 위험**: Low

### F-11 [P2] legacy 위험 예산을 호출자가 공급함

- **문제**: legacy 모드에서는 `ExecutionMarketDay.daily_cash_vol_target`을 호출자가 넣는다. 이 값을 미래 계좌로 계산했다면 look-ahead가 된다. 코드는 이 값의 출처를 검증할 수 없다. 동적 모드는 전일 종가 계좌를 쓰고 테스트로 확인된다 (`test_next_day_risk_target_uses_previous_closing_account`).
- **근거 코드**: `portfolio_backtest.py:321-386`, `system_backtest.py:168-171`
- **권장 단계**: P0-04. legacy 모드를 유지할지 P0-02에서 결정한다.
- **수정 시 테스트 위험**: legacy 모드를 제거하면 Medium

### F-12 [P2] 계좌가 0 이하일 때의 동작

- **문제**: `update_account_value`는 유한성만 검사한다 (`account_ledger.py:8-16`). 포트폴리오 동적 모드는 다음 날 `calculate_daily_cash_vol_target`에서 `capital <= 0`을 거부한다 (`risk_target.py:13-16`). legacy 모드는 risk_policy가 없으면 계좌가 음수여도 계속 거래한다.
- **근거 코드**: 위 위치, `portfolio_backtest.py:555-579`
- **권장 단계**: P0-04
- **수정 시 테스트 위험**: Low

### F-13 [P2] 경로 A와 B1은 fx와 슬리피지를 무시함

- **근거 코드**: `daily_step.py:41-46, 86-92`, `roll_aware_daily_step.py:73-78, 103-110`
- **영향**: 이 경로의 결과는 B2, C, D와 비교할 수 없다 (상품 통화와 기준 통화가 같고 슬리피지 0일 때만 비교 가능)
- **권장 단계**: P0-02 (경로 위상 결정 D-02)
- **수정 시 테스트 위험**: Low

### F-14 [P2] `roll_aware_daily_step`의 검증 누락과 비용 분류

- **문제**: `roll_from_contract == roll_to_contract`를 거부하지 않는다. probe에서 같은 월물에 −5, +100이 체결되었고, 필요량 95가 아니라 105를 거래해 비용이 과대 계상되었다. 방향성 거래 비용은 항상 0이다. `contract_aware_daily_step`은 같은 상황을 거부한다 (`contract_aware_daily_step.py:105-111`).
- **근거 코드**: `roll_aware_daily_step.py:65-71, 94-117`
- **현재 테스트**: 없음 (같은 월물로의 롤)
- **권장 단계**: P0-02 (B1 폐기 여부). 유지한다면 P0-03 후보로 검증을 추가한다.
- **수정 시 테스트 위험**: Low

### F-15 [P3] 성과 지표 관례

- **문제**: Sharpe에 무위험수익률을 반영하지 않는다. 연율 평균은 산술 평균 × 256이다. drawdown은 일별 종가 계좌로 계산한다.
- **근거 코드**: `performance.py:75-127, 130-170`
- **권장 단계**: Phase 1
- **수정 시 테스트 위험**: 정의를 바꾸면 Medium

---

## 3. 아키텍처 위험 (A)

| ID | 등급 | 문제 | 근거 코드 | 영향 / 발생 조건 | 현재 테스트 | 권장 단계 | 수정 시 테스트 위험 |
|---|---|---|---|---|---|---|---|
| A-01 | P1 | 데이터 검증 모듈이 백테스트 러너에 의존함 (타입 주석 목적) | `data_quality.py:7-9, 97-101` | Paper/Live가 러너를 import해야 하는 구조. 반대 방향 import가 추가되면 순환이 생김 | 간접적으로 있음 (`test_data_quality.py`) | P0-02 (D-01) | 재export하면 Low |
| A-02 | P1 | `ExecutionMarketDay`에 시장 관측, 비용 가정, 위험 파라미터가 섞여 있음 | `system_backtest.py:28-47` | 시각 필드 추가, adapter 분리가 어려움. 동적 모드에서 vol 목표 필드는 무시됨 | 있음 | P0-02 (D-01) | 구조를 바꾸면 fingerprint가 바뀌므로 Medium |
| A-03 | P1 | 일간 회계 조립 코드가 3벌, 날짜 루프가 3벌, 준비 루프가 2벌 | `daily_step.py:41-102`, `roll_aware_daily_step.py:73-127`, `contract_aware_daily_step.py:126-258`, `backtest.py:37-68`, `contract_aware_backtest.py:55-95`, `portfolio_backtest.py:284-634`, `system_backtest.py:65-234, 236-497` | 수정할 때 일부 경로만 바뀌는 불일치 위험 (A-05, F-13이 실제 사례) | 경로별로 있음 | P0-02 (D-02) | 통합하면 High (V1_DEPENDENCY_ANALYSIS §3.7) |
| A-06 | P1 | 상품 간 `day_dates`가 정확히 같아야 함. 휴장일이 다른 시장을 함께 다룰 수 없음 | `portfolio_backtest.py:216-242` | 다시장 포트폴리오에서 즉시 실패 (fail-fast이므로 왜곡은 없음) | 있음 (`test_unsynchronized_instrument_dates_are_rejected`) | P0-02 (D-07) | Medium |
| A-07 | P1 | 새 포지션 = 목표 포지션 (전량 체결 가정이 박혀 있음) | `contract_aware_daily_step.py:266`, `roll_aware_daily_step.py:137` (포트폴리오는 월물 합으로 다시 계산 `portfolio_backtest.py:514-520`) | Paper/Live의 부분 체결과 reconciliation을 반영할 수 없음 | 전량 체결 가정 테스트만 있음 | P0-02 (D-09) | Medium |
| A-04 | P2 | `ContractAwareBacktestDayInput.margin_per_contract_base`를 쓰지 않고 조용히 무시함. 러너가 `position_buffer_fraction`을 전달할 수 없음 | `contract_aware_backtest.py:31-36, 69-86` | 사용자는 margin이 검사된다고 오해할 수 있음. 단일 상품 경로에서는 버퍼링을 쓸 수 없음 | 없음 | P0-03 후보 | Low |
| A-05 | P2 | 포트폴리오 러너는 B2 러너를 거치지 않아 가격 연속성 검사가 없음. 준비 단계가 warm-up 이후에 날짜를 건너뛰면 그날의 보유 포지션 PnL이 조용히 누락됨 | `portfolio_backtest.py:443-501`, `system_backtest.py:318-324` | 발생 조건: warm-up 이후 forecast나 vol이 다시 `None`이 될 때 (vol이 정확히 0인 경우 등). 발생 가능성은 낮음 (INFERRED) | 없음 | P0-03 후보 (검사 추가 검토) | Low~Medium |
| A-08 | P2 | `performance`가 `PortfolioBacktestDayResult`에만 적용됨. 단일 상품 결과는 분석할 수 없음 | `performance.py:6-8, 37-72` | 연구 단계의 단일 상품 분석 | 있음 | P0-02 | Low |
| A-09 | P2 | `code_version`을 호출자가 문자열로 넣음 (Git 미연동). 데이터 vintage 없음. 결과 fingerprint에 체결가, 체결 내역, risk snapshot이 포함되지 않음 | `backtest_result_bundle.py:41-55, 99-132` | 같은 fingerprint인데 체결 세부가 다를 수 있음 (INFERRED: 일별 PnL과 포지션이 포함되므로 가능성은 낮음) | 있음 | P0-02 (D-11) | fingerprint 정의를 바꾸면 Medium |
| A-10 | P2 | PIT 신호를 날짜마다 전체 재계산함 (back-adjust + 6개 EWMA + vol) | `research_pipeline.py:220-248`, `futures_data.py:135-163` (날짜 × roll 수만큼 반복) | 10년 이상 이력 × 다상품에서 실행 시간 증가 (측정하지 않음, INFERRED) | 성능 테스트 없음 | Phase 1 | 최적화할 때 결과가 같은지 검증 필요 |
| A-11 | P2 | (a) `build_backtest_input_payload` 중복 정의 `backtest_manifest.py:405-517, 519-631`. (b) 실행되지 않는 분기 `research_pipeline.py:230-239` (as_of 날짜가 가격 날짜에서 오고, active 가격이 없으면 back-adjust가 예외를 던지므로 마지막 날짜는 항상 as_of와 같음, INFERRED). (c) 결합 경로의 `raw_crossover=0.0` 자리채움 `research_pipeline.py:132`. (d) src에서 쓰이지 않는 별칭 `execute_roll_trades` `roll_execution.py:123-142`, 이름이 오해를 부르는 `calculate_spread_cost` (슬리피지 포함) `costs.py:72-83` | 가독성. (c)는 결과를 읽는 사람이 crossover가 0이라고 오해할 수 있음 | 일부 있음 | P0-03 후보 | Low |
| A-13 | P2 | docstring과 공식 명세(입력, 출력, 단위, 전제, 예외)가 없음 | 전체 | CLAUDE.md §3.2 규칙과 차이 | — | 별도 승인 후 (CLAUDE.md §4.1) | 없음 |
| A-12 | P3 | 같은 검증이 여러 곳에 있고 내용이 조금씩 다름: 가격 검증 3곳, 체결일 중복 검사 3곳. 슬리피지 bool 검사가 `execution.py:69`에서는 빠져 있고 `data_quality.py:153-167`에는 있음. `data_quality`는 margin을 검증하지 않음 | V1_DEPENDENCY_ANALYSIS §3.3 | 입력 경로에 따라 검증 수준이 다름 | 부분적으로 있음 | P0-03 후보 | Low |
| A-14 | P3 | `instrument_results: dict[str, object]` `portfolio_backtest.py:52-55`. EWMAC 전용 이름인 `PreparedEWMACBacktest`를 포트폴리오 범용 입력으로 씀 `portfolio_backtest.py:33-36` | 규칙 종류가 늘어나면 혼란 | — | Phase 1 | Low |
| A-15 | P3 | IDM 상한 없음 `portfolio.py:48-60`. forecast 결합은 동일가중 고정 `combined_forecast.py:65-68`. 거래일 256 고정 `backtest_config.py:140-147` | 설정 유연성 | 있음 | Phase 1 | 값을 바꾸면 Medium |

---

## 4. 미검증 가정 목록

| ID | 가정 | 현재 근거 | 상태 |
|---|---|---|---|
| U-01 | quote mid가 당일 종가(active 월물 원시 가격)와 같다 | 테스트 데이터 구성 | UNVERIFIED (코드에서 검증하지 않음) |
| U-02 | 체결은 t일 종가 부근에서 일어난다 | 테스트 구성, `system_backtest.py` 주석 | UNVERIFIED |
| U-03 | `fx_to_base`는 체결 시각의 환율이다 | 없음 | UNVERIFIED |
| U-04 | 수수료는 상품 통화로 부과된다 | `costs.py:105-113` 구조 | UNVERIFIED |
| U-05 | roll event는 해당 날짜 이전에 알 수 있는 정보로 정해진다 | 없음 | UNVERIFIED |
| U-06 | forecast scalar, FDM, cap 등 상수가 원전과 일치한다 | 없음 | UNVERIFIED (CLAUDE.md §7) |
| U-07 | 세 번째 관측일부터 신뢰할 수 있는 vol을 얻을 수 있다 | `min_periods=2` | UNVERIFIED (F-01) |
| U-08 | 가산 back-adjustment에서 full 경로와 PIT 경로의 신호가 같다 | probe 1회 | CONFIRMED (현재 규칙 한정). 회귀 테스트는 없음 |
| U-09 | 시장 유동성은 무한하다 (전량 체결) | `execution.py:106-109` | UNVERIFIED (예상 자본 규모에서는 영향이 작을 것으로 INFERRED) |
| U-10 | legacy `daily_cash_vol_target`에 미래 정보가 들어 있지 않다 | 호출자 책임 | UNVERIFIED |
| U-11 | 테스트 환경 차이: CLAUDE.md의 검증 환경은 Termux (Python 3.14.6, pandas 3.0.6)이고, 이번 감사는 Windows 11 (Python 3.14.7, pandas 3.0.5)에서 실행함 | 두 환경 모두 306 passed | CONFIRMED (Windows에서도 통과). CLAUDE.md §6에는 Windows가 기록되어 있지 않음 |

---

## 5. 개선 후보 (우선순위별)

해결 코드를 작성하지 않았다. 아래는 다음 단계에서 검토할 후보다.

| 등급 | 후보 | 관련 ID |
|---|---|---|
| P0 | warm-up 정책을 결정하고, 최소 이력 기준을 설정 또는 데이터 계약으로 명시 | F-01 |
| P0 | 체결 시점 모델을 확정하고, quote와 fx에 관측 시각을 두며, mid와 평가가격의 정합성을 검증하거나 회계를 재정의 | F-02 |
| P1 | full 경로와 PIT 경로의 동일성 회귀 테스트. 또는 full 신호 경로를 연구 전용으로 격리 | F-03 |
| P1 | 가드레일을 거래 전 차단 방식으로 설계하고, 손실 한도와 Kill Switch 설계 문서 작성 (CLAUDE.md §8) | F-04 |
| P1 | 공용 시장 데이터 모델 정리 (V1_DEPENDENCY_ANALYSIS §2.4) | A-01, A-02 |
| P1 | 운영 기준 경로를 지정하고 legacy 경로의 위상 결정 | A-03, F-13, F-14 |
| P1 | 자산 유형(선물·ETF) 모델과 비용 정책 설계 | V1_DEPENDENCY_ANALYSIS §4 |
| P1 | 달력 정렬, FX, roll event 데이터 계약 정의 | A-06, F-06, F-07 |
| P2 | `contract_aware_backtest`의 margin과 buffer 전달 정리, 포트폴리오 러너의 연속성 검사 | A-04, A-05 |
| P2 | 중복 정의, 실행되지 않는 코드, 자리채움 값 정리 | A-11 |
| P2 | 재현성 범위 확장 (Git 연동, vintage) | A-09 |
| P3 | 검증 로직 일원화, 타입 강화, 설정 유연화 | A-12, A-14, A-15 |

---

## 6. P0-03 / P0-04에 넘길 검증 과제

### 6.1 P0-04 (금융 무결성 최종 검증)

| ID | 검증 과제 | 관련 |
|---|---|---|
| V-01 | 짧은 이력에서 초기 포지션 크기를 손으로 계산하고, warm-up 기준 후보별 영향 비교 | F-01 |
| V-02 | 일간 회계 등식 검증: mid ≠ 종가일 때 누락되는 손익을 독립 계산으로 정량화 | F-02 |
| V-03 | full 경로와 PIT 경로의 신호 동일성 (roll이 여러 번 있는 데이터) | F-03 |
| V-04 | EWMAC scalar, FDM, cap, 평균 forecast 10, vol span, long-run window, 0.7, 256을 원전과 대조 (확인하지 못하면 `UNVERIFIED` 유지) | F-09 |
| V-05 | 사이징 공식의 단위 일관성 독립 계산 (BC/d ÷ (pt/d × IC/pt/ct × BC/IC) = ct) | `position.py:58-93` |
| V-06 | back-adjustment gap 부호와 roll일 PnL 연속성 독립 계산 (roll일 구월물 보유 → 다음 날 신월물 보유) | `futures_data.py:115-168`, `system_backtest.py:145-154` |
| V-07 | 비용 공식 독립 계산: 수수료 + 스프레드 + 슬리피지, fx 환산 순서, 양쪽 roll leg | `costs.py`, `roll_execution.py` |
| V-08 | FX 시점 가정 문서화. 환율이 변할 때 gross PnL 환산 방식 검토 | F-06 |
| V-09 | 동적 위험 예산이 전일 종가 계좌만 쓰는지 재확인 (테스트는 있음), legacy 모드의 위험 | F-11 |
| V-10 | 계좌가 0 이하인 경우, 음수 가격, 0 vol 같은 경계 조건 | F-12 |
| V-11 | 성과 지표 정의 (Sharpe, drawdown, turnover)를 독립 계산과 비교 | F-15, `performance.py` |

### 6.2 P0-03 후보 (범위 미정, 잠정)

| ID | 과제 | 관련 |
|---|---|---|
| T-01 | `contract_aware_backtest`가 margin 필드를 무시하는 동작을 테스트로 고정할지, 고칠지 결정 | A-04 |
| T-02 | 포트폴리오 러너에서 날짜를 건너뛸 때의 동작 테스트 | A-05 |
| T-03 | `roll_aware_daily_step`에서 같은 월물로 롤하는 입력을 처리하는 방식 (폐기하지 않는 경우) | F-14 |
| T-04 | 검증 불일치(슬리피지 bool, margin 미검증)를 테스트로 드러내기 | A-12 |
| T-05 | 중복 정의 제거 등 동작이 바뀌지 않는 정리 작업과 그 회귀 확인 | A-11 |
| T-06 | Windows 환경을 검증 환경 목록에 추가할지 결정 (CLAUDE.md §6 변경은 승인 필요) | U-11 |
