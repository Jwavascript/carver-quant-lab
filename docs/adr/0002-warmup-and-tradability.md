# ADR-0002: Warm-up과 거래 허용 정책 (Warm-up and Tradability)

## 1. Title

신호의 계산 가능성(CALCULABLE)과 거래 가능성(TRADABLE) 분리, warm-up 정책

## 2. Status

**ACCEPTED** (2026-10-16)

| 항목 | 내용 |
|---|---|
| 승인일 | 2026-10-16 |
| 승인 주체 | 프로젝트 사용자 |
| 승인 근거 | 사용자의 명시적 승인 (작업 P0-02A-FINAL) |
| 승인 범위 | **핵심 아키텍처 정책 원칙.** 구체적으로 R2 기준 §5.1(Signal Eligibility와 Trading State의 구분)과 §6(계산 함수 밖의 거래 허용 정책 계층, 프로필 구조, LIVE fail-closed, 부적격 상태에서도 평가 지속)의 정책 원칙, §8.0의 `V1_COMPAT` 적용 범위. §6의 제목 "Proposed Decision"은 ADR 서식의 이름이며, 그 정책 원칙이 승인된 결정이다 |
| 승인 범위가 아닌 것 | §11 Open Questions 전부. 이 ADR에서는 warm-up 최소 관측 수와 vol 하한의 형태와 값 (Q2-1, Q2-2), 결측·거래 재개 정의와 재-warm-up 관측 수 (Q2-3), 거래 부적격 상태의 기존 포지션 처리 (Q2-4), 신규 상품 승인 (Q2-5), `min_periods` 유지 여부 (Q2-6), 성과 평가 시작일 표시 (Q2-7), 다수 상품 부적격 시 계좌 상태 (Q2-8), `RESEARCH` 임계값 누락 처리 (Q2-9). 또한 이 ADR이 설명하는 기능의 구현, 신규 금융 공식의 실제 구현, 실전 주문 활성화 |
| 의미 | ACCEPTED는 **설계 원칙이 승인되었다**는 뜻이다. 구현 완료, 금융 계산의 정확성 검증 완료, Live Trading 준비 완료를 뜻하지 않는다. §10의 인수 테스트는 **명세**이며 아직 구현되지 않았다. 숫자 예제는 저장소 밖 독립 산술로 확인한 값이다 |
| 변경 규칙 | 핵심 결정을 바꾸려면 새 ADR을 작성하고 이 ADR을 `SUPERSEDED by NNNN`으로 바꾼다. 오탈자, 링크, 명백한 문서 오류 수정은 허용하되 결정 내용은 바꾸지 않는다. Open Questions의 답은 후속 검증(P0-03, P0-04, 시장·브로커 선정)에서 정하고, 결정에 영향을 주면 새 ADR로 기록한다 |

- 작성일: 2026-10-16
- 기준 커밋: `df6547e` (306 passed)
- 개정: R1 (2026-10-16, 기준 커밋 `3bdfecb`). Signal Eligibility와 Trading State를 분리하고, `V1_COMPAT` 사용 범위 제한과 LIVE fail-closed 규칙을 추가했다. (당시 상태는 PROPOSED였다.) 변경 내역은 §13에 있다.
- 개정: R2 (2026-10-16). `V1_COMPAT` 적용 범위(§8.0)를 세 ADR에서 통일했다. 새 연구 API에는 기본 프로필이 없다. (당시 상태는 PROPOSED였다.)
- 관련 P0-01 항목: GAP `F-01`(P0), `A-05`, `F-09`. 결정 ID는 D-06.

## 3. Context

### 3.1 V1의 현재 warm-up 동작 (CONFIRMED)

| 구성 요소 | 현재 설정 | 의미 | 근거 |
|---|---|---|---|
| 가격 변화 | 첫 값은 `None` | n개 가격 → n−1개 변화 | `volatility.py:17-41` |
| 단기 vol | `ewm(span=32, adjust=False, min_periods=2).std(bias=False)` | **가격 변화 2개**(세 번째 가격)부터 값이 생김. 표본 2개의 표준편차 | `volatility.py:65-75` |
| long-run vol | `rolling(window=2560, min_periods=1).mean()` (단기 vol 시계열에 적용) | 단기 vol이 처음 생기는 날부터 값이 있음. 그날 long-run = 단기 vol 자신. 2560개가 쌓일 때까지는 확장 평균 | `volatility.py:173-176` |
| blended vol | 0.7 × 단기 + 0.3 × long-run | 초기에는 단기 vol과 같음 | `volatility.py:97-145` |
| EWMAC | `ewm(span, adjust=False)`, `min_periods` 미지정(기본 0) | 첫 가격부터 값이 있음. 첫 가격으로 시작하므로 slow EWMA(최대 span 256)는 초기에 거의 첫 가격에 머묾 | `forecast.py:190-206` |
| forecast | vol이 `None`이면 `None`. vol = 0이면 `None` | **vol이 생기는 날부터 forecast도 생김** | `forecast.py:132-133, 231-256` |
| 결합 forecast | 구성 중 하나라도 `None`이면 `None` | 모든 구성의 시작일이 같으므로 실질적으로 같은 날 시작 | `combined_forecast.py:133-138` |
| 거래 시작 | 전일 signal의 vol과 forecast가 모두 있는 첫날 | 네 번째 가격일에 첫 거래 | `system_backtest.py:115-121, 318-324` |
| 기존 테스트 | index 2에서 forecast가 존재함을 assert | **현재 동작이 테스트로 고정되어 있음** | `tests/test_research_pipeline.py:60-84` |

### 3.2 문제

- 표본 2~3개로 만든 vol이 작게 나오면, 평균 포지션 `= 일간 현금 목표 ÷ (vol × M × fx)`(`position.py:88-91`)가 과도하게 커진다.
- vol = 0은 `None`으로 걸러지지만 **아주 작은 양수 vol은 걸러지지 않는다.**
- long-run vol이 `min_periods=1`이라 초기에는 단기 vol과 같다. 그래서 "단기 vol이 장기 대비 비정상적으로 작다"는 비교로는 초기 과소 추정을 잡아내지 못한다 (§10 AT-0002-1).
- 결측 구간(달력 공백, 거래 중단)이 있으면 공백 전후의 가격 차이가 변화 1개로 처리된다 (`volatility.py:25-39`). 거래 재개 직후의 vol 의미가 달라질 수 있다 (INFERRED).
- 새 상품 상장, 거래 재개, 데이터 공급 중단에 대해 거래를 허용할지 판단하는 규칙이 없다.

## 4. Decision Drivers

1. **과대 포지션 방지**: 신뢰할 수 없는 추정치로 포지션을 키우지 않는다. 위험 성향이 "제한된 손실 허용"이다.
2. **계산 함수의 순수성 유지**: 기존 vol·forecast 계산 함수와 상수를 바꾸지 않는다 (CLAUDE.md §5 승인 사항).
3. **설명 가능성**: 거래하지 않은 이유를 날짜·상품별로 기록할 수 있어야 한다.
4. **연구와 실전의 차이**: 연구 백테스트는 앞부분 이력을 warm-up에 쓸 수 있다. 실전에서는 새 상품 진입 조건이 더 엄격해야 한다.
5. **V1 호환성**: 6~8일짜리 짧은 테스트 데이터로 만든 기존 테스트를 보존해야 한다.
6. **수치를 근거 없이 정하지 않음**: 최소 이력 길이는 P0-04의 근거로 정한다.

## 5. Considered Options

### 5.1 상태 정의 (모든 대안에 공통)

#### 5.1.1 Signal Eligibility (신호 적격성) — 이 ADR이 정의

상품 하나, 의사결정 시점 하나(ADR-0001 `decision_at`)에 대해 판단한다.

| 상태 | 정의 |
|---|---|
| `NOT_CALCULABLE` | vol 또는 forecast가 `None` (V1 계산 결과 그대로) |
| `CALCULABLE` | vol과 forecast가 수치로 존재하지만, 거래 허용 정책을 통과하지 못함. **사유 코드가 반드시 붙는다** (예: `INSUFFICIENT_HISTORY`, `VOL_IMPLAUSIBLY_LOW`, `RESUMED_AFTER_GAP`, `STALE_DATA`, `POLICY_NOT_CONFIGURED`) |
| `TRADABLE` | CALCULABLE 조건을 만족하면서 거래 허용 정책을 모두 통과함 |

- **CALCULABLE과 TRADABLE은 계속 구분한다.** 신호 값이 존재한다는 것과 그 값으로 위험을 늘려도 된다는 것은 별개다.
- R0에 있던 보조 상태 `RESTRICTED`는 **R1에서 신호 적격성 상태에서 뺐다.** 같은 이름이 ADR-0003의 Trading State에 있어서 혼동되기 때문이다. R0의 "RESTRICTED (신호)"는 R1의 "`CALCULABLE` + 사유 코드"에 해당한다.

#### 5.1.2 Trading State (거래 상태) — ADR-0003이 정의

`NORMAL` / `RESTRICTED` / `HALTED`는 **계좌·시스템 단위의 운영 상태**다. 신호 적격성과 다른 개념이다.

| 구분 | Signal Eligibility (ADR-0002) | Trading State (ADR-0003) |
|---|---|---|
| 단위 | 상품 × 의사결정 시점 | 계좌(시스템) |
| 결정 근거 | 신호 계산 결과, 이력 길이, vol 타당성, 데이터 신선도·품질 | 위험 한도, 손실 한도, Reconciliation, 주문 상태, 브로커 연결, 수동 Kill Switch |
| 효과 | 그 상품의 **위험 증가 주문**을 막는다 | 계좌 전체의 주문 허용 범위를 정한다 |
| 해제 | 다음 판단 시점에 조건이 충족되면 자동으로 TRADABLE | 사용자 승인과 원인 해소 확인 (ADR-0003 §6.5) |

- 한 상품이 TRADABLE이 아니어도 계좌의 Trading State는 바뀌지 않는다. 반대로 Trading State가 `RESTRICTED`이면 TRADABLE인 상품도 위험을 늘릴 수 없다.
- 여러 상품이 동시에 TRADABLE이 아니게 되는 상황(예: 데이터 공급 중단)을 Trading State 전환 조건으로 삼을지는 ADR-0003에서 정한다 (Q2-8).

### 5.2 대안 A — 고정 최소 관측일 수

- 규칙: 유효한 가격 관측 수 `n ≥ N_min`이면 TRADABLE. 모든 상품과 전략에 같은 `N_min`을 쓴다.
- 장점: 가장 단순하고 검증하기 쉽다.
- 단점: span이 서로 다른 규칙(EWMAC 2/8 … 64/256)을 구분하지 못한다. `N_min`이 임의의 숫자가 되기 쉽다. 결측과 거래 재개를 다루지 못한다. 아주 작은 vol을 직접 걸러내지 못한다.

### 5.3 대안 B — 전략별 최소 관측일 수 + vol 안정화 조건

- 규칙:
  - (B1) 신호 구성별 최소 관측 수. 예: slowest span의 함수 `N_signal = f(slow_span)`. `f`의 형태와 계수는 미정.
  - (B2) vol 최소 표본 수 `N_vol`
  - (B3) vol 타당성 조건. 예: 가격 대비 vol 하한, tick 대비 vol 하한, 단기/장기 비율 하한. 이 조건은 **거래 허용 판단에만** 쓰고 사이징 공식에는 넣지 않는다.
- 장점: 계산 구조(span)와 연결된 근거를 댈 수 있다. 작은 vol 위험을 직접 다룬다.
- 단점: 파라미터가 많다. B3의 비율 조건은 초기에 long-run = 단기라서 효과가 없으므로 B2와 함께 써야 한다.

### 5.4 대안 C — 데이터 길이·품질 기반 거래 허용 상태 정책

- 규칙: 상품별로 다음 정보를 보고 상태를 판단한다.
  - 연속 유효 관측 수
  - 마지막 결측 이후 경과 관측 수 (거래 재개 후 재-warm-up)
  - 데이터 신선도 (마지막 가격의 `data_available_at`, ADR-0001)
  - 데이터 품질 플래그 (공급자 수정, 이상치 등. Phase 1 데이터 계층이 생긴 뒤)
- 장점: 새 상장, 거래 중단·재개, 공급 중단을 일관되게 다룬다. Live 운용에 필요하다.
- 단점: 데이터 계층(현재 없음)과 메타데이터가 필요하다. 상태 전이 규칙이 복잡하다.

### 5.5 비교

| 기준 | A | B | C |
|---|---|---|---|
| 과대 포지션 방지 | 부분적 (관측 수만) | 높음 (작은 vol 직접 처리) | 높음 (B와 결합할 때) |
| 근거 설명 | 약함 (단일 숫자) | span과 연결됨 | 데이터 상태와 연결됨 |
| 결측·재개·신규 상장 | 처리 못 함 | 일부 | 처리함 |
| 구현 복잡도 | 낮음 | 중간 | 높음 (데이터 메타데이터 필요) |
| 계산 함수 변경 필요 | 없음 | 없음 | 없음 |
| 기존 테스트 | 호환 프로필이면 영향 없음 | 같음 | 같음 |

## 6. Proposed Decision

### 6.1 결정 요지

**계산 함수(`volatility`, `forecast`, `combined_forecast`, `research_pipeline`)는 바꾸지 않는다. 그 바깥에 순수 함수로 된 "거래 허용 정책(Tradability Policy)" 계층을 둔다. 정책은 B(전략별 최소 관측 + vol 타당성)를 기본 구조로 하고, C(데이터 상태)의 항목은 데이터 계층이 생기는 대로 같은 틀에 추가한다.**

- 정책의 입력은 V1 signal(vol, forecast)과 그 메타데이터(관측 수, 결측 이력, 신선도)다. 출력은 `NOT_CALCULABLE / CALCULABLE / TRADABLE` 가운데 하나와 **사유 코드**다 (R1에서 `RESTRICTED` 제거, §5.1.1).
- 모든 임계값은 설정 파라미터다. **이 ADR은 숫자를 정하지 않는다.** 최소 관측 수와 vol 하한의 형태와 값은 P0-04에서 표본 크기별 vol 추정 오차 분석 등의 근거를 만든 뒤 사용자가 결정한다.
- 정책 프로필:

| 프로필 | 규칙 | 용도 | 사용할 수 있는 실행 모드 |
|---|---|---|---|
| `V1_COMPAT` | TRADABLE ⇔ CALCULABLE (현재 동작) | **기존 테스트와 기존 연구 결과의 재현 전용** | 기존 V1 API(암묵적), 새 연구 API(명시적 선택). Paper/Live에서는 선택할 수 없음 (§8.0) |
| `RESEARCH` | B 규칙. 임계값은 설정 | 연구 백테스트 | 새 연구 API (명시적 선택) |
| `LIVE` | B + C 규칙, 가장 엄격. **설정이 부족하면 fail-closed** (§6.4) | Paper/Live | Paper, Live |

### 6.2 거래 허용 상태가 아닐 때의 동작

- TRADABLE이 아니면 **위험을 늘리는 거래는 하지 않는다.**
- 이미 보유한 포지션을 유지할지, 줄일지, 청산할지는 **이 ADR이 정하지 않는다.** ADR-0003의 정책(검증된 위험 축소 주문의 조건 포함)을 따른다. 기본값은 미정이다 (Q2-4).
- **거래 부적격 상태에서도 보유 포지션의 손익과 계좌 평가는 계속 계산한다.** 적격성은 "새 위험을 만들 수 있는가"에 대한 판단이지, 평가를 멈추는 조건이 아니다. 평가는 ADR-0001의 회계식을 따른다.
- 평가에 필요한 가격 자체가 없으면 V1처럼 ValueError로 실패한다. 적격성 판단이 가격 결측을 숨기면 안 된다.
- **백테스트에서는 그날을 건너뛰지 않는다.** 날짜를 남겨 두고 거래만 막는다. 현재 V1은 warm-up 날짜를 일별 입력에서 제외한다 (`system_backtest.py:113-121`). 이 방식을 warm-up 이후에 쓰면 보유 포지션의 손익이 누락될 수 있다 (GAP A-05). 그래서 TRADABLE 판단은 "날짜 제외"가 아니라 "거래 차단"으로 표현해야 한다.

### 6.3 연구용 warm-up과 실전 진입 조건의 구분

| 구분 | 연구 (RESEARCH) | 실전 (LIVE) |
|---|---|---|
| 앞부분 이력 | 신호 계산에 모두 쓰되, 성과 평가 시작일은 warm-up 이후로 설정할 수 있음 | 이용 가능한 이력이 부족하면 진입하지 않음 |
| 새 상품 | 상장일부터 이력을 쌓고 기준을 만족하면 거래 | 기준 만족 후에도 사용자 승인을 요구할지는 Q2-5 |
| 거래 재개 | 재-warm-up 관측 수 이후 거래 | 같음 + 데이터 신선도 확인 |

### 6.4 `V1_COMPAT` 사용 제한과 LIVE fail-closed (R1 추가)

**`V1_COMPAT` 사용 제한**

- `V1_COMPAT`는 기존 테스트와 기존 연구 결과를 재현하는 용도로만 쓴다.
- Paper/Live 실행 설정에서 `V1_COMPAT`를 선택하면 **설정 검증 단계에서 ValueError로 거부한다.** 경고만 내고 진행하지 않는다.
- 따라서 `V1_COMPAT`를 이용해 Paper/Live에서 거래 적격성 검사를 우회할 수 없다.
- 프로필 이름이 없거나 알 수 없는 값이면 기본값으로 대체하지 않고 ValueError를 낸다. 새 연구 API에도 기본 프로필은 없다. 암묵적 `V1_COMPAT`는 **기존 V1 API에만** 있다 (§8.0. R1의 "기본값 = `V1_COMPAT`는 Backtest에만 적용"을 R2에서 바꿈).

**LIVE fail-closed**

`LIVE` 프로필에서 다음 가운데 하나라도 부족하면 그 상품은 TRADABLE이 될 수 없다. 상태는 `CALCULABLE`(또는 `NOT_CALCULABLE`)이고, **위험 증가 주문을 차단한다.**

| 부족한 정보 | 사유 코드 |
|---|---|
| warm-up 임계값(최소 관측 수, vol 하한 등)이 설정되지 않음 | `POLICY_NOT_CONFIGURED` |
| 데이터 품질 정보(검증 결과, 품질 플래그)가 없음 | `DATA_QUALITY_UNKNOWN` |
| 시점 정보(`observed_at`, `data_available_at`)가 없어서 신선도와 I-1(ADR-0001)을 판단할 수 없음 | `TIMESTAMP_MISSING` |

- 부족한 설정을 "제한 없음"이나 V1 동작으로 해석하지 않는다. **정보가 부족하면 거래를 막는 쪽으로 판단한다.**
- 이때도 보유 포지션의 손익과 계좌 평가는 계속한다 (§6.2).
- 기존 포지션의 유지·축소·청산은 ADR-0003을 따른다.
- 임계값의 **값**은 정하지 않는다. "값이 설정되어 있어야 한다"는 요건만 정한다.

## 7. Consequences / Trade-offs

**장점**
- 계산 결과는 그대로 두고 "거래해도 되는가"만 별도로 판단하므로 V1 결과 재현성이 유지된다.
- 거래하지 않은 사유가 기록되어 감사할 수 있다.
- ADR-0003의 위험 정책과 같은 "위험 증가 차단" 의미를 공유한다.

**단점**
- 정책 파라미터가 늘어난다. 파라미터마다 근거가 필요하다.
- 거래 허용 기준이 엄격하면 백테스트 초기 성과가 달라지고 비교 기준이 바뀐다. 성과를 보고할 때 정책 프로필을 명시해야 한다.
- "vol 하한으로 사이징"(vol floor)은 이 ADR에 포함하지 않는다. 그것은 금융 공식 변경이므로 별도 승인과 ADR이 필요하다.

## 8. Compatibility with V1

### 8.0 `V1_COMPAT` 적용 범위 (R2, 세 ADR 공통)

> 이 절은 ADR-0001, ADR-0002, ADR-0003에 **같은 내용으로** 들어 있다. 세 ADR의 호환 모드(ADR-0001의 회계 모드, ADR-0002의 정책 프로필, ADR-0003의 사후 검사 모드)는 모두 이 규칙을 따른다. 한 곳을 고치면 세 곳을 함께 고친다.

| 경로 | 규칙 |
|---|---|
| **기존 V1 API** (현재 `src/carver_quant`의 공개 함수. 예: `run_daily_step`, `run_contract_aware_backtest`, `run_ewmac_system_backtest`, `run_prepared_portfolio_backtest`, `run_combined_ewmac_portfolio_backtest`) | 현재의 **입력, 동작, fingerprint를 바꾸지 않는다.** 정책 프로필 인자를 새로 요구하지 않는다. 이 API의 동작이 곧 암묵적 `V1_COMPAT`다 |
| **기존 백테스트 재현** | 기존 V1 API를 그대로 호출(암묵적 `V1_COMPAT`)하거나, 새 API에서 `V1_COMPAT`를 **명시적으로** 선택해 쓸 수 있다 |
| **새 연구 API** (ADR-0001~0003을 구현하는 새 진입점) | 정책 프로필을 **명시적으로** 선택해야 한다 (`RESEARCH`, 또는 재현 목적의 `V1_COMPAT`). **기본값은 없다.** 누락하면 ValueError |
| **Paper/Live** | `V1_COMPAT`를 선택할 수 없다 (ValueError). 허용되는 프로필은 `LIVE`뿐이다. 기존 V1 API는 거래 전 안전 검사가 없으므로 Paper/Live의 주문 경로에서 호출하지 않는다 |
| **우회 금지** | 프로필 누락, 알 수 없는 값, 빈 문자열, `None`, 대소문자 변형 등 어떤 형태로도 기본값이나 `V1_COMPAT`로 대체되지 않는다. Paper/Live에서는 설정 검증 단계에서 시작을 거부한다 (fail-closed) |
| **확인 수준** | 구현 전이므로 기존 306개 테스트 통과, 기존 실행 결과 보존, 기존 fingerprint 보존은 모두 **INFERRED**다. 보존 방법은 P0-03에서 정한다 (ADR-0001 Q1-9) |

### 8.1 그 밖의 영향

| 항목 | 영향 |
|---|---|
| 기존 306개 테스트 | 기존 V1 API를 바꾸지 않으므로(암묵적 `V1_COMPAT`) 변경 없음 (INFERRED. 구현 전이므로 회귀 확인 필요). 특히 `test_research_pipeline_has_warmup_period`는 *계산 가능성*을 검증하는 테스트로 그대로 의미가 있다 |
| `V1_COMPAT`의 범위 | §8.0 |
| fingerprint | 프로필을 설정에 추가하면 입력 fingerprint가 바뀔 수 있다. `V1_COMPAT`에서는 기존 fingerprint를 보존해야 한다. 방법은 ADR-0001 Q1-9와 함께 P0-03에서 정한다 |
| 계산 함수와 상수 | 변경 없음 |
| 짧은 테스트 데이터 | `RESEARCH`·`LIVE` 프로필 테스트에는 더 긴 합성 시계열이 필요하다. 기존 데이터는 바꾸지 않는다 |
| `system_backtest`의 warm-up 건너뛰기 | `V1_COMPAT`에서는 유지. 다른 프로필에서는 "날짜 유지 + 거래 차단"을 쓴다. 구현 시점에 결정한다 |

## 9. Financial Integrity Implications

- **과대 포지션**: 짧은 이력의 작은 vol로 인한 레버리지 폭증을 정책 단계에서 막는다 (AT-0002-1).
- **Look-ahead**: 정책 판단은 판단 시점까지 알려진 정보만 써야 한다. 관측 수, 결측 이력, 신선도 모두 PIT로 계산한다. 미래 데이터의 결측 여부를 보고 과거 거래를 막으면 안 된다.
- **결측 처리**: V1의 fail-fast(가격이 없으면 ValueError)는 유지한다. 정책은 "값은 있지만 신뢰도가 낮은" 경우를 다룬다. 값을 보간하지 않는다.
- **성과 편향**: 정책이 어려운 구간(거래 재개 직후 등)을 체계적으로 피하면 백테스트 성과가 실제보다 좋아 보일 수 있다. 정책은 사전에 정하고, 결과를 본 뒤 조정하지 않는다.

## 10. Acceptance Criteria

### AT-0002-1 짧은 이력에서 아주 작은 vol이 추정되는 경우 (시나리오 3)

가상의 상품을 쓴다. 특정 실제 상품의 사양이 아니다: 가격 약 350 pt, M = 250,000 IC/pt/ct, fx = 1, 계좌 50,000,000, 연 vol 목표 0.20. 일간 현금 목표 = 50,000,000 × 0.20 ÷ √256 = **625,000 BC/d**.

- **입력 가격**: 350.00, 350.05, 350.15, 350.20, 350.30 (변화 0.05, 0.10, 0.05, 0.10)
- **V1 실행 결과** (CONFIRMED, V1 함수를 실행해 확인. 독립 산술과 일치):

| index | blended vol (pt/d) | combined forecast | 평균 포지션 = 625,000 ÷ (vol × 250,000) | 목표 = 평균 × forecast ÷ 10 | 반올림 | gross leverage = 목표 × 350 × 250,000 ÷ 50,000,000 |
|---|---|---|---|---|---|---|
| 0, 1 | None | None | — | — | — | NOT_CALCULABLE |
| 2 | 0.035355 (= 표본 {0.05, 0.10}의 표준편차, 독립 계산 일치) | 8.358 | 70.71 | 59.10 | **59** | **103.25배** |
| 4 | 0.029139 | 14.478 | 85.79 | 124.22 | **124** | **217.0배** |
| 비교: vol을 가격의 1%(3.5 pt/d)로 가정 | 3.5 | (20 가정) | 0.714 | 1.43 | 1 | 1.75배 |

- **관찰**: index 2에서 long-run vol = 단기 vol이므로 단기/장기 비율은 1.0이다. **비율 조건만으로는 잡아낼 수 없다.** 관측 수 조건(B1/B2)이나 가격·tick 대비 vol 하한(B3)이 필요하다.
- **기대 출력**:
  - `V1_COMPAT`: index 2부터 TRADABLE (현재 동작 재현)
  - `RESEARCH`·`LIVE`: 관측 수가 임계값 미만이면 index 2와 4는 `CALCULABLE`이고, 사유 코드는 `INSUFFICIENT_HISTORY` 또는 `VOL_IMPLAUSIBLY_LOW` (R0의 "`CALCULABLE` 또는 `RESTRICTED`"를 R1 상태 정의에 맞춰 정정)
- **전제**: 임계값은 테스트에서 명시적 파라미터로 주입한다. 테스트가 특정 운영 수치를 확정하는 것이 아니다.
- **예외**: 정책 파라미터가 비유한값이거나 음수이면 ValueError
- **새 테스트 후보**: `test_compat_profile_matches_v1_calculability`, `test_short_history_is_calculable_but_not_tradable`, `test_vol_ratio_check_alone_misses_initial_underestimate`

### AT-0002-2 CALCULABLE과 TRADABLE 분리

- **입력**: forecast와 vol이 모두 존재하지만 관측 수가 임계값 미만인 날
- **기대 출력**: 상태 `CALCULABLE`, 거래량 0 (보유가 0이면 계속 0). signal 값 자체는 V1과 같음
- **새 테스트 후보**: `test_signal_values_unchanged_by_tradability_policy`

### AT-0002-3 warm-up 이후 거래 불가 상태가 다시 생긴 날의 손익 보존

- **입력**: 보유 5 ct, 어느 날 정책이 그 상품을 TRADABLE이 아니라고 판단 (`CALCULABLE` 또는 `NOT_CALCULABLE`)
- **기대 출력**: 그날 보유분 gross PnL과 계좌 평가는 계산된다 (날짜 유지). 위험 증가 거래만 차단된다. 기존 포지션의 축소 여부는 ADR-0003 정책의 결과다
- **V1 비교**: V1 준비 단계는 forecast가 `None`인 날을 건너뛴다. 이 테스트는 새 프로필에서 손익이 누락되지 않음을 확인한다
- **새 테스트 후보**: `test_ineligible_day_keeps_holding_pnl` (R0 이름 `test_restricted_day_keeps_holding_pnl`을 R1 용어에 맞춰 변경)

### AT-0002-4 거래 재개와 결측 구간

- **입력**: N일 연속 가격 후 공백, 그다음 재개 가격들
- **기대 출력**: `LIVE` 프로필에서 재개 후 재-warm-up 관측 수를 채우기 전까지 `CALCULABLE`, 사유 `RESUMED_AFTER_GAP` (R1 용어로 정정)
- **미정**: "공백"의 정의(영업일 달력 기준인지, 일정 기간 이상인지)는 Q2-3과 달력 정책(D-07)에 의존한다

### AT-0002-5 vol = 0과 아주 작은 vol

- vol = 0: V1 forecast는 `None` → `NOT_CALCULABLE` (현재 동작 유지)
- vol > 0이지만 가격 또는 tick 대비 하한 미만: `CALCULABLE`, 사유 `VOL_IMPLAUSIBLY_LOW` (R1 용어로 정정). 하한의 정의 방식(가격 비율인지, tick 배수인지)은 Q2-2

### AT-0002-6 LIVE 프로필에 warm-up 설정이 없는 경우 (R1 추가, 인수 테스트 명세 3)

- **입력**:
  - 프로필 `LIVE`. warm-up 임계값(최소 관측 수, vol 하한)이 **설정되지 않음** (`None`)
  - 데이터 품질 정보와 타임스탬프는 있음
  - AT-0002-1과 같은 가격 5개. index 4에서 vol 0.029139, forecast 14.478 (V1 계산값, CONFIRMED)
  - 경우 (a) 보유 0, V1 사이징 목표 +124 ct. 경우 (b) 보유 +5 ct, 목표 +124 ct. 경우 (c) 보유 +5 ct, 목표 +2 ct
- **기대 출력**:

| 경우 | 신호 적격성 | 위험 증가 주문 | 손익·계좌 평가 | 축소 주문 |
|---|---|---|---|---|
| (a) | `CALCULABLE`, `POLICY_NOT_CONFIGURED` | 차단. 주문 0 | 계산함 (보유 0이면 보유분 손익 0) | 해당 없음 |
| (b) | 같음 | 차단. +5 유지 | 보유 5 ct의 손익을 계산함 | 해당 없음 |
| (c) | 같음 | 해당 없음 | 계산함 | −3 ct 주문은 이 ADR이 허용하지도 막지도 않음. ADR-0003의 검증된 위험 축소 조건을 따름 |

- **판단 근거**: §6.4 LIVE fail-closed. 설정 누락을 "제한 없음"으로 해석하면 (a)에서 gross leverage 217배(AT-0002-1)의 포지션을 그대로 낸다
- **예외조건**:
  - 설정된 임계값이 비유한값이거나 음수이면 ValueError (설정 오류이므로 시작 단계에서 거부)
  - 평가 가격이 없으면 ValueError (적격성이 가격 결측을 숨기지 않음)
  - 같은 입력을 `RESEARCH` 프로필로 실행할 때도 임계값이 없으면 같은 결과를 낼지는 Q2-9
- **새 테스트 후보**: `test_live_profile_without_warmup_config_blocks_risk_increase`, `test_live_profile_without_warmup_config_keeps_valuation`

### AT-0002-7 Paper/Live에서 `V1_COMPAT` 선택 (R1 추가)

- **입력**: 실행 모드 Paper(또는 Live), 프로필 `V1_COMPAT`
- **기대 출력**: 설정 검증 단계에서 ValueError. 주문 경로가 시작되지 않음
- **변형 (R2 수정)**: 프로필 미지정 → 새 연구 API에서도 ValueError(기본값 없음), Paper/Live에서도 ValueError. 기존 V1 API는 프로필 인자가 없고 현재 동작(암묵적 `V1_COMPAT`)을 유지한다. 알 수 없는 값·빈 문자열·대소문자 변형도 ValueError
- **판단 근거**: §6.4, §8.0. `V1_COMPAT`나 프로필 누락으로 적격성 검사를 우회하는 것을 막는다
- **새 테스트 후보**: `test_v1_compat_profile_rejected_in_paper_and_live`, `test_new_research_api_requires_explicit_profile`, `test_invalid_profile_value_is_rejected`, `test_existing_v1_api_signature_unchanged`

## 11. Open Questions

| ID | 질문 | 결정 주체 |
|---|---|---|
| Q2-1 | 최소 관측 수의 형태와 값: slowest span의 배수인가, vol 표본 수인가, 둘 다인가? | 사용자 (P0-04 근거 후) |
| Q2-2 | vol 타당성 하한을 무엇으로 정의할 것인가: 가격 대비 비율, tick 배수, 장기 vol 대비 비율 (long-run이 충분히 쌓인 뒤)? | 사용자 (P0-04 근거 후) |
| Q2-3 | 결측과 거래 중단의 정의, 재-warm-up 관측 수 | D-07 달력 정책과 함께 |
| Q2-4 | 거래 불가 상태에서 기존 포지션은 유지, 축소, 청산 중 무엇으로 할 것인가? | 사용자 (ADR-0003과 함께) |
| Q2-5 | LIVE에서 새 상품을 처음 거래할 때 사용자 승인을 요구할 것인가? | 사용자 |
| Q2-6 | long-run vol의 `min_periods=1`과 slow EWMA의 `min_periods` 미지정을 그대로 둘 것인가? 바꾸면 계산 공식 변경이므로 승인이 필요하다 | 사용자 (P0-04 이후) |
| Q2-7 | 연구 백테스트에서 성과 평가 시작일을 warm-up 이후로 옮길 때 그 구간을 결과에 어떻게 표시할 것인가? | P0-03 계약 |
| Q2-8 | 여러 상품이 동시에 TRADABLE이 아니게 될 때(데이터 공급 중단 등) 계좌 Trading State를 바꿀 것인가? | ADR-0003 / 사용자 |
| Q2-9 | `RESEARCH` 프로필에서 임계값이 없을 때도 fail-closed로 할 것인가, 아니면 설정 오류로 실행을 거부할 것인가? | 사용자 |

## 12. Related Code and Documents

- 코드: `volatility.py:17-41, 44-95, 97-145, 147-226`, `forecast.py:94-157, 160-275`, `combined_forecast.py:89-165`, `research_pipeline.py:41-269`, `system_backtest.py:113-121, 318-324`, `position.py:58-93`
- 테스트: `tests/test_research_pipeline.py:60-84`, `tests/test_volatility.py` (`test_long_run_average_uses_only_available_history`), `tests/test_forecast.py:119` (`test_zero_volatility_produces_no_forecast`)
- 문서: [V1_GAP_ANALYSIS.md](../quality/V1_GAP_ANALYSIS.md) F-01, A-05; [V1_DATA_FLOW.md](../architecture/V1_DATA_FLOW.md) §6
- 관련 ADR: [0001](0001-execution-timing-and-valuation.md) (`data_available_at`), [0003](0003-pretrade-risk-policy.md) (위험 증가 차단 의미)

## 13. 개정 이력

| 개정 | 날짜 | 내용 |
|---|---|---|
| R0 | 2026-10-16 | 최초 제안 (P0-02A) |
| R1 | 2026-10-16 | (1) Signal Eligibility(상품 단위)와 Trading State(계좌 단위, ADR-0003)를 분리. 신호 상태에서 `RESTRICTED`를 빼고 "`CALCULABLE` + 사유 코드"로 표현. AT-0002-1·3·4·5의 상태 표기를 이에 맞춰 정정 (숫자는 그대로). (2) `V1_COMPAT`를 Backtest 재현 전용으로 제한하고 Paper/Live에서 거부. (3) LIVE fail-closed 규칙과 사유 코드 추가. (4) 거래 부적격 상태에서도 손익·계좌 평가를 계속한다고 명시. 기존 포지션 처리는 ADR-0003에 위임. (5) AT-0002-6, AT-0002-7 추가 |
| R2 | 2026-10-16 | (1) `V1_COMPAT` 적용 범위 §8.0 추가 (세 ADR 공통). (2) R1의 "기본값 = `V1_COMPAT`는 Backtest에만 적용"을 "암묵적 `V1_COMPAT`는 기존 V1 API에만 있고, 새 연구 API는 프로필을 명시해야 함"으로 변경. 프로필 표의 사용 범위 열과 AT-0002-7 변형을 이에 맞춤. (3) 기존 306개 테스트·fingerprint 호환은 INFERRED 유지 |
| ACCEPTED | 2026-10-16 | 상태를 PROPOSED에서 **ACCEPTED**로 변경 (사용자의 명시적 승인, 범위는 §2). 결정 내용은 R2 그대로이며 바꾸지 않았다. 문서 정리: §13(개정 이력)이 §12 앞에 있던 순서 오류를 바로잡아 문서 끝으로 옮김 (R1에서 생긴 서식 오류, 내용 변경 없음) |
