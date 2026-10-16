# ADR-0005: 백테스트 경로와 V1 호환 전략 (Backtest Paths and V1 Compatibility)

## 1. Title

다섯 백테스트 경로의 위상, V1 기준 진입점, 새 연구 엔진과의 관계, V1 결과 보존 방법 (결정 ID D-02)

## 2. Status

**ACCEPTED** (2026-10-16)

| 항목 | 내용 |
|---|---|
| 승인일 | 2026-10-16 |
| 승인 주체 | 프로젝트 사용자 |
| 승인 근거 | 사용자의 명시적 승인 (작업 P0-02B-FINAL) |
| 승인 범위 | **핵심 아키텍처 설계 원칙** (아래 "승인된 원칙"). §6의 제목 "Proposed Decision"은 ADR 서식의 이름이며, 그 가운데 아래 원칙이 승인된 결정이다 |
| 구현 상태 | **미구현.** 새 연구 엔진, golden 테스트, 차등 비교 테스트 모두 아직 없다. 기존 경로는 그대로다 |
| 인수 테스트 | **명세만 존재, 미구현** (§10) |
| 미해결 질문 | §11의 Open Questions를 모두 유지한다 |
| 의미 | ACCEPTED는 설계 원칙이 승인되었다는 뜻이다. 구현 완료, 금융 공식의 독립 검증 완료, 실전 매매 준비 완료를 뜻하지 않는다 |
| 변경 규칙 | 핵심 결정을 바꾸려면 새 ADR로 대체한다 (`SUPERSEDED by NNNN`). 오탈자, 링크, 명백한 문서 오류만 직접 고친다 |

**승인된 원칙**

1. `run_combined_ewmac_portfolio_backtest`를 V1 기준 통합 진입점으로 지정한다 (§6.1, §6.2).
2. 기존 백테스트 경로를 즉시 삭제하거나 새 엔진으로 재배선하지 않는다 (§6.1).
3. 기존 경로를 V1 재현·교육·비교 기준으로 보존한다 (§6.2).
4. 새 금융 기능은 별도로 설계하는 새 연구 엔진에 구현한다 (§6.1, §6.4).
5. 새 엔진에는 ACCEPTED ADR-0001~0003의 원칙을 적용한다 (§6.4).
6. 구조를 바꾸기 전에 V1의 결과, 입력 fingerprint, 결과 fingerprint를 golden master로 고정한다 (§6.7 Stage 0).
7. 기존 V1 경로를 새 엔진으로 옮기려면 별도 ADR, 회귀 검증, 사용자 승인이 필요하다 (§6.7 Stage 5).

**승인되지 않은 사항 (Open Questions로 유지)**

| 사항 | 관련 질문 |
|---|---|
| golden master 테스트의 저장 형식과 상세 fixture 범위 | Q5-4 |
| golden master 테스트의 구체적인 구현 시점과 실행 작업 | Q5-9 |
| 첫 구현 자산 유형 (선물 / ETF / 동시) | Q5-8, ADR-0006 Q6-1 |
| 차등 비교의 허용 오차 | Q5-6 |
| 레거시 경로의 향후 폐기 시점 | Q5-1 |

golden 테스트는 구조 변경 전에 필요한 **보호 장치로서** 승인되었다. 이번 승인은 테스트 코드를 작성하라는 승인이 아니다.

- 작성일: 2026-10-16 (작업 P0-02B)
- 기준 커밋: `ac239b0` (`python -m pytest -q -W error` → 306 passed, 경고 0)
- 관련 P0-01 항목: GAP `A-03`, `A-04`, `A-05`, `A-06`, `A-08`, `F-03`, `F-04`, `F-11`, `F-13`, `F-14`. [V1_DEPENDENCY_ANALYSIS.md](../architecture/V1_DEPENDENCY_ANALYSIS.md) §3
- 관련 ADR: [0001](0001-execution-timing-and-valuation.md), [0002](0002-warmup-and-tradability.md), [0003](0003-pretrade-risk-policy.md) (모두 ACCEPTED), [0004](0004-market-data-and-domain-boundaries.md), [0006](0006-futures-etf-instrument-model.md) (ACCEPTED)
- **이 ADR은 경로를 삭제하거나 통합하지 않는다.** 위상과 규칙만 정한다.

## 3. Context

### 3.1 다섯 경로 (CONFIRMED)

| 경로 | 진입점 | 스텝 | 날짜 루프 | 신호 | t−1 정렬 | 롤 | fx | 슬리피지 | 버퍼 | 위험 예산 | 가드레일 | 연속성 검사 | `data_quality` | src 호출자 | 전용 테스트 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A 단일 상품 | `run_backtest` (`backtest.py:26-70`) | `run_daily_step` | 자체 (`backtest.py:37-68`) | 호출자 | 호출자 책임 | 없음 | **1.0 고정** | **없음** | 없음 | 호출자 값 | 없음 | 있음 (`:38-47`) | 없음 | 없음 | 7 |
| B1 Roll-aware | `run_roll_aware_daily_step` (스텝만) | 자체 | 없음 | 호출자 | 호출자 책임 | **항상 롤** | **1.0 고정** | **없음** | 없음 | 호출자 값 | 없음 | 해당 없음 | 없음 | 없음 | 7 |
| B2 Contract-aware | `run_contract_aware_backtest` (`contract_aware_backtest.py:38-97`) | `run_contract_aware_daily_step` | 자체 (`:55-95`) | 호출자 | 호출자 책임 | 선택 | 있음 | 있음 | 스텝은 지원, **러너는 전달 불가** | 호출자 값 | 없음 | 있음 (`:56-67`) | 없음 | C | 29 |
| C System | `run_ewmac_system_backtest`, `prepare_*` (`system_backtest.py:499-672`) | B2 | B2 러너 (full 경로의 run만) | 내부 (full 또는 PIT) | **내부 보장** (`:176-183, 430-437`) | 선택 | 있음 | 있음 | 없음 | 체결일 데이터 값 | 없음 | B2 러너를 거치면 있음 | 없음 | D (PIT 준비) | 5 |
| D Portfolio/System | `run_combined_ewmac_portfolio_backtest` (`portfolio_system_backtest.py:171-248`) | B2 스텝 **직접 호출** | 자체 (`portfolio_backtest.py:284-634`) | 내부 (**항상 PIT**) | **내부 보장** | 선택 | 있음 | 있음 | 있음 | legacy 또는 동적 | **사후 검사, ValueError로 중단** (`:560-579`) | **없음** | 있음 (`portfolio_system_backtest.py:106-116`) | 최상위 | 18 |

전용 테스트 수(CONFIRMED): A = `test_backtest.py` 3 + `test_daily_step.py` 4. B1 = `test_roll_aware_daily_step.py` 7. B2 = `test_contract_aware_backtest.py` 12 + `test_contract_aware_daily_step.py` 14 + `test_contract_aware_daily_step_buffering.py` 3. C = `test_system_backtest.py` 4 + `test_combined_system_backtest.py` 1. D = `test_portfolio_backtest.py` 9 + `test_portfolio_system_backtest.py` 8 + `test_v1_acceptance.py` 1. 합계 66개, 나머지 240개는 공유 공식과 분석 모듈의 테스트다.

### 3.2 공유 공식과 중복 조립 (CONFIRMED)

**같은 구현을 공유하는 금융 공식** (복제 없음):

| 공식 | 모듈 | 쓰는 경로 |
|---|---|---|
| gross·net PnL | `pnl.py:4-55` | 다섯 경로 모두 |
| 평균·목표 포지션, 반올림 | `position.py:8-155` | 다섯 경로 모두 |
| 거래량 | `trade.py` | 다섯 경로 모두 |
| 체결가 결정, 슬리피지 | `execution.py:62-152` | 다섯 경로 모두 (A는 직접, 나머지는 `roll_execution` 경유) |
| 비용 (수수료 + mid 대비 체결가 비용) | `costs.py:4-113` | 다섯 경로 모두 |
| 롤·리밸런스 거래 생성 | `roll.py:29-70` | B1, B2(→C, D) |
| 다리별 체결과 비용 집계 | `roll_execution.py:36-121` | B1, B2(→C, D) |
| 버퍼링 | `buffering.py:20-104` | B2 스텝(선택), D |
| 위험 예산 | `risk_target.py`, `portfolio.py:63-102` | D |
| 사후 가드레일 | `risk_guardrail.py:96-210` | D |

**중복된 조립 코드**:

| 책임 | 위치 | 벌 수 |
|---|---|---|
| 일간 회계 순서 (gross → 목표 → 거래 → 체결 → 비용 → net → 계좌) | `daily_step.py:41-102`, `roll_aware_daily_step.py:73-127`, `contract_aware_daily_step.py:126-258` | 3 |
| 날짜 루프와 상태 전달 | `backtest.py:37-68`, `contract_aware_backtest.py:55-95`, `portfolio_backtest.py:284-634` | 3 |
| 일별 입력 조립 (t−1 정렬) | `system_backtest.py:65-234` (full), `:236-497` (PIT) | 2 |
| 체결일 dict 구성과 중복 날짜 검사 | `system_backtest.py:80-88, 272-283`, `data_quality.py:106-109` | 3 |

중복 때문에 이미 경로 간 불일치가 생겼다: D에는 연속성 검사가 없고(A-05), A와 B1은 fx와 슬리피지를 무시한다(F-13).

### 3.3 현재 테스트가 결과를 얼마나 고정하는가 (CONFIRMED)

| 테스트 파일 | 리터럴 값 비교 (`approx(숫자)`, 여러 줄에 걸친 호출 포함) 수 | 테스트 수 |
|---|---|---|
| `test_backtest.py` (A) | 5 | 3 |
| `test_contract_aware_backtest.py` (B2) | 23 | 12 |
| `test_system_backtest.py` (C) | 9 | 4 |
| `test_combined_system_backtest.py` (C) | 0 | 1 |
| `test_portfolio_backtest.py` (D) | 19 | 9 |
| `test_portfolio_system_backtest.py` (D 최상위) | 4 (모두 위험 예산 값) | 8 |
| `test_v1_acceptance.py` (D 최상위) | **0** | 1 |

- **최상위 진입점의 손익, 포지션, 비용, 계좌 값을 고정하는 테스트가 없다.** `test_portfolio_system_backtest.py`의 리터럴 비교 4개는 위험 예산 값(계좌 일간 목표 1,250, 상품 목표 750)이다 (`tests/test_portfolio_system_backtest.py:366-391, 564-569`). 그 밖에는 거래일 수(`len(result.days) == 5`, `:145`) 같은 구조만 확인한다. `test_v1_acceptance.py`는 회계 항등식(합계, net = gross − 비용, 계좌 연결)과 성질(비용 발생, snapshot 존재)만 확인한다.
- **fingerprint 값을 고정하는 테스트도 없다** (ADR-0004 §3.5: 해시 리터럴 0건).
- 따라서 **"306개 테스트 통과"는 "기존 결과와 fingerprint 보존"을 보장하지 않는다.** 경로를 정리하기 전에 결과를 고정하는 장치가 먼저 필요하다 (§6.7 Stage 0).

### 3.4 경로별 알려진 결함과 차이 (CONFIRMED)

| ID | 내용 | 경로 | 근거 |
|---|---|---|---|
| A-04 | `ContractAwareBacktestDayInput.margin_per_contract_base`를 스텝에 넘기지 않고 조용히 무시함. `position_buffer_fraction`도 전달할 수 없음 | B2 러너 | `contract_aware_backtest.py:31-36, 69-86` |
| A-05 | 연속성 검사가 없음. 준비 단계가 warm-up 이후 날짜를 건너뛰면 그날 보유분 PnL이 누락됨 | D | `portfolio_backtest.py:443-501`, `system_backtest.py:318-324` |
| A-06 | 상품 간 날짜가 정확히 같아야 함 | D | `portfolio_backtest.py:216-242`, `test_unsynchronized_instrument_dates_are_rejected` |
| F-03 | full-history 신호가 미래 롤을 포함한 조정 시계열을 씀. 현재 규칙에서는 우연히 PIT와 같음 | C full | `research_pipeline.py:48-52, 160-164` |
| F-04 | 사후 가드레일이 백테스트를 중단시킴 | D | `portfolio_backtest.py:560-579`, `test_portfolio_rejects_gross_leverage_limit_breach` |
| F-11 | legacy 모드에서 위험 예산을 호출자가 넣음 | D, C | `portfolio_backtest.py:321-386` |
| F-13 | fx와 슬리피지를 무시함 | A, B1 | `daily_step.py:41-46, 86-92`, `roll_aware_daily_step.py:73-78, 103-110` |
| F-14 | 같은 월물로의 롤을 거부하지 않음. 방향성 비용은 항상 0 | B1 | `roll_aware_daily_step.py:65-71, 94` |
| — | `daily_cash_vol_target`의 의미가 경로마다 다름 (상품 수준 / 계좌 수준 / 무시) | C, D | ADR-0004 §3.3 |

참고: P0-01 문서(V1_DEPENDENCY_ANALYSIS §3.6)가 인용한 테스트 이름 `test_backtest_reproduces_manual_day_1_to_day_5`의 실제 이름은 `test_run_backtest_reproduces_manual_day_1_to_day_5`이다 (`tests/test_backtest.py:94`). P0-01 문서는 이번 작업에서 수정하지 않았다.

## 4. Decision Drivers

1. **V1 결과 재현성**: 기존 V1 API의 입력, 동작, fingerprint를 바꾸지 않는다 (ADR-0001~0003 §8.0).
2. **새 금융 기능의 단일 구현 위치**: 일반화 회계식, 거래 허용 정책, 거래 전 위험 검사, ETF를 다섯 군데에 따로 넣지 않는다.
3. **금융 결과 변경 위험 최소화**: 구조 정리가 손익 숫자를 조용히 바꾸지 않아야 한다.
4. **테스트 보존**: 기존 테스트를 삭제하거나 약화하지 않는다 (CLAUDE.md §5).
5. **Backtest/Paper/Live 공유**: 공유해야 할 계산과 모드별 계산을 구분한다 (CLAUDE.md §4).
6. **단계별 비용**: 각 단계가 독립적으로 검증 가능해야 한다.

## 5. Considered Options

### 5.1 계산 책임의 분류 (모든 대안에 공통)

| 분류 | 계산·책임 | V1 위치 |
|---|---|---|
| **Backtest·Paper·Live가 공유해야 할 계산** | PIT 신호(vol, forecast), 거래 허용 정책(ADR-0002), 위험 예산, 사이징, 버퍼링, 거래 전 위험 L1·L2(ADR-0003), 주문 의도 생성(월물 다리 포함), 사전 비용 추정, 손익 회계식과 평가(ADR-0001), Reconciliation 비교 계산(차이 계산만) | `research_pipeline`(PIT), `position`, `buffering`, `risk_target`, `portfolio`, `roll`(거래 생성), `costs`, `pnl`. 거래 허용 정책, 거래 전 위험, 일반 회계식은 없음 |
| **백테스트 전용** | replay 루프, 체결 가정(수수료표, 슬리피지, 체결 규칙, 데이터 지연), 시뮬레이션 체결(전량 체결), V1 사후 가드레일(호환 모드), legacy 위험 예산 입력 | `*_backtest` 러너, `execution.execute_market_order`, `risk_guardrail.validate_risk_snapshot` |
| **브로커 실행 전용** | 주문 제출, 주문 상태 추적, 브로커 체결 수신, L3 상태 게이트, Kill Switch 상태 전이, Reconciliation 조회 | 없음 (PLANNED, ADR-0003, D-09, D-12) |
| **레거시·교육용으로 남길 것** | 손계산 기준 예제, 단일 상품 호환 러너, full-history 신호 경로(재현·비교용) | A, B2 러너, C full |
| **향후 공통 코어로 바꿀 것** | 일간 회계 조립, 날짜 루프, 일별 입력 조립(PIT), 입력 검증 | §3.2의 중복 조립 코드 |

### 5.2 대안 A — 다섯 경로를 모두 같은 위상으로 유지

- **내용**: 지금처럼 다섯 경로를 동등하게 유지하고, 새 기능은 필요한 경로에 각각 넣는다.
- **장점**: 지금 당장 바뀌는 것이 없다.
- **단점**: 새 기능(ADR-0001~0003, ETF)마다 어느 경로에 넣을지 매번 정해야 한다. 이미 생긴 불일치(A-05, F-13)가 계속 늘어난다. "기준 결과"가 무엇인지 정해지지 않아 재현성 기준이 흐려진다.

### 5.3 대안 B — `portfolio_system_backtest`를 기준 진입점으로 지정하고 나머지는 레거시 호환·단위 검증 용도로 유지

- **내용**: D 경로를 **V1 기준 통합 진입점**으로 지정한다. 나머지 경로는 지우지 않고 역할을 정해 동결한다.
- **장점**: 코드 변경 없이 기준이 생긴다. D는 데이터 검증, PIT, 동적 위험 예산, 버퍼링, 가드레일, 성과 분석, 재현성이 모두 연결된 유일한 경로다 (V1_DEPENDENCY_ANALYSIS §3.6).
- **단점**: D 자체가 EWMAC 전용 준비 타입(`PreparedEWMACBacktest`)에 묶여 있고, ADR-0001~0003의 새 동작이 없다. 새 기능을 D에 직접 넣으면 V1 결과가 바뀐다. 따라서 B만으로는 새 기능의 구현 위치가 정해지지 않는다.

### 5.4 대안 C — 공용 Daily Engine을 새로 설계하고 모든 기존 경로를 Adapter로 연결

- **내용**: 새 공용 엔진을 만들고, 다섯 경로를 모두 adapter를 통해 이 엔진 위에서 실행되게 바꾼다.
- **장점**: 장기적으로 구현이 하나로 모인다.
- **단점**: 기존 경로를 새 엔진 위로 옮기는 순간 V1 결과가 바뀔 수 있는 지점이 많다 (아래 표). 기존 테스트의 기대값이 바뀌면 CLAUDE.md §5의 승인 사항이다.

C에서 결과가 바뀔 수 있는 지점 (메커니즘은 CONFIRMED, 영향 크기는 INFERRED):

| 지점 | 바뀌는 내용 | 영향받는 테스트 |
|---|---|---|
| D를 연속성 검사가 있는 공용 루프로 옮김 | 지금은 통과하는 입력이 거부될 수 있음 (A-05) | `test_portfolio_*`, `test_v1_acceptance.py` |
| A·B1을 fx·슬리피지가 있는 공용 스텝으로 옮김 | fx = 1, 슬리피지 0일 때만 같음 (F-13) | `test_daily_step.py`, `test_backtest.py`, `test_roll_aware_daily_step.py` |
| B1을 B2 검증으로 옮김 | 같은 월물 롤 입력이 거부됨, 비용 분류가 바뀜 (F-14) | `test_roll_aware_daily_step.py` |
| warm-up 날짜 처리를 ADR-0002 방식으로 통일 | 거래일 수와 보유분 PnL이 바뀜 | C, D 테스트 |
| 사후 가드레일을 ADR-0003 거래 전 검사로 통일 | 중단(ValueError) 대신 차단 → 기대값이 바뀜 | `test_portfolio_rejects_gross_leverage_limit_breach`, `test_portfolio_rejects_margin_usage_limit_breach` |
| 위험 예산 legacy·동적 모드 통일 | `daily_cash_vol_target` 해석이 바뀜 (ADR-0004 §3.3) | `test_portfolio_backtest.py` |

### 5.5 단계별 마이그레이션 비용과 금융 결과 변경 위험

| 단계 | A (동등 유지) | B (기준 진입점 지정) | C (전 경로 adapter화) |
|---|---|---|---|
| 지금 (지정·문서화) | 비용 없음 / 위험 없음 | 비용 거의 없음 (문서) / 위험 없음 | 비용 없음 (설계만) / 위험 없음 |
| V1 결과 고정 (golden 테스트) | 선택 사항 | 필요 (낮은 비용) / 위험 없음 | 필수 (낮은 비용) / 위험 없음 |
| 새 기능 구현 | 경로마다 반복 (높은 비용, 누적) / 경로 간 불일치 위험 높음 | 새 엔진 하나에 구현 (중간 비용) / V1 위험 없음 (V1 동결) | 새 엔진 하나에 구현 (중간 비용) / 위험은 다음 단계에 몰림 |
| 기존 경로 이전 | 해당 없음 | **하지 않음** (선택 사항, 별도 ADR) | 다섯 경로 모두 (높은 비용) / **결과 변경 위험 높음** (§5.4 표) |
| 장기 유지보수 | 다섯 벌 유지 | V1 동결본 + 새 엔진 두 벌 | 엔진 하나 + adapter 다섯 개 |

## 6. Proposed Decision

### 6.1 결정 요지

**B를 채택한다. D 경로(`run_combined_ewmac_portfolio_backtest`)를 V1 기준 통합 진입점으로 지정하고, 다섯 경로를 모두 동결된 V1 구현으로 유지한다. 새 금융 기능은 기존 경로에 넣지 않고 새 연구 엔진(PLANNED)에만 구현한다. C의 공용 엔진 아이디어는 새 연구 API에만 적용하고, 기존 경로를 새 엔진 위로 재배선하는 것은 이 ADR에서 채택하지 않는다 (별도 ADR과 golden 동일성 증명이 필요).**

- 기존 경로의 즉각적인 삭제나 일괄 통합을 제안하지 않는다.
- V1 경로와 새 엔진의 관계는 **차등 비교 테스트**(AT-0005-3)로 연결한다.

### 6.2 경로별 위상

| 경로 | 위상 (제안) | 역할 | 허용되는 변경 |
|---|---|---|---|
| D `run_combined_ewmac_portfolio_backtest`, `prepare_combined_ewmac_portfolio` | **V1 기준 통합 진입점** (V1 Reference Entry Point) | 기존 결과 재현. 새 엔진 차등 비교의 기준 | 동결. 결함 수정은 별도 승인과 golden 갱신 기록 |
| D `run_prepared_portfolio_backtest` | V1 기준 진입점의 내부 러너 (공개 API) | 같음 | 동결 |
| C PIT 준비 `prepare_point_in_time_combined_ewmac_backtest` | V1 기준 경로의 구성 요소 | D가 사용 | 동결 |
| C full-history (`prepare_ewmac_backtest`, `run_ewmac_system_backtest`, `prepare_combined_ewmac_backtest`) | **V1 재현·연구 비교 전용** | F-03 위험 때문에 새 연구 결과의 근거로 쓰지 않음 | 동결 |
| B2 스텝 `run_contract_aware_daily_step` | **V1 핵심 스텝** (동결된 기준 구현) | C·D가 사용. 새 엔진 `V1_COMPAT` 회계의 기준 | 동결 |
| B2 러너 `run_contract_aware_backtest` | V1 단일 상품 호환 러너 | 단위 검증, 단일 상품 재현 | 동결. margin 무시(A-04)는 알려진 제약으로 문서화 |
| A `run_backtest`, `run_daily_step` | **손계산 기준 예제** (Reference Example) | 일간 회계 순서의 교육·검증 (`test_run_backtest_reproduces_manual_day_1_to_day_5`) | 동결. fx·슬리피지 미지원(F-13)은 알려진 제약 |
| B1 `run_roll_aware_daily_step` | **폐기 후보** (Deprecated 후보, 유지) | 테스트 7개 보존. 새 코드에서 사용 금지 | 동결. 같은 월물 롤 결함(F-14)은 문서화. 삭제는 별도 승인 (Q5-1) |
| 새 연구 엔진 (PLANNED) | **새 금융 기능의 유일한 구현 위치** | ADR-0001~0004, 0006 구현 | 새 코드 |

### 6.3 V1 기준 진입점의 의미와 한계

D를 기준 진입점으로 지정하는 것은 **"V1 연구 결과를 재현하는 기준"**이라는 뜻이다. **실전 거래 기능을 갖췄다는 뜻이 아니다.** D에는 다음이 없다 (CONFIRMED).

| 없는 것 | 관련 결정 |
|---|---|
| 거래 전 위험 검사 (사후 검사 후 ValueError로 중단) | ADR-0003 |
| 주문 상태, 부분 체결, 미체결 (항상 전량 체결, 새 포지션 = 목표) | GAP F-08, A-07, D-09 |
| 관측 시각과 이용 가능 시각 | ADR-0001, ADR-0004 |
| 거래 허용 정책 (세 번째 관측일부터 신호가 계산되고, 네 번째 가격일에 첫 거래) | ADR-0002 |
| Reconciliation, Kill Switch, 브로커 adapter | ADR-0003, D-12 |
| 다시장 달력 정렬 (날짜가 정확히 같아야 함) | D-07 |
| ETF 표현 | ADR-0006 |
| 통화 키 FX | ADR-0001 R2, D-08 |
| 긴 이력에서의 성능 (PIT 신호를 날짜마다 다시 계산, O(n²). 성능 영향은 측정하지 않음, INFERRED) | GAP A-10 |

### 6.4 새 연구 엔진(PLANNED)이 지켜야 할 경계

| ID | 요구사항 | 근거 |
|---|---|---|
| E-1 | 정책 프로필을 명시적으로 받는다. 기본값 없음. 누락·잘못된 값은 ValueError | ADR-0001~0003 §8.0, ADR-0002 §6.4 |
| E-2 | 신호는 PIT 경로로만 만든다. full-history 신호 경로를 두지 않는다 | GAP F-03 |
| E-3 | `V1_COMPAT`가 아닌 프로필에서는 상품이 TRADABLE이 아닌 날(계산 불가 포함)에도 날짜를 유지하고, 그 상품의 **위험 증가 거래만** 막는다. 기존 포지션의 유지·축소·청산은 ADR-0003 정책을 따른다 (ADR-0002 Q2-4) | ADR-0002 §6.2 |
| E-4 | 손익은 ADR-0001 일반화 회계식으로 계산한다. `V1_COMPAT` 회계 모드는 명시적으로 고를 때만 쓴다 | ADR-0001 §6 |
| E-5 | 상품별 승수 `M[c]`, 통화별 `fx[κ,t]`로 계산한다 | ADR-0001 R2, ADR-0006 |
| E-6 | 거래 전 위험 L1·L2를 적용한다. 기본 정책(B 또는 C)은 ADR-0003 Q3-2에 따른다. `V1_COMPAT`를 명시한 재현 실행에서는 ADR-0003 §8의 사후 검사(A)만 쓴다 | ADR-0003 |
| E-7 | 입력은 ADR-0004의 도메인 계약(관측값·가정값·위험 입력 분리, 가격 종류, 시각)으로 받는다 | ADR-0004 |
| E-8 | 체결은 시각이 있는 체결 기록으로 남긴다. 백테스트에서 전량 체결을 시뮬레이션하더라도 포지션은 체결 기록에서 계산한다 (목표 = 포지션이라고 가정하지 않음) | GAP A-07, D-09 |
| E-9 | 데이터 경계 검증과 엔진 불변조건(가격 연속성, 상태 일관성)을 **모두** 적용한다 | §3.4의 검증 차이 |
| E-10 | 받은 입력을 조용히 무시하지 않는다. 쓰지 않는 입력은 받지 않거나 거부한다 | GAP A-04의 교훈 |
| E-11 | 위험 예산: `LIVE` 프로필(Paper/Live)에서는 결정 시점 계좌와 위험 목표로 계산한다 (ADR-0003 §6.4). `V1_COMPAT` 재현 실행은 V1 legacy 입력의 의미를 보존한다. `RESEARCH`에서 명시적 위험 예산 시계열을 허용할지는 **미정**이다 (ADR-0004 Q4-7, P0-03에서 사용자 결정) | ADR-0004 §6.3, Q4-7 |

### 6.5 V1 호환성 요구사항

| ID | 요구사항 | 확인 방법 |
|---|---|---|
| C5-1 | 기존 V1 공개 API(이름, import 경로, 시그니처, dataclass 필드)를 보존한다. 테스트가 쓰는 비공개 이름도 포함한다 | AT-0005-1 (a) |
| C5-2 | 기존 306개 테스트를 기대값 수정 없이 통과한다 | `python -m pytest -q -W error` |
| C5-3 | 기존 일별 PnL, 포지션, 비용, 체결 결과를 보존한다 | AT-0005-1 (b), Stage 0 golden |
| C5-4 | 기존 manifest와 입력·결과 fingerprint를 보존한다 | AT-0005-1 (b), ADR-0004 AT-0004-3 |
| C5-5 | 새 연구 API는 정책 프로필을 명시적으로 받는다 | AT-0005-2 |
| C5-6 | Paper/Live에서는 `V1_COMPAT`를 쓸 수 없고, 기존 V1 API를 주문 경로에서 호출하지 않는다 | ADR-0002 AT-0002-7 |
| C5-7 | 구현 전이므로 C5-2~C5-4의 보존은 **INFERRED**다. Stage 0 golden 테스트가 생겨야 CONFIRMED로 바꿀 수 있다 | §3.3 |

### 6.6 설계 시 주의할 문제별 결정

| 문제 | V1 (동결) | 새 연구 엔진 |
|---|---|---|
| `system_backtest`의 t−1 신호 정렬 (`:176-183, 430-437`) | 인덱스 오프셋(`signals[index − 1]`)으로 보장. 그대로 둔다 | 시점 계약으로 보장한다: 신호 입력의 `data_available_at ≤ decision_at` (ADR-0001 I-1). 인덱스 위치에 의존하지 않는다. 같은 입력에서 V1과 같은 신호가 쓰이는지 AT-0005-3으로 확인한다 |
| PIT 경로와 full-history 경로 | 둘 다 유지. full은 재현·비교 전용 (§6.2) | PIT만 쓴다 (E-2). full과 PIT의 동일성 회귀 테스트는 P0-04 (GAP F-03, V-03) |
| 포트폴리오 러너의 날짜 정렬 (`portfolio_backtest.py:216-242`) | 정확히 같지 않으면 거부. 그대로 둔다 | D-07이 정해지기 전에는 같은 fail-fast를 쓴다. 임의로 가격을 앞 날짜 값으로 채우지 않는다 |
| 포트폴리오 러너와 단일 상품 러너의 입력 검증 차이 | D는 `data_quality`는 쓰지만 연속성 검사가 없고, B2 러너는 연속성 검사는 있지만 `data_quality`를 쓰지 않는다. 그대로 둔다 | 두 검증을 모두 적용한다 (E-9) |
| warm-up 날짜 제외 (A-05) | 그대로 둔다 | `V1_COMPAT`에서는 V1처럼 제외해 재현한다. 다른 프로필에서는 날짜를 유지한다 (E-3, AT-0005-4) |
| Roll-aware 경로의 같은 월물 롤 허용 (F-14) | B1 결함을 그대로 두고 문서화한다 | B2와 같은 검증을 쓴다: `roll_to ≠ active` (`contract_aware_daily_step.py:105-111`). `RollEvent`도 같은 월물을 거부한다 (`futures_data.py:33-36`) |
| margin 필드 전달 누락 (A-04) | B2 러너는 무시하고, D는 사후 검사에 쓴다. 그대로 둔다 | margin은 위험 입력 묶음(ADR-0004 §6.3)으로만 받고 ADR-0003 L1에서 쓴다. 받은 값을 무시하지 않는다 (E-10) |
| 거래 후 가드레일과 ACCEPTED ADR-0003 거래 전 검사 | 사후 검사(ValueError로 중단)를 유지한다. ADR-0003 §8의 V1 호환 모드 A다 | 거래 전 L1·L2를 적용한다. 기본 정책(B 또는 C)은 ADR-0003 Q3-2에 따른다. `V1_COMPAT` 재현 실행에서는 사후 검사(A)만 쓴다. 사후 일관성 검사를 함께 둘지는 ADR-0003 Q3-9 |
| legacy 위험 예산 (F-11) | 유지한다 | `LIVE`에서는 결정 시점 계좌로 계산한다. `V1_COMPAT` 재현 실행은 V1 legacy 입력을 변환기로 재현한다. `RESEARCH`의 명시적 입력 허용 여부는 미정 (E-11, ADR-0004 Q4-7) |

**금융 공식은 이 문제들을 이유로 바꾸지 않는다.** V1 경로의 결함은 문서화하고, 새 엔진에서 처음부터 올바르게 구현한다. V1 경로를 고치려면 별도 승인과 golden 갱신 기록이 필요하다 (Q5-3).

### 6.7 마이그레이션 단계 (구현은 이 ADR의 범위 밖)

| 단계 | 내용 | V1 결과 변경 위험 | 테스트 영향 | 승인 |
|---|---|---|---|---|
| **0** | **V1 golden master 고정** (원칙 승인됨): 대표 fixture마다 일별 결과(포지션, 체결, 비용, PnL, 계좌), 입력·결과 fingerprint, 공개 API 목록을 기록하는 테스트 추가. fixture 후보: 롤일, KRW 기준통화와 USD 상품, 슬리피지 1 tick, 버퍼링, risk policy, legacy·동적 모드. **저장 형식과 상세 범위는 미승인 (Q5-4)** | 없음 | 테스트 추가만 (기존 테스트 수정 없음) | **구현 시점과 실행 작업은 미승인 (Q5-9)**. 별도 작업 명세와 승인 필요 |
| 1 | ADR-0004 Stage 1 (역방향 의존 해소. 방식 A/A-0는 미승인, ADR-0004 Q4-1) | 없음 (Stage 0이 보호) | 없음 | 방식 선택 승인. 대안 A이면 모듈 이동 승인 |
| 2 | P0-03 도메인 계약과 새 연구 엔진의 뼈대를 **추가** | 없음 (V1 미변경) | 새 테스트만 | P0-03, 구현 승인 |
| 3 | 차등 비교: 새 엔진(`V1_COMPAT` 명시)과 D 경로를 같은 입력으로 비교 (AT-0005-3). ADR-0001 C-2(롤일 동치성)를 여기서 확인 | 없음 | 새 테스트만 | 구현 승인 |
| 4 | 새 엔진에 일반 모드 기능 추가 (ADR-0001 일반 회계, ADR-0002 RESEARCH, ADR-0003 B, ADR-0006 ETF) | 없음 (V1 미변경) | 새 테스트만 | 기능별 명세·독립 검증·승인 (CLAUDE.md §3.2) |
| 5 (선택) | V1 러너를 새 엔진 위에서 실행되게 바꾸기, B1 삭제, full 경로 은퇴 | **높음** | 기존 테스트 기대값이 바뀔 수 있음 | **별도 ADR + golden 동일성 증명 + 사용자 승인** |

**golden master의 한계**: Stage 0 golden은 V1의 **현재 출력**을 고정하는 회귀 장치다. 그 값이 금융적으로 옳다는 것을 증명하지 않는다. 금융 무결성 검증은 P0-04에서 독립 계산으로 한다. golden 값과 독립 계산이 다르면 golden을 조용히 고치지 않고, 원인과 처리 방법을 별도로 승인받는다.

### 6.8 ACCEPTED ADR과의 정합성

| ACCEPTED 결정 | 이 ADR의 대응 | 충돌 여부 |
|---|---|---|
| ADR-0001~0003 §8.0: 기존 V1 API의 입력·동작·fingerprint 불변, 새 연구 API는 프로필 명시, Paper/Live는 `V1_COMPAT` 불가 | V1 경로 동결 (§6.2), C5-1~C5-7, E-1 | 없음 |
| ADR-0001 C-2: 롤일까지 V1과 같은지는 구현·회귀 검증 전까지 INFERRED | Stage 3 차등 비교에서 확인 (AT-0005-3) | 없음 |
| ADR-0001 일반화 회계식과 평가 주기 귀속 | 새 엔진만 구현 (E-4, E-8) | 없음 |
| ADR-0002 "날짜 유지 + 거래 차단", `V1_COMPAT`에서는 warm-up 건너뛰기 유지 | E-3, §6.6 warm-up 행 | 없음 |
| ADR-0003 거래 전 L1·L2, V1 호환 모드에서는 사후 검사 A만 사용 | §6.6 가드레일 행 | 없음 |
| ADR-0003 처리 순서 (목표 → 버퍼링 → 거래 허용 판단 → L2 → L3 → 주문) | 새 엔진 흐름이 이 순서를 따른다 ([P0-02B_DECISION_SUMMARY.md](../architecture/P0-02B_DECISION_SUMMARY.md) §3) | 없음 |

## 7. Consequences / Trade-offs

**장점**
- 코드 변경 없이 "V1 기준 결과"가 정해진다.
- 새 금융 기능이 한 곳(새 엔진)에만 들어가므로 경로 간 불일치가 더 늘지 않는다.
- V1 결과가 바뀌는 작업(Stage 5)은 별도 결정으로 분리되어 실수로 일어나지 않는다.

**단점과 비용**
- 당분간 V1 동결본과 새 엔진 두 벌을 유지한다. 같은 공식 함수(`pnl`, `position`, `costs` 등)를 공유하더라도 조립 코드는 두 벌이 된다.
- 차등 비교 테스트를 유지해야 한다.
- V1의 알려진 결함(A-04, A-05, F-13, F-14)은 V1 안에 그대로 남는다. 결과를 읽는 사람이 이를 알 수 있도록 문서화해야 한다.

## 8. Compatibility with V1

이 ADR은 ADR-0001 §8.0(세 ADR 공통)의 `V1_COMPAT` 적용 범위를 그대로 따른다.

| 항목 | 영향 |
|---|---|
| 기존 306개 테스트 | 변경 없음 (이 ADR은 코드를 바꾸지 않음. 이후 단계의 보존은 INFERRED, C5-7) |
| 기존 경로 | 삭제·통합 없음. 동결 |
| 기존 결과와 fingerprint | Stage 0 golden 테스트로 고정한 뒤에만 구조 작업을 시작한다 |
| 공개 API | 변경 없음. 새 매개변수를 추가하지 않는다 (예: V1 API에 프로필 인자를 추가하지 않음) |

## 9. Financial Integrity Implications

- **결과 재현성**: golden 고정 없이 경로를 정리하면 손익이 조용히 바뀔 수 있다 (§3.3). Stage 0이 이를 막는다.
- **look-ahead**: 새 엔진은 full-history 신호 경로를 두지 않는다 (E-2). 곱셈 조정(ETF)이 들어오면 full 경로는 실제 look-ahead가 되기 때문이다 (GAP F-03).
- **손익 누락**: 새 엔진은 날짜를 유지하므로 A-05 같은 보유분 손익 누락이 생기지 않는다 (E-3).
- **비용 일관성**: 새 엔진은 fx와 슬리피지를 항상 받으므로 F-13 같은 경로별 비용 차이가 없다.
- **위험 검사**: V1 기준 진입점은 사후 검사만 한다. 그 결과를 Live 준비의 근거로 쓰면 안 된다 (§6.3).

## 10. Acceptance Criteria

인수 테스트는 **명세**다. 이번 작업에서 구현하지 않았다.

### AT-0005-1 기존 V1 API와 결과 fingerprint가 보존된다 (인수 테스트 명세 2)

- **입력**:
  - (a) `ac239b0`에서 기록한 V1 공개 API 목록: 모듈 경로, 이름, 함수 시그니처(매개변수 이름·순서·기본값), dataclass 필드(이름·기본값·순서). 테스트가 import하는 비공개 이름(`_prepare_backtest_from_point_in_time_signals`) 포함
  - (b) Stage 0 golden fixture와, `ac239b0`에서 계산한 입력 fingerprint, 결과 fingerprint, 일별 결과
- **기대 결과**:
  - 모든 이름이 같은 경로에서 import된다. 재export한 클래스는 원래 클래스와 `is`로 같다.
  - 시그니처와 dataclass 필드가 같다.
  - 입력·결과 fingerprint가 **문자 단위로 같다**.
  - 일별 결과가 같다. 정수(포지션, 거래량)는 정확히 같다. 실수(체결가, 비용, PnL, 계좌)는 연산 경로가 같으므로 정확히 같아야 한다.
  - 306개 테스트가 통과하고 경고가 0이다.
- **전제조건**: Stage 0 golden 테스트가 있다. **지금은 없으므로** 이 기준을 자동으로 검사할 수 없다 (§3.3).
- **예외조건**: V1을 의도적으로 바꾸는 경우에는 별도 승인을 받고, 이전 fingerprint와 새 fingerprint, 바꾼 이유를 기록한다. golden 값을 조용히 갱신하지 않는다.
- **V1 호환성 영향도**: 이 테스트가 V1 보존의 직접 장치다.
- **새 테스트 후보**: `test_v1_public_api_surface_is_unchanged`, `test_v1_golden_input_fingerprints`, `test_v1_golden_result_fingerprints`, `test_v1_golden_daily_results`

### AT-0005-2 새 연구 경로에서 정책 프로필을 생략하면 거부된다 (인수 테스트 명세 3)

- **입력**: 새 연구 API 호출

| 경우 | 프로필 값 |
|---|---|
| (a) | 인자 없음 |
| (b) | `None` |
| (c) | 빈 문자열 |
| (d) | `"v1_compat"` (대소문자 변형) |
| (e) | `"RESEARCHX"` (알 수 없는 값) |
| (f) | `"RESEARCH"` (명시) |
| (g) | `"V1_COMPAT"` (명시, Backtest 재현) |
| 비교 | 기존 V1 API 호출 (프로필 인자 없음) |

- **기대 결과**:
  - (a)~(e): 엔진이 시작되기 전, 설정 검증 단계에서 **ValueError**. 기본값으로 대체하지 않는다.
  - (f): 실행된다.
  - (g): 실행된다. manifest에 모드를 기록하고, 보고서에 "V1 가정(mid = 평가가격)"을 표시한다 (ADR-0001 §8.3).
  - 기존 V1 API: 프로필 인자 없이 지금처럼 동작한다 (암묵적 `V1_COMPAT`).
- **전제조건**: ADR-0002 §6.4, ADR-0001 §8.0.
- **예외조건**: 실행 모드가 Paper/Live이면 (g)도 ValueError다 (ADR-0002 AT-0002-7).
- **V1 호환성 영향도**: 없음. V1 API에 매개변수를 추가하지 않는다.
- **새 테스트 후보**: `test_new_research_api_rejects_missing_profile`, `test_new_research_api_rejects_unknown_or_miscased_profile`, `test_v1_api_runs_without_profile_argument`

### AT-0005-3 기존 경로와 새 경로에 같은 입력을 넣고 결과를 비교한다 (인수 테스트 명세 8)

- **입력**: Stage 0 golden fixture 집합. fixture 범위는 미승인이다 (Q5-4). 아래는 포함을 권장하는 후보다.
  - 두 상품, 서로 다른 통화(KRW 기준통화, USD 상품, fx 1,350)
  - 롤이 있는 날
  - 슬리피지 1 tick
  - 버퍼링
  - 한도 안의 risk policy
  - legacy 모드와 동적 모드

  같은 입력으로 (i) V1 `run_combined_ewmac_portfolio_backtest`와 (ii) 새 연구 엔진(`V1_COMPAT` 명시, ADR-0004 변환기로 입력 변환)을 실행한다.
- **기대 결과**:
  - 거래일 목록이 같다 (`V1_COMPAT`에서는 warm-up 날짜도 V1처럼 제외).
  - 날짜·상품마다 목표 포지션, 방향성 거래량, 월물별 포지션, 체결(월물, 수량, 가격), 거래 비용, gross·net PnL, 개장·종가 계좌가 같다.
  - 허용 오차 정책은 **미승인**이다 (Q5-6). 권장안은 정확 일치다. 연산 순서가 달라 정확 일치가 불가능하면, 허용 오차를 근거와 함께 정하고 승인받는다 (CLAUDE.md §3.2). 근거 없이 오차를 넓히지 않는다.
  - 롤일도 같아야 한다. 이 테스트가 통과해야 ADR-0001 C-2(롤일 동치성)를 INFERRED에서 CONFIRMED로 바꿀 수 있다.
  - 추가 확인: 같은 입력을 일반 회계 모드로 돌리면, V1과의 차이가 ADR-0001 §6.2의 valuation gap 항 `Σ fx[κ(c(k)),t] × Δq[k] × (V − mid) × M[c(k)]`과 정확히 같아야 한다.
- **전제조건**: Stage 0, ADR-0004 변환기, ADR-0001 `V1_COMPAT` 회계 모드 정의. legacy 모드 fixture는 변환기에 위험 예산 수준을 "계좌"로 명시해 재현한다 (ADR-0004 AT-0004-4, E-11).
- **예외조건**: 차이가 나면 테스트는 실패한다. 기대값을 V1 쪽으로 맞추거나 새 엔진 쪽으로 맞추는 조정을 자동으로 하지 않는다. V1 결과가 기준이며, V1 결함이 원인으로 입증되면 별도 승인을 받는다.
- **V1 호환성 영향도**: 없음. V1은 바뀌지 않는다.
- **새 테스트 후보**: `test_new_engine_v1_compat_matches_portfolio_system_backtest`, `test_new_engine_v1_compat_matches_on_roll_days`, `test_general_mode_difference_equals_valuation_gap`

### AT-0005-4 새 엔진의 프로필별 warm-up 날짜 처리 (ADR-0002 AT-0002-3 참조)

- **입력**: 보유 5 ct인 상태에서 어느 날 신호가 계산 불가(`NOT_CALCULABLE`)가 되는 입력
- **기대 결과**:
  - `V1_COMPAT`: V1 D 경로처럼 그날을 일별 입력에서 제외한다 (V1 재현).
  - `RESEARCH`: 날짜를 유지하고, 보유분 gross PnL과 계좌 평가를 계산한다. 위험 증가 거래만 막는다.
  - 그날 `RESEARCH`에서 위험 축소 거래가 없다고 하면(ADR-0003 정책 결과에 따라 달라짐), **그날(t)의 일별 손익 차이**는 보유분 손익 `5 × (V[t] − V[t−1]) × M × fx`와 같다. V1은 이 구간의 손익을 기록하지 않기 때문이다 (GAP A-05). t 이후의 날짜는 동적 위험 예산에서 계좌 차이 때문에 목표가 달라질 수 있으므로, 같은 값을 기대하지 않는다.
- **전제조건**: E-3, ADR-0002 §6.2.
- **예외조건**: 평가가격이 없으면 두 프로필 모두 ValueError다.
- **V1 호환성 영향도**: 없음.
- **새 테스트 후보**: `test_v1_compat_profile_reproduces_warmup_day_skip`, `test_research_profile_keeps_ineligible_day_pnl`

## 11. Open Questions

| ID | 질문 | 결정 주체 |
|---|---|---|
| Q5-1 | B1 `roll_aware_daily_step`을 언제, 어떻게 폐기할 것인가? 테스트 7개 삭제는 승인 사항이다. 권장: 지금은 폐기 후보로 표시만 하고, 새 엔진의 롤 검증이 끝난 뒤 다시 결정. **레거시 경로의 폐기 시점은 승인 범위 밖, 미결정** | 사용자 |
| Q5-2 | full-history 신호 경로를 "V1 재현·비교 전용"으로 지정하는 것을 승인하는가? | 사용자 |
| Q5-3 | V1 결함(A-04, A-05, F-13, F-14)을 V1 경로 안에서 고칠 것인가, 문서화만 할 것인가? 권장: 문서화만 하고 새 엔진에서 해결 | 사용자 |
| Q5-4 | Stage 0 golden fixture의 범위와 저장 형식 (테스트 코드 안의 리터럴 / 별도 데이터 파일). **승인 범위 밖, 미결정** | 사용자, D-11 |
| Q5-5 | 새 연구 엔진의 진입점 위치와 이름 | D-10 |
| Q5-6 | 차등 비교의 허용 오차 정책. 권장안은 정확 일치. **승인 범위 밖, 미결정** | 사용자 (P0-04 근거) |
| Q5-7 | 단일 상품 연구를 새 엔진에서 "상품 하나짜리 포트폴리오"로 처리할 것인가, 별도 진입점을 둘 것인가? (A-08: 성과 분석이 포트폴리오 결과 타입에 묶여 있음) | 사용자 |
| Q5-8 | 새 엔진의 첫 구현 자산 유형: 선물 먼저 / ETF 먼저 / 동시 개발 (ADR-0006 Q6-1). 현재 V1이 선물 중심이라는 사실만으로 정하지 않는다. **승인 범위 밖, 미결정** | 사용자 |
| Q5-9 | Stage 0 golden master 테스트를 언제, 어떤 작업으로 구현할 것인가? (원칙은 승인됨. 구현 작업은 별도 명세와 승인 필요) | 사용자 |

## 12. Related Code and Documents

- 코드: `backtest.py:26-70`, `daily_step.py:27-114`, `roll_aware_daily_step.py:40-141`, `contract_aware_backtest.py:14-97`, `contract_aware_daily_step.py:46-271`, `system_backtest.py:65-672`, `portfolio_backtest.py:162-640`, `portfolio_system_backtest.py:75-248`, `backtest_manifest.py:405-669`, `backtest_result_bundle.py:57-191`
- 테스트: `tests/test_backtest.py:94` (`test_run_backtest_reproduces_manual_day_1_to_day_5`), `tests/test_roll_aware_daily_step.py`, `tests/test_contract_aware_backtest.py`, `tests/test_system_backtest.py:46, 100, 164, 275`, `tests/test_portfolio_backtest.py:404, 737, 791`, `tests/test_portfolio_system_backtest.py`, `tests/test_v1_acceptance.py`
- 문서: [V1_DEPENDENCY_ANALYSIS.md](../architecture/V1_DEPENDENCY_ANALYSIS.md) §3; [V1_DATA_FLOW.md](../architecture/V1_DATA_FLOW.md) A~D; [V1_GAP_ANALYSIS.md](../quality/V1_GAP_ANALYSIS.md) A-03~A-06, F-03, F-04, F-11, F-13, F-14; [P0-02B_DECISION_SUMMARY.md](../architecture/P0-02B_DECISION_SUMMARY.md)
- 관련 ADR: [0001](0001-execution-timing-and-valuation.md), [0002](0002-warmup-and-tradability.md), [0003](0003-pretrade-risk-policy.md), [0004](0004-market-data-and-domain-boundaries.md), [0006](0006-futures-etf-instrument-model.md)

## 13. 개정 이력

| 개정 | 날짜 | 내용 |
|---|---|---|
| R0 | 2026-10-16 | 최초 제안 (P0-02B). 상태 PROPOSED. 작성 후 읽기 전용 독립 검토의 지적 사항을 반영함 ([P0-02B_DECISION_SUMMARY.md](../architecture/P0-02B_DECISION_SUMMARY.md) §13) |
| ACCEPTED | 2026-10-16 | 상태를 PROPOSED에서 **ACCEPTED**로 변경 (사용자의 명시적 승인, 범위는 §2). 승인 범위에 맞춰 다음 표현을 조정했다. 새 결정은 추가하지 않았다. (1) golden master의 원칙(승인)과 저장 형식·fixture 범위·구현 시점(미승인)을 구분하고, golden이 정답을 증명하지 않는다는 점을 명시 (§6.7, AT-0005-3, Q5-4, Q5-9 추가). (2) 차등 비교 허용 오차를 미결정으로 표시 (AT-0005-3, Q5-6). (3) 첫 구현 자산 유형 질문에 "ETF 먼저"를 포함한 세 선택지를 명시 (Q5-8). (4) `RESEARCH` 위험 예산 입력 정책을 ADR-0004 Q4-7에 맞춰 미결정으로 표시 (E-11, §6.6). (5) ADR-0004 Stage 1 방식을 미승인으로 표시 (§6.7). (6) 관련 ADR 상태 표기 갱신 |
