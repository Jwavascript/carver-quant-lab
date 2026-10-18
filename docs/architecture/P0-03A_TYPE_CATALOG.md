# P0-03A 타입 카탈로그 (Type Catalog)

| 항목 | 내용 |
|---|---|
| 작업 | P0-03A Common Domain Contracts Design |
| 기준 커밋 | `24cae00` |
| 작성일 | 2026-10-17 |
| 개정 | R1, R1-FIX, R2 (2026-10-17. R2 = P0-03A-FINAL: D3A-19·49·50 핵심 원칙 승인 반영, 판정 FINAL BLOCKED. §8) |
| 문서 상태 | **PROPOSED (사용자 검토 대기).** 구현 승인이 아니다. D3A-19·49·50의 핵심 원칙만 2026-10-17 사용자 승인 (`APPROVED_PRINCIPLE`) |
| 중심 문서 | [P0-03A_DOMAIN_CONTRACTS.md](P0-03A_DOMAIN_CONTRACTS.md) (설계 근거와 불변조건 `INV-xx`) |
| 미결정 사항 | [P0-03A_DECISION_REGISTER.md](P0-03A_DECISION_REGISTER.md) (`D3A-xx`) |
| 인수 테스트 | [../quality/P0-03A_CONTRACT_ACCEPTANCE_SPEC.md](../quality/P0-03A_CONTRACT_ACCEPTANCE_SPEC.md) (`AT-03A-xx`, **명세만, 미구현**) |

## 0. 읽는 법

- **이 카탈로그의 필드 목록은 설계 후보이지 구현 승인이 아니다.** 타입 이름은 모두 가칭이다. `carver_quant.lab.domain`은 설명용 가칭이며 패키지는 만들지 않았다.
- "자료형 후보"는 Python 표현의 **후보**다. 최종 자료형, 특히 가격·금액·환율의 수치 표현(`float` / `Decimal` 등)은 ADR-0011 Q11-6이 정한다 (D3A-11). 표에서는 이를 `Num`으로 적는다.
- "필수 여부" 표기:

| 표기 | 의미 |
|---|---|
| 필수 (A) | ACCEPTED ADR의 승인된 원칙(또는 규칙별 승인 표)이 그 정보의 존재를 요구한다. 근거를 함께 적는다. ADR-0001~0003은 §5.1·§6의 정책 원칙 전체가 승인 범위다 |
| (ADR 본문) | ACCEPTED ADR의 본문(규칙 표, 인수 테스트 명세)에 있지만 승인 원칙 목록 밖인 근거. 승인된 것처럼 쓰지 않는다. 확인 필요 (D3A-48) |
| (P: D3A-xx) | 2026-10-17 사용자가 핵심 원칙만 승인한 P0-03A 결정(D3A-19, D3A-49, D3A-50)이 근거인 요구. ACCEPTED ADR이 아니다. 필드 형태와 세부는 미결정이다. R2 독립 검토 뒤에는 이 표기로 필수 여부를 정한 필드가 없고(판정 원칙과 기록 필드를 구분, 기록 필드는 D3A-19.8), 불변조건 칸에서만 쓴다 |
| 필수 (제안) | 이 문서의 제안이다. 승인되지 않았다 |
| 선택 (제안) | 있을 수도 없을 수도 있다는 제안 |
| 미결정 | 결정되지 않았다. 연결된 질문을 적는다 |
| 조건부 | 다른 필드 값에 따라 필수 |

- "승인 구분"의 [ACCEPTED]는 ACCEPTED ADR 원칙을 그대로 적용한 부분, [APPROVED_PRINCIPLE]은 2026-10-17 승인된 P0-03A 핵심 원칙(D3A-19, D3A-49, D3A-50)을 적용한 부분, [APPROVED_PRINCIPLE · 적용 보류]는 원칙은 승인되었지만 ACCEPTED ADR과의 규범 충돌이 해소될 때까지 쓰지 않는 부분(D3A-49 원칙 (2), 결정 등록부 §9 CA-49), [제안]은 이 문서가 새로 제안한 부분이다 (`NOT_APPROVED`).
- 예외의 이름(`INVALID_VALUE` 등)은 [중심 문서 §12.2](P0-03A_DOMAIN_CONTRACTS.md)의 오류 분류 후보다. Python 예외 클래스는 구현하지 않았다 (D3A-34). V1 관례에 따라 모두 `ValueError` 계열로 둘지는 미결정이다.
- 기본값: **이 카탈로그의 어떤 필드에도 기본값을 정하지 않는다.** 기본값이 필요한 것처럼 보이는 곳은 미결정으로 표시했다.

## 1. 타입 목록

| ID | 타입 (가칭) | 분류 | 영역 |
|---|---|---|---|
| TC-A1 | `InstrumentId` | Identifier | Identity & Instrument |
| TC-A2 | `ContractId` | Identifier | Identity & Instrument |
| TC-A3 | `VenueId` | Identifier | Identity & Instrument |
| TC-A4 | `TradableUnitRef` | Identifier (tagged) | Identity & Instrument |
| TC-A5 | `AssetType` | Enumeration (판별자) | Identity & Instrument |
| TC-A6 | `QuantityUnit` | Enumeration | Identity & Instrument |
| TC-A7 | `InstrumentIdentity` | Value Object (합성 구성요소) | Identity & Instrument |
| TC-A8 | `QuantityConvention` | Reference Data (구성요소) | Identity & Instrument |
| TC-A9 | `PriceIncrementRule` | Reference Data (구성요소) | Identity & Instrument |
| TC-A10 | `FuturesInstrument` | Reference Data (Union 변형) | Identity & Instrument |
| TC-A11 | `FuturesContract` | Reference Data (거래 단위 사양) | Identity & Instrument |
| TC-A12 | `EtfInstrument` | Reference Data (Union 변형) | Identity & Instrument |
| TC-A13 | `Instrument` | Tagged Union | Identity & Instrument |
| TC-A14 | `TradingConstraintSet` | Reference Data | Identity & Instrument |
| TC-A15 | `ReferenceProvenance` | Value Object (출처) | Identity & Instrument |
| TC-B1 | `Quantity` | Value Object | Values & Units |
| TC-B2 | `Price` | Value Object | Values & Units |
| TC-B3 | `ContractMultiplier` | Value Object | Values & Units |
| TC-B4 | `CurrencyCode` | Value Object | Values & Units |
| TC-B5 | `MoneyAmount` | Value Object | Values & Units |
| TC-C1 | `PriceKind` | Enumeration | Market Observation |
| TC-C2 | `ValueProvenance` | Enumeration | Market Observation / Input Bundles |
| TC-C3 | `ObservationMeta` | Value Object (메타데이터) | Market Observation |
| TC-C4 | `RawPriceObservation` | Observation | Market Observation |
| TC-C5 | `MarketQuote` | Observation | Market Observation |
| TC-C6 | `AdjustedPriceSeries` | Derived (연구 전용) | Research-derived |
| TC-C7 | `FuturesRollEvent` | Reference Event | Reference Events |
| TC-C8 | `CorporateAction` | Reference Event (Union) | Reference Events |
| TC-C9 | `DataVintageRef` | Reference (실행 manifest용) | Market Observation |
| TC-D1 | `Instant` | Value Object | Time & Calendar |
| TC-D2 | `ZonedLocalTime` | Value Object (입력 형태) | Time & Calendar |
| TC-D3 | `TradingDayLabel` | Value Object | Time & Calendar |
| TC-D4 | `ExchangeCalendar` | Reference Data | Time & Calendar |
| TC-D5 | `TradingSession` | Reference Data | Time & Calendar |
| TC-D6 | `PublicationExpectation` | Reference Data / Assumption | Time & Calendar |
| TC-D7 | `AccountSchedule` | Policy Input (계좌 설정) | Time & Calendar |
| TC-D8 | `MarketDataStatus` | Enumeration | Time & Calendar |
| TC-D9 | `DataStatusAssessment` | Derived Record | Time & Calendar |
| TC-E1 | `FxRate` | Value Object | FX |
| TC-E2 | `FxObservation` | Observation | FX |
| TC-E3 | `FxRole` | Enumeration | FX |
| TC-E4 | `ValuationFxSet` | Derived Record (선택 결과) | FX |
| TC-E5 | `DecisionFxSnapshot` | Derived Record (선택 결과) | FX |
| TC-F1 | `MarketObservationSet` | Input Contract (묶음 1) | Input Bundles |
| TC-F2 | `ExecutionAssumptionSet` | Input Contract (묶음 2) | Input Bundles |
| TC-F3 | `DataLatencyAssumption` | Execution Assumption | Input Bundles |
| TC-F4 | `RiskPolicyInput` | Input Contract (묶음 3) | Input Bundles |
| TC-F5 | `PolicyProfile` | Enumeration | Input Bundles |
| TC-F6 | `ValuationPolicySelection` | Policy Input | Input Bundles |
| TC-F7 | `MarginRequirementRecord` | Reference Data / Assumption (묶음 3) | Input Bundles |
| TC-F8 | `ExplicitRiskBudgetSeries` | Policy Input (**자리표시자, 비허용**) | Input Bundles |

### 1.1 작업 명세의 후보 이름과 이 카탈로그의 대응

| 작업 명세 후보 | 이 카탈로그 | 합치거나 바꾼 이유와 금융적 영향 |
|---|---|---|
| `InstrumentId` | TC-A1 | 그대로 |
| `TradableUnitId` | TC-A4 `TradableUnitRef` | ETF는 상품 ID가 곧 거래 단위이므로(ADR-0006 §6.2 표) 별도 ID를 새로 만들지 않고 상품 ID를 명시적으로 감싼다. 선물은 `ContractId`를 감싼다. 표현은 D3A-03 |
| `ContractId` | TC-A2 | 그대로 |
| `AssetType` | TC-A5 | 그대로 |
| `InstrumentSpec` | TC-A13 `Instrument` (= TC-A10 \| TC-A12) | **V1 `carver_quant.instrument.InstrumentSpec`과 이름이 같으므로 쓰지 않는다** (D3A-01). 같은 이름이면 같은 의미라고 오해할 위험이 있다 |
| `FuturesSpec` | TC-A10 `FuturesInstrument` + TC-A11 `FuturesContract` | ADR-0006의 가칭을 따른다. 상품 사양과 월물 사양을 나눠야 월물별 `M[c]`(ADR-0001 R2)와 만기를 표현할 수 있다 |
| `ETFSpec` | TC-A12 `EtfInstrument` | ADR-0006의 가칭을 따른다 |
| `TradingConstraints` | TC-A14 `TradingConstraintSet` | 시장·브로커 의존 값을 출처·`as_of`가 있는 참조 데이터로 둔다 (I6-11) |
| `RawPriceObservation` | TC-C4 | 그대로 |
| `AdjustedPriceObservation` / 조정 시계열 계약 | TC-C6 `AdjustedPriceSeries` | 조정 가격은 개별 관측이 아니라 `as_of`에 묶인 **snapshot 시계열**이다 (ADR-0004 §6.4). 개별 "관측"으로 만들면 서로 다른 snapshot의 값을 섞어 차분할 위험이 생긴다 (INV-28) |
| `MarketQuote` | TC-C5 | 그대로 |
| `PriceKind` | TC-C1 | 그대로. 단 "평가가격"과 "조정 가격"은 값에 넣지 않는다 |
| `MarketObservationMetadata` | TC-C3 `ObservationMeta` | 이름만 줄임 |
| `DataVintageReference` | TC-C9 `DataVintageRef` | 관측 레코드가 아니라 실행 manifest에 둔다 (ADR-0011 FP-11, FP-12) |
| `ObservedAt`, `DataAvailableAt`, `DecisionAt`, `ValuationAt` | TC-D1 `Instant` + 역할 이름이 붙은 필드 | 역할별 별도 타입을 둘지는 D3A-16. 별도 타입이 막을 수 있는 오류(역할 바꿔 넣기)는 시각 순서 불변조건과 명시적 인자로 일부 보완한다 |
| `MarketSessionRef` | TC-D5 `TradingSession`의 `session_id` 참조 | 상태 기록(TC-D9)의 `reference_session` 필드로 쓴다 |
| `TradingDayLabel` | TC-D3 | 거래소를 함께 가진다 (라벨은 그 달력 안에서만 의미) |
| `PublicationExpectation` | TC-D6 | 그대로 |
| `MarketDataStatus` | TC-D8 | 그대로 (정확히 네 값) |
| `DataFreshness` | TC-D9 `DataStatusAssessment`의 경과 시간·사유 필드 | 신선도는 상태 판정과 같은 입력에서 나오므로 같은 기록에 둔다. 임계값 비교 결과(`STALE_DATA`)는 정책 계층의 출력이다 (ADR-0002) |
| `CurrencyCode` | TC-B4 | 그대로 |
| `MoneyAmount` | TC-B5 | 그대로 |
| `FXQuote`, `FXObservation` | TC-E1 `FxRate` + TC-E2 `FxObservation` | 방향을 가진 값(`FxRate`)과 시각·출처를 가진 관측(`FxObservation`)을 나눴다. 환율 bid/ask는 환전 실행(P0-03B)에서 필요하면 다룬다 |
| `BaseCurrency` | 별도 타입 없음. 계좌의 속성인 `CurrencyCode` | BC는 계좌가 정한다. 하드코딩하지 않는다 (Q8-9) |
| `ValuationFXReference` | TC-E4 `ValuationFxSet`의 통화별 항목 | 평가 주기마다 통화별 정확히 하나라는 규칙(X8-5)을 집합 단위로 검사하기 위해 묶었다 |

---

## 2. Identity & Instrument

### TC-A1 `InstrumentId` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 신호·포트폴리오·상품 사양의 대상이 되는 논리 상품을 식별한다 |
| 분류 | Identifier (Value Object) |
| 입력·출력 관계 | 문자열 → 식별자 값. 같은 타입끼리만 비교한다 [제안] |
| 예상 예외 | 빈 값 또는 공백만 있는 값 → `INVALID_VALUE` |
| 참조하는 타입 | 없음 |
| V1 대응 | `InstrumentSpec.symbol` (`instrument.py:7`, 빈 문자열 거부 `:13-14`). 포트폴리오 dict 키와 일치 검사 (`portfolio_system_backtest.py:98-105`) |
| 관련 ADR·질문 | ADR-0006 §6.2, 승인 원칙 4. D3A-02 |
| 승인 구분 | [ACCEPTED] 상품 ID라는 개념과 월물 ID와의 구분. [제안] 별도 타입, 형식 규칙 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `value` | `str` | 필수 (A: ADR-0006 §6.2 "내부 상품 ID") | — | 내부 논리 상품 식별자. 상품 참조 데이터가 부여 | 상품 존속 기간 동안 바뀌지 않음 [제안] | 비어 있지 않음. 형식·대소문자·고유 범위는 D3A-02. 문자열에서 의미를 해석하지 않음 [제안] |

### TC-A2 `ContractId` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 선물의 개별 만기 월물(거래 단위)을 식별한다 |
| 분류 | Identifier |
| 입력·출력 관계 | 문자열 → 식별자 값. 소속 상품과 만기는 ID에서 해석하지 않고 `FuturesContract`(TC-A11)에서 찾는다 [제안] |
| 예상 예외 | 빈 값 → `INVALID_VALUE` |
| 참조하는 타입 | 없음 |
| V1 대응 | `ContractPrice.contract` (`futures_data.py:9`, 빈 값 거부 `:13-14`), `RollEvent.old_contract`·`new_contract` (`:23-24`), `BackAdjustedPrice.active_contract` (`:42`), quote·월물 포지션 dict의 키 (`roll_execution.py:39`, `contract_aware_daily_step.py:49`) |
| 관련 ADR·질문 | ADR-0006 I6-3, 승인 원칙 4. D3A-02 |
| 승인 구분 | [ACCEPTED] 월물 ID와 상품 ID의 구분, 월물 ID 필수. [제안] 별도 타입 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `value` | `str` | 필수 (A: I6-3) | — | 월물 식별자. 계약 사양이 바뀌면 다른 ID (ADR-0001 §6.2 전제조건) | 월물 존속 기간 동안 불변 | 비어 있지 않음. 고유 범위(거래소 안 / 전역)는 D3A-02 |

### TC-A3 `VenueId` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 거래소를 식별하고 거래소 달력과 연결한다 |
| 분류 | Identifier |
| 입력·출력 관계 | 문자열 → 식별자. `ExchangeCalendar`(TC-D4)를 찾는 키 |
| 예상 예외 | 빈 값 → `INVALID_VALUE` |
| 참조하는 타입 | 없음 |
| V1 대응 | 없음. V1 변환 시 "제공되지 않음" (ADR-0006 §6.7) |
| 관련 ADR·질문 | ADR-0006 §6.2 (`InstrumentIdentity`의 거래소), ADR-0007 §6.8 (거래소 → 달력 → 세션). D3A-02, D3A-20 |
| 승인 구분 | [ACCEPTED] 상품 식별 정보에 거래소가 있음. [제안] 별도 타입 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `value` | `str` | 필수 (제안) | — | 거래소 식별자 (MIC 같은 표준을 쓸지는 D3A-02) | 불변 | 비어 있지 않음 |

### TC-A4 `TradableUnitRef` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 포지션·quote·체결·평가가격·증거금의 키가 되는 거래 단위를 가리킨다 |
| 분류 | Identifier (tagged union) |
| 입력·출력 관계 | (`kind`, ID) → 참조. raw 관측, quote, (P0-03B) 포지션·체결 기록의 키 |
| 예상 예외 | `kind`와 ID 종류 불일치, 선물 상품 ID를 월물 자리에 넣음 → `IDENTITY_MISMATCH`. 알 수 없는 `kind` → `UNSUPPORTED_OR_UNAPPROVED` |
| 참조하는 타입 | TC-A1, TC-A2 |
| V1 대응 | 없음. V1은 월물 이름 문자열만 쓰고 ETF가 없다 |
| 관련 ADR·질문 | ADR-0006 §6.2 표 (거래 단위 키), I6-3, I6-4. D3A-03 |
| 승인 구분 | [ACCEPTED] 선물은 월물 ID, ETF는 상품 ID가 거래 단위. [제안] tagged 표현 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `kind` | 열거 (`FUTURES_CONTRACT`, `ETF_LISTING`) | 필수 (제안) | — | 거래 단위 종류 | — | 알 수 없는 값 거부 |
| `contract_id` | `ContractId` | 조건부: `kind = FUTURES_CONTRACT`이면 필수 (A: I6-3), 아니면 없음 | — | 선물 월물 | — | 그 상품의 월물 체인에 있어야 함 (경계에서 참조 데이터로 검사, A: I6-3) |
| `instrument_id` | `InstrumentId` | 조건부: `kind = ETF_LISTING`이면 필수 (A: ADR-0006 §6.2 표). `FUTURES_CONTRACT`에서 소속 상품 ID를 함께 둘지는 미결정 (D3A-03) | — | ETF 상장 종목 (또는 선물의 소속 상품) | — | ETF의 경우 `EtfInstrument`의 ID여야 함 |

### TC-A5 `AssetType` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 상품 Tagged Union의 판별자 |
| 분류 | Enumeration |
| 입력·출력 관계 | 값 → 변형 선택. 처리하지 않은 값은 기본 분기에서 거부 |
| 예상 예외 | 알 수 없는 값, `None`, 빈 문자열, 대소문자 변형 → `UNSUPPORTED_OR_UNAPPROVED` [제안] |
| 참조하는 타입 | 없음 |
| V1 대응 | 없음 (V1은 자산 유형이 없음) |
| 관련 ADR·질문 | ADR-0006 §6.1, §6.2, 승인 원칙 1. Q6-1 (첫 구현 유형) |
| 승인 구분 | [ACCEPTED] 판별자 `FUTURES`, `ETF` (가칭), 없거나 모르는 값 거부. [제안] 대소문자 변형 거부 |

| 값 | 의미 | 근거 |
|---|---|---|
| `FUTURES` | 선물 상품 | ADR-0006 §6.2 |
| `ETF` | 상장지수펀드 | ADR-0006 §6.2 |

새 자산 유형은 새 변형과 별도 결정으로만 추가한다 [제안].

### TC-A6 `QuantityUnit` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 수량의 단위를 표시한다 |
| 분류 | Enumeration |
| 입력·출력 관계 | `QuantityConvention`, `Quantity`가 참조 |
| 예상 예외 | 알 수 없는 값 → `UNSUPPORTED_OR_UNAPPROVED` |
| V1 대응 | 없음 (V1 수량은 단위 표시 없는 정수 계약 수) |
| 관련 ADR·질문 | ADR-0006 §6.2 (`QuantityConvention`), I6-5 |
| 승인 구분 | [ACCEPTED] `CONTRACT`, `SHARE` |

| 값 | 의미 | 쓰는 변형 |
|---|---|---|
| `CONTRACT` | 계약 수 | `FuturesInstrument` |
| `SHARE` | 주 수 | `EtfInstrument` |

### TC-A7 `InstrumentIdentity` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 상품의 정체성(식별자, 거래소, 거래통화)을 담는 공통 구성요소 |
| 분류 | Value Object (합성 구성요소) |
| 입력·출력 관계 | 모든 `Instrument` 변형이 포함한다 |
| 예상 예외 | 필수 필드 누락 → `MISSING_REQUIRED`. 통화 코드 오류 → `INVALID_VALUE` |
| 참조하는 타입 | TC-A1, TC-A3, TC-B4 |
| V1 대응 | `InstrumentSpec.symbol`, `InstrumentSpec.currency` (`instrument.py:7-8`). V1 currency는 계산에 쓰이지 않음 (ADR-0006 §3.1) |
| 관련 ADR·질문 | ADR-0006 §6.2, I6-10. D3A-02, D3A-25 |
| 승인 구분 | [ACCEPTED] 구성 (내부 상품 ID, 거래소, 거래통화 κ). [제안] 필드 이름 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `instrument_id` | `InstrumentId` | 필수 (A: ADR-0006 §6.2) | — | 상품 식별자 | 불변 | — |
| `venue` | `VenueId` | 미결정. 달력 기반 상태 판정에 필요하므로 LIVE에서 없으면 fail-closed [제안]. V1 변환에서는 "제공되지 않음" 표시 (A: ADR-0006 §6.7) | — | 거래소 | 불변 [제안] | — |
| `trading_currency` | `CurrencyCode` | 필수 (A: I6-10) | — | 거래통화 κ. FX를 찾는 키 | 불변 | 유효한 통화 코드 (D3A-25) |
| 기호 매핑 (거래소·공급자·브로커 기호) | 미정 | 미결정 (D3A-02) | — | 외부 기호와 내부 ID의 대응. 참조 데이터 | `as_of` | 내부 ID를 외부 기호로 대신하지 않음 [제안] |

### TC-A8 `QuantityConvention` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 수량의 단위와 lot size를 정한다 |
| 분류 | Reference Data (합성 구성요소) |
| 입력·출력 관계 | `Quantity`(TC-B1)의 유효성 검사에 쓴다 |
| 예상 예외 | lot size가 정수가 아니거나 1 미만 → `INVALID_VALUE`. 변형과 단위 불일치(선물에 `SHARE`) → `UNIT_MISMATCH` |
| 참조하는 타입 | TC-A6, TC-A15 |
| V1 대응 | 없음. V1 포지션은 정수 계약 수이며 사실상 lot 1이다. V1 변환에서 lot 1을 V1 의미로 표시하는 것은 [제안] (`V1_COMPAT` 전용) |
| 관련 ADR·질문 | ADR-0006 §6.1, §6.2, I6-5, I6-11 (ADR 본문). Q6-5 |
| 승인 구분 | [ACCEPTED] 단위(`CONTRACT`/`SHARE`), lot size(정수 ≥ 1) (ADR-0006 §6.2), 시장 의존 값은 출처·`as_of`가 있는 참조 데이터 (ADR-0006 §6.1). (ADR 본문) LIVE에서 값이 없으면 위험 증가 차단 (I6-11). [제안] 필드 이름 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `unit` | `QuantityUnit` | 필수 (A) | — | 수량 단위. 선물 `CONTRACT`, ETF `SHARE` 고정 | 불변 | 변형과 일치 |
| `lot_size` | `int` | 값은 참조 데이터 (A: ADR-0006 §6.1). 생성 시 필수 여부는 미결정. LIVE에서 없으면 그 상품의 위험 증가 차단 (ADR 본문: I6-11) | 수량 단위 | 주문·보유 수량의 최소 배수. 값은 시장·브로커 규칙 (UNVERIFIED, Q6-5). R2: 보유(실제) 수량에도 이 배수를 요구하는지는 승인된 D3A-49 원칙 (2)와 ACCEPTED I6-5가 충돌하는 지점이다. ADR 개정 승인(또는 해석 확인) 전까지 현행 문구를 유지한다 (결정 등록부 §9 CA-49) | 출처의 `as_of` | 정수 ≥ 1 (A: ADR-0006 §6.2). `bool`은 정수로 받지 않음 [제안] |
| `lot_size_provenance` | `ReferenceProvenance` | 조건부: `lot_size`가 있으면 필수 (A: ADR-0006 §6.1) | — | 출처와 `as_of` | — | — |

### TC-A9 `PriceIncrementRule` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 최소 가격변동(호가 단위) 규칙을 표현한다 |
| 분류 | Reference Data (합성 구성요소) |
| 입력·출력 관계 | 가격 → 호가 단위 정렬 여부. 체결가·quote 검증에 쓴다 (경계) |
| 예상 예외 | tick ≤ 0, 비유한 값, 구간이 겹치거나 비어 있는 표 → `INVALID_VALUE`. 정렬되지 않은 가격 → `INVALID_VALUE` (경계) |
| 참조하는 타입 | TC-B2, TC-A15 |
| V1 대응 | `InstrumentSpec.tick_size` (`instrument.py:10`, `> 0` 검사 `:29-37`), `validate_price_on_tick` (`execution.py:5-26`, tick 개수 기준 `abs_tol=1e-9`) |
| 관련 ADR·질문 | ADR-0006 §6.1, §6.2 ("고정 tick 또는 가격대별 표. 값은 참조 데이터"). D3A-11 (비교 허용 오차), Q6-5 |
| 승인 구분 | [ACCEPTED] 고정 tick 또는 가격대별 표, 값은 참조 데이터. [제안] tick > 0, 구간 규칙 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `rule_kind` | 열거 (`FIXED_TICK`, `PRICE_BAND_TABLE`) | 필수 (A: ADR-0006 §6.2) | — | 규칙 종류 | — | 알 수 없는 값 거부 |
| `tick_size` | `Num` | 조건부: `FIXED_TICK`이면 필수 | pt | 고정 호가 단위 | 출처의 `as_of` | 유한, > 0 [제안: V1과 같음] |
| `bands` | (하한 pt, 상한 pt, tick pt)의 순서 있는 목록 | 조건부: `PRICE_BAND_TABLE`이면 필수 | pt | 가격대별 호가 단위 (대상 시장 UNVERIFIED) | 출처의 `as_of` | 구간이 겹치지 않고 연속, 각 tick > 0 [제안]. 음수 가격 구간 처리는 미결정 |
| `provenance` | `ReferenceProvenance` | 필수 (A: ADR-0006 §6.1) | — | 출처, `as_of` | — | — |

- 정렬 여부 판정의 수치 허용 오차는 V1의 `1e-9`를 그대로 쓴다고 정하지 않는다. Q11-6 (D3A-11).

### TC-A10 `FuturesInstrument` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 선물 상품(기초 상품 root)의 사양 |
| 분류 | Reference Data (Union 변형, 판별자 `FUTURES`) |
| 입력·출력 관계 | 월물 체인 참조를 통해 `FuturesContract`(TC-A11)들과 연결. 신호의 대상 |
| 예상 예외 | 단위가 `CONTRACT`가 아님 → `UNIT_MISMATCH`. 기업 행사 연결 시도 → `ASSET_TYPE_MISMATCH` (I6-2) |
| 참조하는 타입 | TC-A7, TC-A8, TC-A9, TC-A15, TC-A2 |
| V1 대응 | `InstrumentSpec`을 재현용 변환기로만 연결 (ADR-0006 §6.7) |
| 관련 ADR·질문 | ADR-0006 §6.2, I6-1, I6-2. Q6-2, Q6-3, Q3-11, GAP F-07. D3A-05, D3A-08 |
| 승인 구분 | [ACCEPTED] 구성 요소 목록 (identity, 수량 규칙 `CONTRACT`, 호가 규칙, 월물 체인 참조, 롤 정책 참조, 증거금 모델 참조, 선물 비용표 참조). [제안] 필드 이름. 각 참조의 생성 시 필수 여부는 미결정 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `asset_type` | `AssetType` | 필수 (A) | — | `FUTURES` 고정 | — | — |
| `identity` | `InstrumentIdentity` | 필수 (A) | — | 상품 정체성 | — | — |
| `quantity_convention` | `QuantityConvention` | 필수 (A) | — | 단위 `CONTRACT` | — | 단위 = `CONTRACT` |
| `price_increment_rule` | `PriceIncrementRule` | 구성 요소 (A: ADR-0006 §6.2). 월물 규칙과의 상속 관계는 미결정 (§6.2는 월물이 "상속 가능"이라고만 함) | — | 상품 수준 호가 규칙 | 출처의 `as_of` | — |
| `contract_chain_ref` | 미정 (월물 ID 목록 또는 체인 출처 참조) | 구성 요소 (A). 표현은 미결정 | — | 이 상품의 월물 집합 | `as_of` | 체인 안의 월물은 모두 이 상품에 속함 (A: INV-20) |
| `roll_policy_ref` | 미정 | 구성 요소 (A). 내용은 미결정 (GAP F-07) | — | 롤 이벤트를 어떻게 만드는지 | — | — |
| `margin_model_ref` | 미정 | 구성 요소 (A). 모델은 미결정 (Q3-11) | — | 증거금 모델 | — | Paper/Live에서 증거금 모델이 없으면 위험 증가 차단 (ADR 본문: ADR-0008 AT-0008-6 예외조건, I6-11) |
| `cost_table_ref` | 미정 | 구성 요소 (A). 값 UNVERIFIED | — | 선물 비용표 (계약당 수수료 등) | `as_of` | — |
| `default_multiplier` | `ContractMultiplier` | **미결정 (Q6-3).** 존재 여부 자체가 상속 규칙에 달려 있음 | κ/pt/계약 | 월물 값의 기본값 후보 | — | 회계 계산에 직접 쓰지 않음 [제안] |

- 분배금·분할 필드를 두지 않는다 (A: I6-2).

### TC-A11 `FuturesContract` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 선물 월물(거래 단위)의 사양 |
| 분류 | Reference Data (거래 단위 사양) |
| 입력·출력 관계 | `TradableUnitRef(FUTURES_CONTRACT)`가 가리킨다. 손익·명목가치·증거금 계산의 승수와 통화를 제공한다 |
| 예상 예외 | 월물 ID 없음, 소속 상품 없음 → `MISSING_REQUIRED`. 통화가 소속 상품과 다름 → `CURRENCY_MISMATCH` (A). `M[c] ≤ 0`, 비유한 값 → `INVALID_VALUE` (A) |
| 참조하는 타입 | TC-A2, TC-A1, TC-B3, TC-B4, TC-A9, TC-D3, TC-A15 |
| V1 대응 | 없음. V1은 월물 사양이 없고 모든 월물이 `InstrumentSpec.multiplier`, `tick_size`를 함께 쓴다 (`roll_execution.py:36-45`) |
| 관련 ADR·질문 | ADR-0006 §6.2, I6-3, I6-6. ADR-0001 §6.2 전제조건. Q6-2, Q6-3. D3A-04, D3A-05 |
| 승인 구분 | [ACCEPTED] 월물 ID, 소속 상품 ID, 만기일·최종 거래일, `M[c]`, κ(c) (상품과 같아야 함), 호가 규칙 (상속 가능). `M[c]` 불변. [제안] 필드 이름, 만기 자료형 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `contract_id` | `ContractId` | 필수 (A: I6-3) | — | 월물 식별자 | 불변 | — |
| `instrument_id` | `InstrumentId` | 필수 (A: ADR-0006 §6.2 "소속 상품 ID") | — | 소속 상품 | 불변 | 정확히 하나의 상품 (A: INV-20) |
| `expiry_date` | `TradingDayLabel` 후보 | **미결정 (Q6-2).** ADR-0006 권장: Paper/Live 필수, 연구 경로 결정 필요. V1 변환은 "제공되지 않음" | 거래일 라벨 | 만기일 | 거래소 달력 기준 | UTC 날짜로 쓰지 않음 (C7-3) |
| `last_trading_day` | `TradingDayLabel` 후보 | 미결정 (Q6-2) | 거래일 라벨 | 최종 거래일 | 거래소 달력 기준 | 만기 이후 보유 거부를 쓰려면 필요 (ADR-0006 §9 권장) |
| `multiplier` | `ContractMultiplier` | **회계 사용 시점에는 확정값이 반드시 있어야 함** (A: ADR-0001 R2, I6-6). 생성 시 필수 여부와 상품 값 상속은 미결정 (Q6-3) | κ/pt/계약 | 월물의 계약승수 `M[c]` | 월물 존속 기간 동안 불변 (A: INV-19) | 유한, > 0 (A). 통화 = κ(c) |
| `trading_currency` | `CurrencyCode` | 필수 (A: ADR-0006 §6.2) | — | κ(c) | 불변 | 소속 상품의 거래통화와 같음. 다르면 거부 (A) |
| `price_increment_rule` | `PriceIncrementRule` | 선택. 상품 규칙 상속 가능 (A: "상속 가능" 기재). 구체 상속 규칙은 미결정 | — | 월물 호가 규칙 | `as_of` | — |
| `provenance` | `ReferenceProvenance` | 필수 (제안). I6-11의 값 목록에는 계약 사양(승수 등)이 없다 | — | 사양의 출처와 `as_of` | — | — |

### TC-A12 `EtfInstrument` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | ETF(상장 종목)의 사양. 상품이 곧 거래 단위다 |
| 분류 | Reference Data (Union 변형, 판별자 `ETF`) |
| 입력·출력 관계 | `TradableUnitRef(ETF_LISTING)`이 가리킨다. 기업 행사(TC-C8)와 연결 |
| 예상 예외 | 롤 이벤트·가산 back-adjustment 요청 → `ASSET_TYPE_MISMATCH` (A: I6-1). 승수 지정 시도 → `INVALID_VALUE` [제안: 필드가 없으므로 표현 불가] |
| 참조하는 타입 | TC-A7, TC-A8, TC-A9, TC-A15 |
| V1 대응 | 없음. V1으로는 ETF를 표현하지 않는다 (ADR-0006 §6.7). 승수 1·롤 0건으로 흉내 낸 V1 결과는 ETF 결과로 인정하지 않음 |
| 관련 ADR·질문 | ADR-0006 §6.2, I6-1, I6-4, I6-6, I6-11. Q6-4, Q6-5, Q6-8, Q8-5, Q3-7. D3A-06, D3A-08 |
| 승인 구분 | [ACCEPTED] 구성 (identity, 수량 규칙 `SHARE`·lot, 호가 규칙, 결제 규칙 참조, 기업 행사 출처 참조, 비용·세금표 참조, 공매도 정책 참조), 승수 필드 없음(1 고정). [제안] 필드 이름 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `asset_type` | `AssetType` | 필수 (A) | — | `ETF` 고정 | — | — |
| `identity` | `InstrumentIdentity` | 필수 (A) | — | 상품 정체성 | — | — |
| `quantity_convention` | `QuantityConvention` | 필수 (A) | — | 단위 `SHARE`, lot size | — | 단위 = `SHARE` |
| `price_increment_rule` | `PriceIncrementRule` | 구성 요소 (A). 값 UNVERIFIED | — | 호가 단위 (가격대별 표일 수 있음) | `as_of` | — |
| `settlement_rule_ref` | 미정 | 구성 요소 (A). 값은 미결정 (Q8-5, Q3-7) | — | 결제일 T+n (UNVERIFIED) | `as_of` | — |
| `corporate_action_source_ref` | 미정 | 구성 요소 (A) | — | 분배금·분할 출처 | — | — |
| `cost_tax_table_ref` | 미정 | 구성 요소 (A). 값 UNVERIFIED | — | 비율 수수료, 최소 수수료, 세금. **새 금융 공식이므로 CLAUDE.md §3.2 절차 필요** (ADR-0006 §6.4) | `as_of` | — |
| `short_policy_ref` | 미정 | 구성 요소 (A). 지원 범위는 미결정 (Q6-4). 확인되지 않은 상품의 음수 목표를 LIVE에서 위험 증가로 차단하는 것은 Q6-4의 권장이며 ADR-0002 §6.4 원칙의 적용 | — | 공매도 허용 여부 | `as_of` | — |
| `special_kind` (레버리지·인버스) | 미정 | 미결정 (Q6-8) | — | 특수 ETF 표시 | — | — |

- 승수 필드를 두지 않는다. 금액 계산에는 1 κ/pt/주를 쓴다 (A: I6-6). 만기·롤 필드를 두지 않는다 (A: I6-1, I6-4).

### TC-A13 `Instrument` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 자산 유형별 상품 사양의 Tagged Union |
| 분류 | Tagged Union |
| 입력·출력 관계 | `asset_type` → 변형. 공통 계산은 공통 구성요소를 보거나 판별자별 분기를 한곳에서 한다 |
| 예상 예외 | 판별자 없음·모르는 값 → `UNSUPPORTED_OR_UNAPPROVED` (A). 처리하지 않은 변형을 기본 분기로 처리 → 설계 오류 |
| 참조하는 타입 | TC-A10, TC-A12, TC-A5 |
| V1 대응 | V1 `InstrumentSpec`은 변환기로 `FuturesInstrument`에만 연결 |
| 관련 ADR·질문 | ADR-0006 §6.1, §6.2, §7 ("분기를 한곳에 모아야 누락이 생기지 않는다") |
| 승인 구분 | [ACCEPTED] `Instrument = FuturesInstrument \| EtfInstrument`, 판별자 거부 규칙 |

| 구성 | 내용 |
|---|---|
| 변형 | `FuturesInstrument` (`FUTURES`), `EtfInstrument` (`ETF`) |
| 판별자 | `asset_type` |
| 분기 규칙 | 모든 변형을 명시적으로 처리. 기본 분기는 거부 [제안] |

### TC-A14 `TradingConstraintSet` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 시장·브로커에 따라 달라지는 거래 제약 값을 출처와 함께 담는다 |
| 분류 | Reference Data |
| 입력·출력 관계 | 상품 변형의 각 `*_ref`가 가리키는 값. 거래 전 검사(ADR-0003 S-5 등)와 수량 검증에 쓴다 |
| 예상 예외 | 값에 출처나 `as_of`가 없음 → `MISSING_REQUIRED` (A: ADR-0006 §6.1). LIVE에서 필요한 값 없음 → 위험 증가 차단 (ADR 본문: I6-11. fail-closed이며 예외가 아님) |
| 참조하는 타입 | TC-A4 또는 TC-A1 (대상), TC-A15, TC-A9 |
| V1 대응 | 없음 |
| 관련 ADR·질문 | ADR-0006 §6.1, §6.4, §6.5, I6-11 (ADR 본문). ADR-0007 Q7-9. Q6-5, Q3-7. D3A-08, D3A-48 |
| 승인 구분 | [ACCEPTED] 시장·브로커 의존 값은 출처와 `as_of`가 있는 참조 데이터 (ADR-0006 §6.1). (ADR 본문) LIVE 누락 시 위험 증가 차단 (I6-11). [제안] 묶음 타입과 항목 이름 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `target` | `TradableUnitRef` 또는 `InstrumentId` | 필수 (제안). 어느 수준에 둘지는 미결정 | — | 제약의 대상 | — | — |
| `lot_size` | `int` + 출처 | 선택 (값 UNVERIFIED) | 수량 단위 | lot size | `as_of` | ≥ 1 |
| `min_order_quantity` | `int` + 출처 | 선택 (UNVERIFIED) | 수량 단위 | 최소 주문 수량 | `as_of` | ≥ 1 |
| `short_sale_allowed` | 열거 (`ALLOWED`, `NOT_ALLOWED`, `UNKNOWN`) + 출처 | 선택 (UNVERIFIED, Q6-4) | — | 공매도 허용 여부 | `as_of` | `UNKNOWN`을 허용으로 보지 않음 [제안] |
| `settlement_cycle` | 미정 + 출처 | 선택 (UNVERIFIED, Q8-5) | 영업일 | 결제 주기 | `as_of` | — |
| `order_acceptance_windows` | 세션별 구간 + 출처 | 선택 (UNVERIFIED, Q7-9) | — | 세션 밖 주문 접수 가능 구간 | `as_of` | 체결 가능 구간과 구분 (ADR-0007 원칙 10) |
| `fee_schedule_ref`, `tax_schedule_ref` | 미정 | 선택 (UNVERIFIED, Q6-5) | — | 수수료·세금표 | `as_of` | — |

### TC-A15 `ReferenceProvenance` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 참조 데이터 값의 출처, 기준 시각, 출처 분류를 기록한다 |
| 분류 | Value Object |
| 입력·출력 관계 | 참조 데이터 타입들이 포함한다 |
| 예상 예외 | 출처나 `as_of` 없음 → `MISSING_REQUIRED` (A: ADR-0006 §6.1). `effective_from > effective_to` → `TIME_ORDER_VIOLATION` |
| 참조하는 타입 | TC-D1, TC-C2, TC-D3 |
| V1 대응 | 없음 |
| 관련 ADR·질문 | ADR-0006 §6.1, ADR-0004 §5.1 ("상품 사양: 유효 기간"), §6.3 (증거금 출처). D3A-31 |
| 승인 구분 | [ACCEPTED] 출처와 `as_of`. [제안] 유효 기간, 출처 분류 필드 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `source` | `str` | 필수 (A: ADR-0006 §6.1) | — | 값의 출처 (거래소 공지, 브로커, 사용자 가정 등) | — | 비어 있지 않음 |
| `as_of` | `Instant` | 필수 (A: ADR-0006 §6.1) | — | 이 값이 알려진 기준 시각 | 지식 기준 시각 | UTC aware |
| `provenance_kind` | `ValueProvenance` (`REFERENCE` 또는 `ASSUMED`) | 필수 (제안) | — | 공지된 값인지 가정값인지 | — | — |
| `effective_from`, `effective_to` | `TradingDayLabel` 또는 `Instant` (미정) | 미결정 | — | 값의 효력 기간 | 효력 시점 | 시작 ≤ 끝 |

---

## 3. Values & Units

### TC-B1 `Quantity` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 계약 수 또는 주 수를 단위와 함께 표현한다. 같은 값 객체가 실제 수량(가칭 `PositionQuantity` 역할)과 신규 주문 수량(가칭 `OrderQuantity` 역할)에 쓰이며, 두 역할은 의미와 검증 책임이 다르다 ([APPROVED_PRINCIPLE] D3A-49 원칙 (1)·(6)). 두 역할을 별도 타입으로 나눌지는 D3A-49.9·D3A-12 (미결정)이므로 별도 TC로 만들지 않았다 |
| 분류 | Value Object |
| 입력·출력 관계 | 같은 단위, 같은 거래 단위끼리만 더하고 뺀다 [제안]. 거래 단위를 넘는 집계는 명시적 함수(P0-03B/C)로만 한다 |
| 예상 예외 | 정수가 아님(`float` 1.0, `bool` 포함) → `INVALID_VALUE` [제안]. 새 주문 수량이 lot 배수가 아님 → `UNIT_MISMATCH` (A: I6-5). 실제 보유·체결 수량이 lot 배수가 아닐 때: D3A-49 원칙 (2)로는 사실대로 기록해야 하지만 ACCEPTED I6-5와 충돌하므로 ADR 개정 승인 전에는 기대 결과를 확정하지 않는다 (아래 설명, 결정 등록부 §9 CA-49). 단위·거래 단위가 다른 수량 합산 → `UNIT_MISMATCH` |
| 참조하는 타입 | TC-A6, TC-A4 |
| V1 대응 | 단위 표시 없는 `int` (포지션 `contract_aware_daily_step.py:47-49`, 반올림 결과 `position.py:8-18`) |
| 관련 ADR·질문 | ADR-0001 §6.2 (`q`, `Δq`는 정수), ADR-0006 I6-5. D3A-12 |
| 승인 구분 | [ACCEPTED] 정수, 단위, lot 배수 (I6-5 문구), 단위가 다른 수량 합산 금지. [APPROVED_PRINCIPLE] D3A-49 원칙 (1), (3)~(6) (2026-10-17): 실제 수량과 주문 수량의 의미 분리, 주문 제약의 별도 검증, 실제 수량을 lot 배수로 조용히 반올림하거나 버리지 않음, 미체결 잔량 ≠ 신규 주문, 주문 검증과 체결·장부 기록의 책임 분리. [APPROVED_PRINCIPLE · 적용 보류] D3A-49 원칙 (2) (실제 수량의 사실 기록, lot 배수 비요구): ADR-0006 I6-5와 규범 충돌, 개정 승인 대기 (CA-49). [제안] 거래 단위를 값 객체에 포함, `bool` 거부 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `value` | `int` | 필수 (A) | `unit` | 부호 있는 수량. 포지션은 0 가능. 거래 수량 0의 거부는 P0-03B | — | 정수 (A: ADR-0001 §6.2, I6-5). lot size를 알면 그 배수 (A: I6-5 문구). 실제 수량에 대해서는 D3A-49 원칙 (2)와 충돌하며 ADR 개정 승인 대기 (CA-49) |
| `unit` | `QuantityUnit` | 필수 (A) | — | `CONTRACT` / `SHARE` | — | 거래 단위의 변형과 일치 |
| `tradable_unit` | `TradableUnitRef` | 미결정 (제안: 포함, D3A-12) | — | 이 수량의 거래 단위 | — | 합산은 같은 거래 단위끼리만 [제안] |

**lot 규칙의 검증 책임 (R1, R2 갱신)**. 같은 `Quantity`라도 쓰이는 자리에 따라 lot 규칙의 의미가 다르다. 아래 세 상황을 구분한다. 가상 예: `ETF.KR1` lot 10.

| 상황 | 예 | I6-5 문구를 그대로 적용하면 | 이 카탈로그의 현재 취급 |
|---|---|---|---|
| 새 주문 수량 (주문 의도, 목표 포지션에서 만든 주문) | 15주 주문 | 거부 | **I6-5 그대로 적용** (A). D3A-49 원칙 (3)과 같은 방향. 완화하지 않는다 |
| 부분 체결로 확인된 실제 수량 | 10주 주문 중 3주 체결 → 실제 +3주 (lot 미만 부분 체결이 생길 수 있는지는 시장·브로커별 UNVERIFIED) | 거부 → 실제 포지션을 표현할 수 없음 | D3A-49 원칙 (2)로는 사실대로 기록 (승인 원칙). I6-5와 충돌하여 ADR 개정 승인 전 적용 보류 (CA-49). 남은 주문 잔량 7주의 lot 처리는 D3A-49.1 (미결정) |
| 기업 행사 이후 실제 보유 수량 | 10주 보유 중 3:2 분할 → 10 × 3/2 = 15주 | 거부 → 실제 보유를 표현할 수 없음 | D3A-49 원칙 (2)와 15주 예제로는 사실대로 기록 (승인 원칙). I6-5와 충돌하여 ADR 개정 승인 전 적용 보류 (CA-49). 15주를 10주나 20주로 바꾸지 않는다 (원칙 (4)) |

- I6-5는 ACCEPTED 원칙 9가 인용한 규칙이므로 이 카탈로그는 그 의미를 바꾸거나 적용 범위를 좁히지 않는다. 실제 수량에 문구대로 적용하면 ACCEPTED ADR-0009 원칙 3·12(실제 포지션은 검증된 기준과 체결 기록으로 계산, 부분 체결은 개별 기록)와 ADR-0006 I6-8(분할은 수량 변환)이 요구하는 실제 상태를 표현할 수 없다. 이 충돌은 D3A-49에 기록했고, R2에서 `NORMATIVE_CONFLICT`로 분류해 ADR-0006 I6-5 개정 제안([ADR 본문] AT-0006-3 문장의 정리 포함)을 결정 등록부 §9.2에 적었다.
- 어느 결정에서도 실제 수량을 lot 배수로 조용히 반올림하거나 일부를 버리지 않는다 ([APPROVED_PRINCIPLE] D3A-49 원칙 (4). I6-5도 반올림이 아니라 거부를 요구하므로 충돌하지 않는다). 15주를 10주로 기록하면 노출이 33% 줄고, 20주로 기록하면 33% 늘어난다.
- 분할 결과가 정수가 아니면(예: 15주에 다시 3:2 분할 → 22.5주) 거부한다 (A: ADR-0001 §6.2와 I6-5의 정수 규칙. AT-0006-4 예외조건과 같음. 소수 주 처리는 Q6-5의 "단주 처리"). 정수 규칙은 D3A-49와 관계없이 모든 수량에 적용한다. 다만 실제 보유가 정수가 아닌 상황(소수 주의 현금 정산 전 등)이 생기면 D3A-49와 같은 대조 문제가 생긴다 (Q6-5).

### TC-B2 `Price` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 특정 거래 단위의 raw 가격 값을 종류와 함께 표현한다 |
| 분류 | Value Object |
| 입력·출력 관계 | raw 관측(TC-C4)·quote(TC-C5)의 가격. 보유분 손익의 가격 차이는 같은 거래 단위 사이에서만 [제안]. 금액 = 수량 × 가격 차이 × 승수 (P0-03B) |
| 예상 예외 | 비유한 값 → `INVALID_VALUE` (A: F, V). 종류가 없거나 조정 가격을 넣음 → `PRICE_KIND_MISMATCH` (A: ADR-0004 §6.4). 선물인데 거래 단위가 월물이 아님 → `IDENTITY_MISMATCH` (A: I6-3) |
| 참조하는 타입 | TC-C1, TC-A4 |
| V1 대응 | 종류 표시 없는 `float` (`ContractPrice.close`, `ContractQuote.bid/ask`, `BackAdjustedPrice.raw_price`) |
| 관련 ADR·질문 | ADR-0001 §5.1.4, §6.2, ADR-0004 §6.4. D3A-09, D3A-10, D3A-11 |
| 승인 구분 | [ACCEPTED] raw와 조정의 구분, 종류 표시, 비유한 값 거부. [제안] 거래 단위 포함, 부호 규칙 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `value` | `Num` (Q11-6) | 필수 | 거래 단위의 pt. ETF는 1 pt = κ 1단위/주 | 가격 값 | 시각은 담는 관측의 `ObservationMeta`가 가짐 | 유한 (A). **보편적 양수 제약 없음**: 선물 raw는 음수 가능 (V1 `tests/test_futures_data.py:217`). ETF raw 부호는 D3A-10 |
| `kind` | `PriceKind` | 필수 (A: ADR-0004 §6.4 "종류 표시") | — | 가격 종류 | — | 조정 종류 없음 (조정 가격은 TC-C6) |
| `tradable_unit` | `TradableUnitRef` | 필수 (선물은 A: I6-3. 일반화는 제안) | — | 가격의 거래 단위 | — | — |

### TC-B3 `ContractMultiplier` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 가격 1pt의 수량 1단위당 금액(계약승수)을 통화와 함께 표현한다 |
| 분류 | Value Object |
| 입력·출력 관계 | 수량 × 가격 차이(pt) × 승수 → 거래통화 금액 (P0-03B 회계식이 사용) |
| 예상 예외 | ≤ 0, 비유한 값 → `INVALID_VALUE` (A). 통화가 월물 통화와 다름 → `CURRENCY_MISMATCH` |
| 참조하는 타입 | TC-B4 |
| V1 대응 | `InstrumentSpec.multiplier` (`instrument.py:9`, `> 0` 검사 `:19-27`). 모든 월물이 공유 |
| 관련 ADR·질문 | ADR-0001 §6.2 (`M[c]` κ(c)/pt/ct, > 0), ADR-0006 I6-6. D3A-05 |
| 승인 구분 | [ACCEPTED] 월물별 `M[c] > 0`, 단위 κ/pt/계약, ETF 1 고정. [제안] 통화를 값에 포함 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `value` | `Num` | 필수 (A) | κ/pt/계약 (ETF: κ/pt/주) | 계약승수 | 월물 존속 기간 동안 불변 (A) | 유한, > 0 (A) |
| `currency` | `CurrencyCode` | 필수 (제안. 단위 κ(c)/pt/계약 자체는 A: ADR-0001 §6.2) | — | 승수 금액의 통화 κ | 불변 | 월물(또는 ETF)의 거래통화와 같음 |

- ETF에는 이 값을 저장하지 않는다. 금액 계산에 쓰는 1 κ/pt/주는 상품 통화에서 파생한다 (A: I6-6).

### TC-B4 `CurrencyCode` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 통화를 식별한다 |
| 분류 | Value Object |
| 입력·출력 관계 | 금액, 승수, 환율, 상품 통화가 참조 |
| 예상 예외 | 유효하지 않거나 지원하지 않는 코드 → `INVALID_VALUE` (ADR 본문: ADR-0008 AT-0008-10 예외조건) |
| 참조하는 타입 | 없음 |
| V1 대응 | `InstrumentSpec.currency` (빈 값만 거부, 계산에 쓰이지 않음), `account_base_currency` (manifest에서 `.strip().upper()`, `backtest_manifest.py:279-283`) |
| 관련 ADR·질문 | ADR-0008 §5.1, AT-0008-10, I6-10. D3A-25 |
| 승인 구분 | [ACCEPTED] 모든 상품에 거래통화 (I6-10), 통화가 다른 금액 합산 금지 (X8-8). (ADR 본문) 유효하지 않은 코드 거부 (AT-0008-10). [제안] 표준과 정규화 규칙 (D3A-25) |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `value` | `str` | 필수 | — | 통화 코드 (ISO 4217 세 글자 등은 D3A-25) | 불변 | 형식·지원 목록·대소문자 규칙은 D3A-25. 소문자 등을 조용히 정규화할지는 미결정 |

### TC-B5 `MoneyAmount` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 통화가 붙은 금액 |
| 분류 | Value Object |
| 입력·출력 관계 | 같은 통화끼리 덧셈·뺄셈. 스칼라 곱. `FxRate`(분모 = 이 통화)로 환산 → 분자 통화 금액 |
| 예상 예외 | 통화가 다른 금액 합산·비교 → `CURRENCY_MISMATCH` (A: X8-8). 비유한 값 → `INVALID_VALUE` [제안] |
| 참조하는 타입 | TC-B4, TC-E1 |
| V1 대응 | 통화 표시 없는 `float` (계좌 값은 기준통화, 비용은 상품 통화 → 환산 `fx.py:4-23`) |
| 관련 ADR·질문 | ADR-0008 X8-8, ADR-0001 R2. D3A-11, D3A-12 |
| 승인 구분 | [ACCEPTED] 통화별 합산 후 환산, 환산 전 합산 금지. [제안] 값 객체 연산 규칙 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `amount` | `Num` (Q11-6) | 필수 | `currency` | 금액. 부호는 맥락이 정함 | 시각은 담는 기록이 가짐 | 유한 |
| `currency` | `CurrencyCode` | 필수 (A) | — | 금액의 통화 | — | — |

---

## 4. Market Observation

### TC-C1 `PriceKind` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | raw 가격이 무엇의 가격인지 표시한다 |
| 분류 | Enumeration |
| 입력·출력 관계 | `Price`, `RawPriceObservation`이 가진다. 평가 정책이 어떤 종류를 평가가격으로 인정할지 고른다 |
| 예상 예외 | 알 수 없는 값 → `UNSUPPORTED_OR_UNAPPROVED` |
| V1 대응 | 없음. V1 `ContractPrice.close`는 종류가 정해져 있지 않음 |
| 관련 ADR·질문 | ADR-0004 §6.4, ADR-0001 Q1-2, ADR-0007 Q7-4. D3A-09 |
| 승인 구분 | [ACCEPTED] 종류 표시로 구분한다는 원칙. [제안] 아래 값 목록 전체 (D3A-09) |

| 값 (후보) | 의미 | 비고 |
|---|---|---|
| `TRADE_LAST` | 마지막 체결가 (장중 포함) | 장중 가격을 공식 가격처럼 쓰지 않음 (ADR-0007 §6.5) |
| `OFFICIAL_CLOSE` | 거래소 공식 종가 | 시장별 의미 UNVERIFIED |
| `SETTLEMENT` | 거래소 정산가 | Q1-2 |
| `NAV` | ETF 순자산가치 | ETF 평가에 쓸지는 Q1-2 |
| `V1_CLOSE_UNSPECIFIED` | V1 변환 전용. 종류를 알 수 없는 V1 종가 | `V1_COMPAT`에서만 [제안, D3A-35] |

- 값에 넣지 않는 것: "평가가격"(정책이 고른 역할), "조정 가격"(별도 타입 TC-C6), bid/ask (TC-C5).
- 공식·잠정 구분을 종류 값으로 할지 별도 속성으로 할지는 D3A-09.

### TC-C2 `ValueProvenance` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 값이 관측인지, 공지된 참조 데이터인지, 가정인지, 정책인지, 파생인지 표시한다 |
| 분류 | Enumeration |
| 입력·출력 관계 | `ReferenceProvenance`와 입력 묶음이 가진다. 관측 레코드는 타입 자체가 관측(`OBSERVED`)이므로 별도 필드를 두지 않는다. 백테스트에서 이용 가능 시각이 가정이라는 사실은 값의 출처가 아니라 시각의 근거이므로 `ObservationMeta.availability_basis`로 따로 표시한다 [제안] |
| 예상 예외 | 알 수 없는 값 → `UNSUPPORTED_OR_UNAPPROVED`. 체결 가정·정책 묶음의 값을 관측 묶음에 넣으려 함 → 책임 경계 위반 (INV-15) |
| V1 대응 | 없음. V1 `ExecutionMarketDay`는 세 종류를 섞는다 (ADR-0004 §3.3) |
| 관련 ADR·질문 | ADR-0004 원칙 2, §6.3, §9. D3A-31 |
| 승인 구분 | [ACCEPTED] 관측값·가정값·정책 값의 분리. [제안] 이 분류 체계 |

| 값 (후보) | 의미 |
|---|---|
| `OBSERVED` | 시장·공급자로부터 얻은 관측 |
| `REFERENCE` | 출처와 `as_of`가 있는 공지·사양 |
| `ASSUMED` | 시뮬레이션 가정 |
| `POLICY` | 사용자·운영 정책 결정 |
| `DERIVED` | 다른 값에서 계산한 값 |

### TC-C3 `ObservationMeta` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 관측의 시각, 이용 가능 시각의 근거, 출처, 수정본 관계를 기록한다 |
| 분류 | Value Object (메타데이터) |
| 입력·출력 관계 | 모든 관측(TC-C4, TC-C5, TC-E2)이 포함. PIT 판정(`usable`)의 입력 |
| 예상 예외 | `observed_at > data_available_at` → `TIME_ORDER_VIOLATION` (A). naive 시각 → `NAIVE_OR_AMBIGUOUS_TIME` (A). `availability_basis = ASSUMED`인데 가정 참조 없음 → `MISSING_REQUIRED` [제안] |
| 참조하는 타입 | TC-D1, TC-C2, TC-F3, TC-D3, TC-D5 |
| V1 대응 | 없음. V1 관측은 `date` 하나뿐 (ADR-0004 §3.4) |
| 관련 ADR·질문 | ADR-0001 §5.1.1, I-1, ADR-0004 §6.5, ADR-0002 §6.4, ADR-0011 FP-11~FP-13, FP-19. D3A-13, D3A-14, D3A-15, D3A-46 |
| 승인 구분 | [ACCEPTED] `observed_at`·`data_available_at`이 각 관측에 속함, 수정본은 별도 관측, `decision_at` 미포함, `dataset_id`·vintage는 실행 manifest. [제안] 시각 필드의 필수 여부, `availability_basis`, `time_basis`, 출처·수정 필드 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `observed_at` | `Instant` | 시각 판정을 하는 모든 경로에서 필수 (제안). ADR-0004 §6.5는 이 필드가 각 관측에 속한다고 정한다 (A). V1 변환에서는 없음 (`time_basis`로 표시) | — | 관측이 나타내는 시장 시각 | 내용 시각 | ≤ `data_available_at` (A) |
| `data_available_at` | `Instant` | 같음 (제안). ADR-0002 §6.4는 시각이 없을 수 있음을 전제로 LIVE의 `TIMESTAMP_MISSING`을 둔다 (A) | — | 시스템이 실제로 쓸 수 있게 된 시각 (백테스트는 가정) | 이용 가능 시각 | ≥ `observed_at` (A) |
| `availability_basis` | 열거 (`RECEIVED`, `ASSUMED`) | 미결정 (D3A-13, Q4-3) | — | `data_available_at`의 근거. Paper/Live의 실제 수신은 `RECEIVED`. 백테스트는 공급자 기록 시각을 근거로 쓰더라도 `ASSUMED` (ADR-0004 §6.5) | — | `ASSUMED`이면 근거(`latency_assumption_ref`)가 필수 [제안] |
| `latency_assumption_ref` | `DataLatencyAssumption` 참조 | 조건부 (제안) | — | 백테스트 지연 가정 | — | 체결 가정 묶음에 있어야 함 |
| `time_basis` | 열거 (`INSTANT`, `V1_DATE_ONLY`) | 필수 (제안) | — | 시각 정보의 성격. V1 변환 관측은 `V1_DATE_ONLY` | — | `V1_DATE_ONLY` 관측은 `V1_COMPAT`에서만 사용 [제안] (ADR-0007 §8) |
| `source_ref` | 미정 | 미결정 (D3A-14, D3A-15) | — | 값을 만든 공급원 | — | ADR-0011 FP-11, FP-12(공급자·`dataset_id`는 실행 manifest)와 충돌하지 않게 정해야 함 |
| `revision_of` | 관측 참조 | 미결정 (D3A-14) | — | 이 관측이 고친 원본 | — | 같은 대상, 같은 `observed_at` [제안] |
| `trading_day_label` | `TradingDayLabel` | 선택 (제안) | — | 공식 가격이 속한 거래일 | 거래소 라벨 | 달력이 부여 (C7-3) |
| `session_ref` | 세션 ID | 선택 (제안) | — | 공식 가격이 속한 세션 | — | — |
| `quality_flags` | 미정 | 미결정 (D3A-46) | — | 검증 결과, 품질 표시 | — | LIVE에서 없으면 `DATA_QUALITY_UNKNOWN` (A: ADR-0002 §6.4) |

- 넣지 않는 필드: `decision_at` (A: ADR-0004 §6.5), `dataset_id`·저장 위치·vintage 표기 (A: ADR-0011 FP-11, FP-12. 실행 manifest의 `DataVintageRef`에 둔다).

### TC-C4 `RawPriceObservation` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 특정 거래 단위(월물 또는 ETF 종목)의 조정하지 않은(raw) 가격 관측. **실행 가능한 가격이라는 뜻이 아니다** (R1) |
| 분류 | Observation |
| 입력·출력 관계 | Data Boundary가 만들고 PIT 뷰를 거쳐 평가·체결가 검증(호가 단위 등)·명목가치·증거금 계산에 쓰인다. 승인된 평가 정책이 평가가격으로 고를 수 있다 (평가가격 종류는 OPEN Q1-2). 필요조건은 보유 월물 자신의 raw 가격, `data_available_at ≤ valuation_at`, `valuation_at`까지 이용 가능해야 했던 세션의 가격이다 (그 밖의 상태는 Q7-3·Q7-4 정책, AT-03A-25 (c)). 체결가로 쓰려면 명시적인 체결 가정(TC-F2의 체결 시뮬레이션)이 그렇게 정해야 하며, 그 결과는 관측이 아니라 가정 기반 체결가다 ([APPROVED_PRINCIPLE] D3A-50 원칙 (5)·(7), INV-33. 그 가정이 승인된 것이어야 한다는 한정은 [제안]). 그런 가정의 허용 여부는 보류이고(Q1-1, AT-03A-25 (d)), 허용되더라도 ADR-0001 I-2와 ADR-0007 원칙 10을 지켜야 한다 |
| 예상 예외 | 거래 단위 없음 → `MISSING_REQUIRED`. 선물인데 월물이 아님 → `IDENTITY_MISMATCH` (A). 비유한 가격 → `INVALID_VALUE` (A). 종류 오류 → `PRICE_KIND_MISMATCH`. 체결 가정이나 체결 기록 없이 이 관측으로 체결가를 확정하려 함 → 거부 ([APPROVED_PRINCIPLE] D3A-50 원칙 (2)·(5). 오류 분류 `MISSING_REQUIRED`는 [제안], AT-03A-25). 이 관측을 `MarketQuote`로 바꾸려 함 → 계약에 변환 경로를 두지 않음 (정산가는 [APPROVED_PRINCIPLE] D3A-50 원칙 (6). 공식 종가·마지막 체결가 등 다른 종류로 넓힌 것은 [제안]). Python 생성자가 이를 구조적으로 막는지는 구현 후 인수 테스트로 확인한다 (AT-03A-25 (b)) |
| 참조하는 타입 | TC-A4, TC-B2, TC-C1, TC-C3 |
| V1 대응 | `ContractPrice` (`futures_data.py:6-17`, 종가 종류 미상, `date`만), `BackAdjustedPrice.raw_price` (`:43`) |
| 관련 ADR·질문 | ADR-0001 §5.1.4, ADR-0004 §6.4, I6-3, I6-7. D3A-09, D3A-10 |
| 승인 구분 | [ACCEPTED] raw 가격은 특정 월물(ETF 종목)의 가격, 체결·평가에 사용 (ADR-0001 §5.1.4, ADR-0004 §6.4). [제안] 필드 구성. [APPROVED_PRINCIPLE] D3A-50 (2026-10-17): "Raw = 조정하지 않음, 체결 가능을 뜻하지 않음", 공식 종가·정산가는 Raw이면서 평가용 가격일 수 있음 (중심 문서 §5.1, INV-33, 결정 등록부 §9 CA-50) |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `tradable_unit` | `TradableUnitRef` | 필수 (선물 A: I6-3. 일반화 제안) | — | 거래 단위 | — | — |
| `price` | `Num` | 필수 | 거래 단위의 pt | 가격 | `meta.observed_at` | 유한. 부호는 D3A-10 |
| `kind` | `PriceKind` | 필수 (A: 종류 표시) | — | 가격 종류 | — | — |
| `meta` | `ObservationMeta` | 필수 (제안) | — | 시각·출처 | — | — |
| `officiality` | 미정 (공식 / 잠정 / 지표) | 미결정 (D3A-09) | — | 공식 가격 여부 | — | — |

- 공식 종가(`OFFICIAL_CLOSE`), 정산가(`SETTLEMENT`), 마지막 체결가(`TRADE_LAST`)는 모두 raw이지만 의미가 다르다. 기준 가격이거나 과거 한 시점의 거래 가격이며, 이후 주문의 체결가를 보장하지 않는다. bid/ask는 별도 관측(TC-C5)이다 (R1. [APPROVED_PRINCIPLE] D3A-50 원칙 (1)~(3)).
- 평가가격(평가 정책이 고른 raw 관측), 시뮬레이션 체결가(명시적인 체결 가정이 quote 등에서 계산한 값. 승인된 가정이어야 한다는 한정은 [제안]), 실제 체결가(브로커 체결 기록의 가격)는 서로 다른 값이다 ([APPROVED_PRINCIPLE] D3A-50 원칙 (7)). 체결 기록(Fill)은 실제 체결이나 명시적 체결 시뮬레이션에서만 생긴다 (원칙 (5)). Fill의 필드는 P0-03B에서 정한다 (중심 문서 §13.1).
- 거래량·미결제약정 같은 다른 시장 관측은 같은 `ObservationMeta` 형태의 별도 관측 타입 후보다. 현재 ACCEPTED ADR이 요구하지 않으므로 상세 명세는 하지 않았다 (롤 정책이 쓰게 되면 F-07과 함께 다룬다).

### TC-C5 `MarketQuote` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 특정 거래 단위의 bid/ask 관측 |
| 분류 | Observation |
| 입력·출력 관계 | 체결가 결정, mid 기준 비용 측정. mid = (bid + ask) / 2는 파생값 (A: ADR-0001 §5.1.4) |
| 예상 예외 | bid > ask → `INVALID_VALUE` [제안: V1 규칙]. 비유한 값 → `INVALID_VALUE`. 호가 단위 불일치 → `INVALID_VALUE` (경계, [제안]) |
| 참조하는 타입 | TC-A4, TC-B2, TC-C3 |
| V1 대응 | `ContractQuote(bid, ask)` (`roll_execution.py:15-18`, 클래스 자체 검증 없음. 검증은 `execution.py:34-60`, `data_quality.py:169-190`) |
| 관련 ADR·질문 | ADR-0004 §6.4, ADR-0001 §5.1.4. Q3-3 (`P_ref`) |
| 승인 구분 | [ACCEPTED] quote는 시각 있는 관측, 체결가·비용 기준. [제안] bid ≤ ask를 생성 불변조건으로 둠 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `tradable_unit` | `TradableUnitRef` | 필수 (선물 A: I6-3) | — | 거래 단위 | — | — |
| `bid` | `Num` | 필수 (제안) | pt | 매수 호가 | `meta.observed_at` | 유한. bid ≤ ask (bid = ask 허용, V1과 같음) |
| `ask` | `Num` | 필수 (제안) | pt | 매도 호가 | 같음 | 유한 |
| `bid_size`, `ask_size` | `int` | 미결정 | 수량 단위 | 호가 잔량 | 같음 | ≥ 0 |
| `meta` | `ObservationMeta` | 필수 (제안) | — | quote 관측 시각 (V1에는 없음) | — | — |

- 관측 quote에 슬리피지를 더한 값을 넣지 않는다. 슬리피지는 체결 모델이 체결가를 계산할 때 적용한다 (INV-15).
- quote도 관측 시각의 호가일 뿐이며 체결(Fill)이 아니다 ([APPROVED_PRINCIPLE] D3A-50 원칙 (4)). 체결가는 체결 모델(명시적인 체결 가정)이나 체결 기록이 정한다 (INV-33). 정산가로 quote를 만드는 변환 경로는 계약에 두지 않는다 ([APPROVED_PRINCIPLE] D3A-50 원칙 (6), AT-03A-25). 다른 가격 종류의 관측으로 넓힌 것은 [제안]이다. 생성자 수준의 강제는 구현 전이므로 UNVERIFIED이며, 그때까지는 Data Boundary의 출처 확인에 기댄다 (D3A-31).

### TC-C6 `AdjustedPriceSeries` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 신호 계산 전용의 연구용 조정 시계열 snapshot (상품 하나, `as_of` 하나) |
| 분류 | Derived (연구 전용). 계산은 Research 계층이 하고 계약만 도메인에 둔다 |
| 입력·출력 관계 | raw 관측 + 롤 이벤트(선물) 또는 기업 행사(ETF) → 조정 시계열. 신호 함수(vol, forecast)의 입력 |
| 예상 예외 | 체결·평가·명목가치·증거금·현금 입력 자리에 사용 → `PRICE_KIND_MISMATCH` (A). 서로 다른 `as_of` snapshot 차분 → `PRICE_KIND_MISMATCH` (A). `as_of` 이후에 이용 가능해진 입력 포함 → `PIT_VIOLATION` [제안] |
| 참조하는 타입 | TC-A1, TC-D1, TC-D3, TC-A2 |
| V1 대응 | `BackAdjustedPrice.adjusted_price` (`futures_data.py:44`. full-history 함수 `:47-179`와 as-of 함수 `:181-206`이 모두 이 타입을 만들고, 타입에 `as_of`가 없다), `PointInTimeResearchSignalPoint.snapshot_adjusted_price` (PIT snapshot의 마지막 점, `research_pipeline.py:181-185`) |
| 관련 ADR·질문 | ADR-0004 §6.4, ADR-0006 §6.6, ADR-0005 E-2. Q6-6. D3A-35 |
| 승인 구분 | [ACCEPTED] 연구 전용, `as_of`에 묶임, 다른 snapshot 차분 금지, raw로의 암묵 변환 금지, 새 엔진은 PIT만, 자산 유형과 무관한 결과 계약. [제안] 필드 구성 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `instrument_id` | `InstrumentId` | 필수 (제안) | — | 시계열의 상품 (월물이 아니라 상품) | — | — |
| `method` | 열거 (`FUTURES_ADDITIVE_BACK_ADJUSTED`, `ETF_CORPORATE_ACTION_ADJUSTED`, `V1_DIFFERENCE_ONLY`) | 필수 (제안) | — | 조정 방식 | — | ETF 방식의 세부는 Q6-6. ETF에 가산 방식 요청 시 거부 (A: I6-1) |
| `as_of` | `Instant` | 필수 (A: ADR-0004 §6.4 "as_of에 묶임") | — | snapshot의 지식 기준 시각 | 지식 기준 시각 | 모든 입력의 `data_available_at ≤ as_of` [제안] |
| `construction` | 열거 (`PIT`, `V1_FULL_HISTORY`, `V1_AS_OF_SNAPSHOT`, `V1_UNSPECIFIED`) | 필수 (제안) | — | 구성 방식 | — | 새 엔진은 `PIT`만 (A: E-2). V1 값은 변환 경계에서만 들어오며, V1 타입에 구성 정보가 없으므로 호출자가 명시하거나 `V1_UNSPECIFIED` (D3A-35) |
| `points` | (`TradingDayLabel` 또는 `Instant`, `Num`)의 시퀀스 | 필수 | pt (조정 기준) | 조정 가격 점 | 각 점의 관측 시각 | 시각 오름차순, 유한. 부호 제약 없음 |
| `point_source_contracts` | 점별 `ContractId` | 선택 (제안) | — | 각 점의 기반 월물 (V1 `active_contract`에 해당) | — | — |

- 차분은 같은 snapshot 안에서만 한다 (A). 시계열 끝에서 조정 값이 raw와 같아지는 성질을 근거로 조정 값을 raw로 쓰지 않는다 [제안].

### TC-C7 `FuturesRollEvent` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 선물의 롤(구월물 → 신월물) 참조 이벤트 |
| 분류 | Reference Event |
| 입력·출력 관계 | 조정 시계열 계산(Research)과 롤 체결 다리 생성(Engines, P0-03B 회계)에 쓴다 |
| 예상 예외 | ETF에 사용 → `ASSET_TYPE_MISMATCH` (A: I6-1). 구월물 = 신월물 → `INVALID_VALUE` (A, V1과 같음). 체인에 없는 월물 → `IDENTITY_MISMATCH` (A: I6-3) |
| 참조하는 타입 | TC-A1, TC-A2, TC-D3, TC-D1, TC-A15 |
| V1 대응 | V1 `RollEvent(date, old_contract, new_contract)` (`futures_data.py:20-36`). 상품 ID와 known_at이 없음 |
| 관련 ADR·질문 | ADR-0006 §6.2, I6-1. ADR-0004 §6.5 (known_at). GAP F-07. ADR-0001 Q1-6. D3A-01 (이름) |
| 승인 구분 | [ACCEPTED] 상품 ID, 효력일, 구·신월물 ID, known_at, 선물 전용. [제안] 이름 `FuturesRollEvent` (ADR-0006 가칭 `RollEvent`는 V1 이름과 같음) |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `instrument_id` | `InstrumentId` | 필수 (A) | — | 롤하는 선물 상품 | — | 선물 상품 |
| `effective_date` | `TradingDayLabel` | 필수 (A: "효력일") | 거래일 라벨 | 롤 효력일 | 효력 시점 | 거래소 달력 라벨 |
| `old_contract_id` | `ContractId` | 필수 (A) | — | 구월물 | — | 상품 체인에 있음 |
| `new_contract_id` | `ContractId` | 필수 (A) | — | 신월물 | — | 상품 체인에 있음, 구월물과 다름 |
| `known_at` | `Instant` | 새 경로 필수 (제안). V1 변환은 "제공되지 않음" | — | 롤 일정이 결정·공표된 시각 | 알려진 시각 | `known_at ≤` 이 이벤트를 쓰는 판단 시각 (PIT) [제안] |
| `provenance` | `ReferenceProvenance` 또는 규칙 생성 표시 | 미결정 (F-07, 롤 정책) | — | 공급자 일정인지 규칙 생성인지 | — | — |

- 같은 상품·같은 효력일의 롤을 하나로 제한하는 V1 규칙(`futures_data.py:73-85`)을 새 계약에도 둘지는 미결정이다. 롤 다리의 체결 시점은 이벤트가 아니라 체결 규칙이 정한다 (ADR-0001 Q1-6).

### TC-C8 `CorporateAction` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | ETF의 분배금·분할 참조 이벤트 |
| 분류 | Reference Event (Union: `CashDistribution` \| `ShareSplit`) |
| 입력·출력 관계 | 조정 시계열(Research), 분배금 `D[c,t]`와 분할 변환(P0-03B 회계)에 쓴다 |
| 예상 예외 | 선물에 사용 → `ASSET_TYPE_MISMATCH` (A: I6-2). 분할 비율 ≤ 0·비유한 값 → `INVALID_VALUE` (A: AT-0006-4). 분배금 통화 오류 → `INVALID_VALUE` |
| 참조하는 타입 | TC-A1, TC-D3, TC-B5, TC-D1, TC-A15 |
| V1 대응 | 없음 |
| 관련 ADR·질문 | ADR-0006 §6.2, I6-2, I6-8, I6-9. ADR-0004 §6.5 (known_at). ADR-0001 Q1-5, Q6-7 (귀속일), Q6-5 ("단주 처리": 여기서는 정수가 아닌 분할 결과, 즉 소수 주) |
| 승인 구분 | [ACCEPTED] 분배금(배당락일, 지급일, 주당 금액, 통화), 분할(효력일, 비율), ETF 전용, 분할은 손익이 아님 (ADR-0006). 기업 행사가 known_at을 가짐 (ADR-0004 §6.5). [제안] 필드 이름, 비율 표현 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `instrument_id` | `InstrumentId` | 필수 (A) | — | ETF 상품 | — | ETF |
| `action_type` | 열거 (`CASH_DISTRIBUTION`, `SPLIT`) | 필수 (A) | — | 종류 | — | 알 수 없는 값 거부 |
| `known_at` | `Instant` | 필수 (제안) | — | 공표 시각 | 알려진 시각 | — |
| `provenance` | `ReferenceProvenance` | 필수 (제안) | — | 출처 | — | — |
| (분배금) `ex_date` | `TradingDayLabel` | 필수 (A: "배당락일") | 거래일 라벨 | 배당락일 | 효력 시점 | — |
| (분배금) `pay_date` | `TradingDayLabel` 또는 날짜 (미정) | 필수 (A: "지급일") | — | 지급일 | — | `ex_date` 이후 [제안] |
| (분배금) `amount_per_share` | `MoneyAmount` | 필수 (A: "주당 금액, 통화") | 통화/주 | 주당 분배금 | — | 유한, ≥ 0 [제안] |
| (분배금) `record_date` | 미정 | 미결정 | — | 기준일 | — | — |
| (분할) `effective_date` | `TradingDayLabel` | 필수 (A) | — | 효력일 | 효력 시점 | — |
| (분할) `ratio` | 정수 분자·분모 (예: 신주 2 / 구주 1) | 필수 (A: "비율") | — | 분할 비율 | — | > 0, 유한 (A). 정수 분자·분모 표현은 [제안] (실수 오차 방지) |

- 귀속일(배당락일/지급일) 선택은 Q1-5/Q6-7이다. 두 날짜를 모두 두고 선택은 열어 둔다 (ADR-0006 §6.8 정합성 표의 기술).

### TC-C9 `DataVintageRef` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 실행이 어느 데이터셋의 어느 vintage에 묶였는지 가리킨다 |
| 분류 | Reference (실행 manifest용) |
| 입력·출력 관계 | 실행 manifest(P0-03C 후보)에 기록. 데이터 계층이 vintage로 관측 집합을 고르는 기준 |
| 예상 예외 | `dataset_id` 없음 → `MISSING_REQUIRED` |
| 참조하는 타입 | TC-D1 |
| V1 대응 | 없음 (V1 manifest에 데이터 버전 없음, GAP A-09) |
| 관련 ADR·질문 | ADR-0011 FP-11~FP-13, Q11-8, Q11-11. ADR-0004 Q4-4. D3A-14 |
| 승인 구분 | [ACCEPTED] `dataset_id`·vintage는 입력 fingerprint가 아니라 실행 manifest에 둠, 실행은 vintage 하나에 묶임. [제안] 필드 구성. vintage의 정의는 미결정 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `dataset_id` | `str` | 필수 (제안) | — | 데이터셋의 논리 식별자. 내용이 바뀌어도 같을 수 있음 (A: FP-12) | — | 데이터 변경 감지 근거로 쓰지 않음 (A: FP-12) |
| `knowledge_cutoff` | `Instant` | 미결정 (D3A-14) | — | "이 시각까지 이용 가능했던 관측" 기준 | 지식 기준 시각 | — |
| `vendor_snapshot_label` | `str` | 미결정 (D3A-14) | — | 공급자가 붙인 snapshot 이름 | — | — |
| `provider` | `str` | 미결정 | — | 공급자 (A: FP-12에 따라 실행 manifest) | — | — |

---

## 5. Time & Calendar

### TC-D1 `Instant` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 실제 시각(instant)을 타임존이 있는 UTC로 표현한다 |
| 분류 | Value Object |
| 입력·출력 관계 | 모든 시각 필드의 자료형. `Instant`끼리만 비교한다 |
| 예상 예외 | naive 시각 → `NAIVE_OR_AMBIGUOUS_TIME` (A). UTC가 아닌 aware 시각 → 거부 또는 정규화 (D3A-17) |
| 참조하는 타입 | 없음 |
| V1 대응 | 없음. V1은 `datetime.date`만 쓴다 (ADR-0007 §3.1) |
| 관련 ADR·질문 | ADR-0007 C7-1, ADR-0011 FP-10. D3A-16, D3A-17 |
| 승인 구분 | [ACCEPTED] UTC instant 저장, naive 거부. [제안] 비UTC 처리, 정밀도 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `value` | 타임존이 있는 `datetime.datetime` (tzinfo = UTC) | 필수 (A: C7-1) | — | 시각 | 역할은 담는 필드의 이름이 정함 | aware, UTC. 정밀도(마이크로초 등)는 미결정 (FP-10의 고정 형식은 제안) |

### TC-D2 `ZonedLocalTime` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 거래소·계좌의 현지 벽시계 시각을 IANA 타임존과 함께 입력받는다 |
| 분류 | Value Object (입력 형태) |
| 입력·출력 관계 | 현지 시각 + 타임존 → 타임존 데이터베이스로 `Instant` 변환. 세션·의사결정 일정 설정에 쓴다 |
| 예상 예외 | 알 수 없는 타임존 → `INVALID_VALUE`. 존재하지 않거나 두 번 존재하는 현지 시각 → 규칙이 정해질 때까지 `NAIVE_OR_AMBIGUOUS_TIME` (Q7-8). 타임존 데이터 없음 → `MISSING_REQUIRED` (A: AT-0007-3 예외조건) |
| 참조하는 타입 | TC-D1 |
| V1 대응 | 없음 |
| 관련 ADR·질문 | ADR-0007 C7-1, C7-2, X7-5, Q7-8. ADR-0011 FP-14. ADR-0010 Q10-7. D3A-18, D3A-24 |
| 승인 구분 | [ACCEPTED] IANA 타임존, 타임존 데이터베이스 변환, 고정 시차 금지, 타임존 데이터 버전 기록. [제안] 왕복 변환 검사 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `local_wall_time` | naive `datetime.datetime` (현지 벽시계) | 필수 | — | 현지 시각 | 현지 시각 | 이 필드만으로 비교하지 않음 |
| `zone` | `str` (IANA 이름, 예: `Asia/Seoul`) | 필수 (A: C7-1) | — | 타임존 | — | 고정 시차 문자열(예: `+09:00`)을 타임존으로 쓰지 않음 [제안, C7-2] |
| `disambiguation` | 미정 | 미결정 (Q7-8) | — | DST 중복·공백 시각의 해석 규칙 | — | 라이브러리 기본값(`fold=0`)에 기대지 않음 [제안] |

- Python `zoneinfo`는 존재하지 않는 현지 시각을 오류 없이 변환한다 (CONFIRMED, 중심 문서 §6.7). 변환 후 다시 현지 시각으로 바꿔 원래 값과 같은지 확인하는 검사가 필요하다 [제안].

### TC-D3 `TradingDayLabel` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 거래소가 세션에 붙인 거래일 라벨 |
| 분류 | Value Object |
| 입력·출력 관계 | 세션, 만기, 롤 효력일, 기업 행사 날짜에 쓴다. 다른 거래소 라벨과 시각으로 비교하지 않는다 |
| 예상 예외 | 거래소 없음 → `MISSING_REQUIRED` [제안]. UTC 날짜에서 만든 라벨 → 설계 오류 (C7-3) |
| 참조하는 타입 | TC-A3 |
| V1 대응 | V1 `date` 필드. `V1_COMPAT`에서는 "모든 상품이 같은 날짜에 세션 하나"인 달력의 라벨로 해석 (A: ADR-0007 §8) |
| 관련 ADR·질문 | ADR-0007 §5.1 (Trading Day), C7-3, X7-4 |
| 승인 구분 | [ACCEPTED] 같은 날짜 문자열이 같은 시각에 이용 가능하다고 가정하지 않음 (X7-4, 원칙 11). 라벨 부여 규칙 C7-3은 ADR-0007 §6.2 규칙이며 승인 원칙 목록에 직접 인용되지 않는다. [제안] 거래소를 함께 가짐 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `venue` | `VenueId` | 필수 (제안) | — | 라벨을 붙인 거래소 | — | — |
| `label` | `datetime.date` | 필수 (제안. 정의는 ADR-0007 §5.1, 부여 규칙은 C7-3) | — | 거래일 라벨 | 거래소 규칙 | 달력이 부여. UTC 날짜·계좌 현지 날짜에서 추론 금지 (C7-3) |

### TC-D4 `ExchangeCalendar` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 거래소의 세션 목록과 휴장(세션 없음)을 정의한다 |
| 분류 | Reference Data |
| 입력·출력 관계 | 데이터 상태 판정(TC-D9)과 체결 가능 구간 판정의 입력 |
| 예상 예외 | 출처·`as_of` 없음 → `MISSING_REQUIRED` (제안). 적용 기간 밖 시각 판정 → 판정 불가 (LIVE는 `MISSING_DATA`로 처리, ADR 본문: AT-0007-5) |
| 참조하는 타입 | TC-A3, TC-D5, TC-D3, TC-A15 |
| V1 대응 | 없음 |
| 관련 ADR·질문 | ADR-0007 §5.1, §6.4, Q7-2, Q7-7. ADR-0011 FP-14. D3A-20 |
| 승인 구분 | [ACCEPTED] 거래소별 세션과 휴장일, IANA 타임존. [제안] 적용 기간, 상품군 범위 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `venue` | `VenueId` | 필수 (A) | — | 거래소 | — | — |
| `timezone` | `str` (IANA) | 필수 (A) | — | 거래소 타임존 | — | 고정 시차 아님 |
| `sessions` | `TradingSession` 시퀀스 | 필수 | — | 세션 목록 | — | 시작 시각 오름차순, 같은 범위 안에서 겹치지 않음 [제안] |
| `coverage_start`, `coverage_end` | `TradingDayLabel` | 필수 (제안) | — | 달력이 정의된 기간 | — | 기간 밖에서는 휴장으로 추측하지 않음 |
| `session_scope` | 미정 (거래소 전체 / 상품군 템플릿) | 미결정 (D3A-20) | — | 세션이 적용되는 상품 범위 | — | — |
| `provenance` | `ReferenceProvenance` | 필수 (제안. 달력이 참조 데이터라는 분류는 ADR-0007 §5.1, 출처는 Q7-2) | — | 출처, `as_of` | — | — |
| `special_events` | 미정 (조기 폐장, 임시 휴장, 거래 중단) | 미결정 (Q7-7) | — | 예외 일정 | — | — |

- 타임존 데이터 출처와 버전은 이 달력을 쓴 실행의 manifest에 기록한다 (A: FP-14).

### TC-D5 `TradingSession` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 한 번의 연속 거래 구간 |
| 분류 | Reference Data |
| 입력·출력 관계 | 공표 예상 시각 계산(TC-D6), 상태 판정(TC-D9), 체결 가능 여부 판정 |
| 예상 예외 | 시작 ≥ 종료 → `TIME_ORDER_VIOLATION`. naive 시각 → `NAIVE_OR_AMBIGUOUS_TIME` |
| 참조하는 타입 | TC-A3, TC-D3, TC-D1, TC-D2 |
| V1 대응 | 없음 |
| 관련 ADR·질문 | ADR-0007 §5.1, 원칙 10, Q7-9. ADR-0007 §6.6 (야간 세션) |
| 승인 구분 | [ACCEPTED] 세션을 instant로 표현 (원칙 1), UTC 비교와 IANA 타임존 (원칙 2), 제출 시각과 체결 가능 시각 구분 (원칙 10). [제안] 현지 시각 병기 (ADR-0007 §5.1의 세션 정의를 따름), 필드 이름 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `session_id` | `str` | 필수 (제안) | — | 세션 식별자 | — | 달력 안에서 고유 |
| `venue` | `VenueId` | 필수 (A) | — | 거래소 | — | — |
| `trading_day_label` | `TradingDayLabel` | 필수 (제안) | — | 거래일 라벨 (야간 세션은 다음 거래일일 수 있음) | 거래소 규칙 | — |
| `start`, `end` | `Instant` | 필수 (A: 원칙 1) | — | 세션 시작·종료 | 실제 시각 | `start < end` |
| `local_start`, `local_end` | `ZonedLocalTime` | 필수 (제안. ADR-0007 §5.1 세션 정의) | — | 감사용 현지 시각 | — | `Instant`와 일치 |
| `session_kind` | 열거 (정규 / 야간 / 단일가 등) | 미결정 (UNVERIFIED) | — | 세션 종류 | — | — |
| `executable_windows` | 구간 목록 | 선택 (UNVERIFIED) | — | 체결 가능 구간 | — | 세션 안 |
| `order_acceptance_windows` | 구간 목록 | 선택 (UNVERIFIED, Q7-9) | — | 주문 접수 가능 구간 | — | 체결 가능 구간과 구분 (A) |

### TC-D6 `PublicationExpectation` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 세션별 공식 가격의 예상 공표 시각을 계산하는 규칙 (데이터 계약) |
| 분류 | Reference Data / Assumption |
| 입력·출력 관계 | 세션 → `expected_publication_at`. 상태 판정에서 "들어와야 했는가"를 정한다 |
| 예상 예외 | 규칙 없음 → 상태 판정 불가 (LIVE: fail-closed) |
| 참조하는 타입 | TC-D5, TC-C1, TC-A15 |
| V1 대응 | 없음 |
| 관련 ADR·질문 | ADR-0007 §5.1 (공표 예상 시각), §6.3, §6.4. ADR-0001 Q1-3. D3A-13, D3A-19 |
| 승인 구분 | [ACCEPTED] 공표 예상 시각은 데이터 계약(참조 데이터, 가정값)이며 실제 이용 가능 시각과 다름. [제안] 규칙 형태 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `scope` | (거래소, 가격 종류 또는 데이터셋) | 필수 (제안) | — | 규칙 적용 범위 | — | — |
| `rule` | 미정 (예: 세션 종료 + 지연) | 필수 (제안). 지연 값은 미결정 (Q1-3) | 시간 | 예상 공표 시각 계산 규칙 | — | 지연 ≥ 0 |
| `provenance` | `ReferenceProvenance` (`REFERENCE` 또는 `ASSUMED`) | 필수 (제안) | — | 데이터 계약인지 가정인지 | — | — |

- 계산 결과(`expected_publication_at`)를 실제 관측의 `data_available_at`으로 쓰지 않는다 (A: INV-07). 백테스트에서 이 규칙을 지연 가정의 근거로 쓰는 것은 `DataLatencyAssumption`을 통해서만 [제안] (D3A-13).

### TC-D7 `AccountSchedule` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 계좌 단위의 의사결정 일정과 평가 일정 |
| 분류 | Policy Input (계좌 설정) |
| 입력·출력 관계 | 평가 주기 (`valuation_at(t−1)`, `valuation_at(t)`]를 정의한다. 체결의 주기 귀속(P0-03B)과 평가 환율 선택(TC-E4)의 기준 |
| 예상 예외 | 평가 시각이 오름차순이 아님 → `TIME_ORDER_VIOLATION` |
| 참조하는 타입 | TC-D1, TC-D2 |
| V1 대응 | 없음. V1 평가는 가격 날짜마다 adjusted 종가로 한다 (ADR-0007 §3.1) |
| 관련 ADR·질문 | ADR-0007 C7-4, Q7-1. ADR-0001 I-3. ADR-0008 Q8-1. D3A-21 |
| 승인 구분 | [ACCEPTED] 계좌 단위 일정, 평가 주기 정의. [제안] 필드 이름. 시각 값은 미결정 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `account_ref` | 미정 (계좌 계약은 P0-03B) | 미결정 | — | 계좌 | — | — |
| `decision_times` | `Instant` 시퀀스, 또는 `ZonedLocalTime` 규칙 + 달력 | 필수 (A: C7-4). 값은 미결정 (Q7-1) | — | 의사결정 시각 | 실제 시각 | 오름차순 |
| `valuation_times` | `Instant` 시퀀스 | 필수 (A: C7-4). 값은 미결정 (Q7-1) | — | `valuation_at(t)` | 실제 시각 | 엄격한 오름차순. 주기는 왼쪽 열림·오른쪽 닫힘 (A: I-3) |
| `fx_valuation_reference_rule` | 미정 | 미결정 (Q8-1) | — | 주기별 FX 평가 기준 시각 규칙 | — | — |

- 기준통화는 계좌의 속성이다. 계좌 계약(P0-03B)의 필드 후보이며 이 타입에 두지 않는다 [제안]. 평가 환율 집합(TC-E4)은 기준통화를 명시적으로 가진다.

### TC-D8 `MarketDataStatus` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 판정 시각에서 상품의 데이터 상태 |
| 분류 | Enumeration |
| 입력·출력 관계 | `DataStatusAssessment`의 출력. 평가 정책·적격성 정책의 입력 |
| 예상 예외 | 다른 값 → `UNSUPPORTED_OR_UNAPPROVED` |
| V1 대응 | 없음 (V1은 휴장과 결측을 구분하지 않음) |
| 관련 ADR·질문 | ADR-0007 §6.4, 승인 원칙 5 |
| 승인 구분 | [ACCEPTED] 정확히 네 값. [APPROVED_PRINCIPLE] D3A-19 원칙 (6): 세션별 내부 상태가 있어도 외부 값을 늘리지 않음, 판정 불가를 다섯 번째 값으로 만들지 않음 (INV-24) |

| 값 | 의미 |
|---|---|
| `FRESH` | 정상 |
| `MARKET_CLOSED` | 마지막 공식 가격 이후 세션 없음. 마지막 가격은 정책이 고른 평가가격이며 현재 시장가치와 같다고 단정하지 않음 |
| `PENDING_OFFICIAL` | 세션은 끝났고 공식 가격의 공표 예상 시각이 아직 오지 않음 |
| `MISSING_DATA` | 세션이 있었고 공표 예상 시각이 지났는데 실제로 이용 가능한 공식 가격이 없음 |

- 이 네 조건은 ADR-0007 §6.4 문구 그대로 적용하면 서로 겹칠 수 있다. 세션별 상태 정보와 명시적 평가 주기로 판정하고 외부 값은 이 네 가지를 유지한다는 원칙은 [APPROVED_PRINCIPLE] D3A-19 (2026-10-17, 결정 등록부 §9 CA-19). 집계 우선순위와 판정 기준 세션의 정확한 규칙은 D3A-19.1~19.4 (미결정).

### TC-D9 `DataStatusAssessment` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 판정 시각 τ에서 상품 하나의 데이터 상태와 신선도, 그 근거를 기록한다 |
| 분류 | Derived Record |
| 입력·출력 관계 | 달력 + 세션 + 공표 예상 + 공식 가격 관측 (모두 τ 기준 PIT) → 상태 기록. 평가 정책, 적격성 정책(ADR-0002 `STALE_DATA`), 거래 전 검사(ADR-0003 S-7)의 입력 |
| 예상 예외 | 판정에 τ 이후에 이용 가능해진 정보를 씀 → `PIT_VIOLATION` [제안] |
| 참조하는 타입 | TC-A4, TC-D1, TC-D8, TC-D5, TC-C4, TC-D4 |
| V1 대응 | 없음 |
| 관련 ADR·질문 | ADR-0007 §6.4 (상태와 함께 "사용한 공식 가격의 관측 시각, 경과 시간, 사유"를 기록), Q7-3, Q7-5. D3A-19 (원칙 승인, 결정 등록부 §9 CA-19) |
| 승인 구분 | [ACCEPTED] 상태 4종, 달력과 관측을 함께 판정, 관측 시각·경과 시간·사유 기록. [APPROVED_PRINCIPLE] D3A-19 (2026-10-17): 세션별 상태와 명시적 평가 주기를 판정에 씀 (원칙 (1)), 같은 입력이면 호출 이력과 관계없이 같은 결과 (원칙 (2)), 늦은 도착 시 같은 세션을 재판정할 수 있어야 함 (원칙 (3)), 확정한 판정 기록을 나중 데이터로 조용히 덮어쓰지 않고 새 기록을 남기는 방향 (원칙 (7)). [제안] 아래 필드의 구성과 형태 (기준 세션, 평가 주기, 세션별 상태, 판정 목적, 정기·비정기 구분) |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `tradable_unit` | `TradableUnitRef` | 필수 (제안) | — | 대상 | — | — |
| `evaluated_at` | `Instant` | 필수 (A: "평가 시각 또는 의사결정 시각 τ") | — | 판정 시각 τ | — | — |
| `purpose` | 열거 (`VALUATION`, `DECISION`) | 미결정 (D3A-19.7) | — | 평가용인지 의사결정 입력용인지 | — | — |
| `status` | `MarketDataStatus` | 필수 (A) | — | 상태 | — | 네 값 중 하나 |
| `reference_sessions` | 세션 ID 목록 | 필수 (제안). 판정이 기준 세션 집합에 따라 결정되어야 한다는 것은 승인 원칙 D3A-19 (2)이지만, 그것을 기록 필드로 둘지는 D3A-19.8 (미결정) | — | 판정의 기준이 된 세션들 | — | 기준 세션을 정하는 규칙은 D3A-19.1~19.3 (미결정). R0의 예시 "직전 판정 이후 끝난 세션"은 반복 판정 반례로 철회했다 (R1) |
| `valuation_period` | (`Instant`, `Instant`] (가칭) | 필수 (제안). 평가 주기를 판정에 쓰는 것은 승인 원칙 D3A-19 (1)·(2)이지만, 기록 필드로 둘지는 D3A-19.8, 형태와 시작·종료 규칙은 D3A-19.1~19.3 (미결정) | — | 판정이 속한 평가 주기. ADR-0001 I-3의 왼쪽 열림, 오른쪽 닫힘 구간과 같은 형태 [제안] | — | — |
| `session_states` | 기준 세션별 내부 상태 목록 (가칭) | 필수 (제안). 세션별 상태를 판정에 쓰고 미해결 세션을 가리지 않는 것은 승인 원칙 D3A-19 (1)·(5)이지만, 기록 필드로 둘지는 D3A-19.8, 내부 상태 값과 집계 규칙은 D3A-19.4 (미결정) | — | 기준 세션마다의 내부 상태 (예: 공식 가격 이용 가능 / 공표 대기 / 기한 경과 미도착. R1 대안 3의 가칭) | — | 외부 `status`의 값을 늘리지 않는다 (P: D3A-19 원칙 (6)) |
| `assessment_kind` | 열거 (`SCHEDULED`, `UNSCHEDULED`, 가칭) | 미결정 (D3A-19.1, D3A-19.3) | — | 정기 판정인지, 정기 일정 밖의 재판정인지. 비정기 재판정이 어느 주기에 속하는지는 D3A-19.3 | — | — |
| `used_observation` | `RawPriceObservation` 참조 | 조건부: 공식 가격을 썼으면 필수 (A: "사용한 공식 가격의 관측 시각") | — | 사용한 공식 가격 관측 | 그 관측의 `observed_at`, `data_available_at` | `data_available_at ≤ evaluated_at` |
| `elapsed` | 시간 길이 | 조건부: `used_observation`이 있으면 필수 (A: ADR-0007 §6.4 "경과 시간") | 시간 | 경과 시간. 기준점(τ − 사용한 관측의 `observed_at`)은 [제안] | — | ≥ 0 |
| `reason` | 사유 코드 | 필수 (A: "사유") | — | 휴장 / 결측 / 공표 대기 등 | — | 휴장으로 인한 경과와 결측을 다른 사유로 표시 (A) |
| `calendar_basis` | 달력 참조 + `as_of` | 필수 (제안) | — | 판정에 쓴 달력 | — | 달력이 없으면 LIVE에서 `MISSING_DATA` (ADR 본문: AT-0007-5) |

- `MARKET_CLOSED`의 `used_observation` 가격은 정책이 고른 평가가격이다. 현재 시장가치와 같다고 단정하지 않고 체결 가격으로 쓰지 않는다 (INV-25).
- 신선도 임계값 비교는 이 기록이 아니라 정책 계층이 한다 (Q7-5).
- 늦게 도착한 가격은 새 판정 기록으로 반영하고, 이미 확정해 남긴 판정 기록을 그 때문에 조용히 덮어쓰지 않는다 ([APPROVED_PRINCIPLE] D3A-19 원칙 (7). 기록 형식, 보존 방식, 오류 정정 절차는 D3A-19.8).
- 같은 세션의 공식 가격이 늦게 도착하면 그 세션을 다시 판정할 수 있다 (원칙 (3)). 결측 세션은 다음 세션 시작이나 재호출 때문에 휴장(`MARKET_CLOSED`)이 되지 않고, 미해결 세션은 다음 세션 때문에 조용히 가려지지 않는다 (원칙 (4)·(5)). 이 성질을 내는 기계적 규칙은 미결정이다 (D3A-19.2~19.5). 예: 16:30 기록 `MISSING_DATA`는 그대로 두고, 16:50에 새 기록 `FRESH`를 남긴다 (AT-03A-05).

---

## 6. FX

### TC-E1 `FxRate` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 방향이 명시된 환율 값 |
| 분류 | Value Object |
| 입력·출력 관계 | `convert(MoneyAmount(a, 분모), FxRate) = MoneyAmount(a × 값, 분자)` |
| 예상 예외 | 값 ≤ 0, 비유한 값 → `INVALID_VALUE` (A). 분자 = 분모 → `INVALID_VALUE` [제안]. 환산할 금액의 통화 ≠ 분모 → `CURRENCY_MISMATCH` [제안] |
| 참조하는 타입 | TC-B4, TC-B5 |
| V1 대응 | `fx_to_base` (상품·날짜별 스칼라, 금액에 곱함 `fx.py:23`. 통화 표시 없음) |
| 관련 ADR·질문 | ADR-0008 §5.1 (BC/κ 방향), X8-4, ADR-0001 §6.2. D3A-26 |
| 승인 구분 | [ACCEPTED] 방향 BC/κ, > 0, 방향 혼합 금지, 반대 방향은 저장 단계에서 명시적으로 뒤집음. [제안] 분자·분모 필드 표현 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `numerator_currency` | `CurrencyCode` | 필수 (제안) | — | 금액의 통화 (평가·결정 환율에서는 BC) | — | ≠ 분모 |
| `denominator_currency` | `CurrencyCode` | 필수 (제안) | — | 1단위의 통화 (κ) | — | — |
| `value` | `Num` | 필수 (A) | 분자/분모 (예: KRW/USD) | 분모 통화 1단위 = 값 × 분자 통화 | 시각은 `FxObservation`이 가짐 | 유한, > 0 (A) |

- 예: `FxRate(numerator=KRW, denominator=USD, value=1400)` → 1,000 USD = 1,400,000 KRW.
- `fx[BC,t] = 1`은 관측으로 저장하지 않는다 (A: ADR-0001 §6.2). 분자가 BC가 아닌 교차 환율의 사용은 D3A-26.

### TC-E2 `FxObservation` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 환율 관측 (값, 방향, 시각, 출처) |
| 분류 | Observation |
| 입력·출력 관계 | Data Boundary가 공급자 값으로 만든다 (반대 방향이면 뒤집은 새 관측). `ValuationFxSet`, `DecisionFxSnapshot`에 들어간다 |
| 예상 예외 | `ObservationMeta`와 `FxRate`의 예외. 공급자 방향을 알 수 없음 → `MISSING_REQUIRED` [제안] |
| 참조하는 타입 | TC-E1, TC-C3 |
| V1 대응 | `ExecutionMarketDay.fx_to_base` (`system_backtest.py:38`, 시각·통화 없음) |
| 관련 ADR·질문 | ADR-0004 §5.1 (FX 관측: `observed_at`, `data_available_at`, 통화쌍), ADR-0008 §6.5. Q8-1. D3A-26, D3A-27 |
| 승인 구분 | [ACCEPTED] 통화쌍 키, 관측 시각, 이용 가능 시각. [제안] 반전 표시 필드 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `rate` | `FxRate` | 필수 (A) | 분자/분모 | 저장 방향의 환율 | — | — |
| `meta` | `ObservationMeta` | 필수 (A: 관측 시각·이용 가능 시각) | — | 시각, 출처 | — | — |
| `rate_type` | 열거 (중간값 / 고시 / bid / ask) | 미결정 (Q8-1) | — | 환율 종류 | — | — |
| `inverted_from_source` | `bool` | 필수 (제안) | — | Data Boundary가 공급자 값을 뒤집었는지 | — | 뒤집었으면 원래 값·방향을 출처에서 추적 가능 |

### TC-E3 `FxRole` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 환율을 어떤 용도로 쓰는지 표시한다 |
| 분류 | Enumeration |
| 관련 ADR·질문 | ADR-0008 §6.5 표. ADR-0001 Q1-4, Q8-11 |
| 승인 구분 | [ACCEPTED] 평가, 사이징·거래 전 위험, 환전, 수수료 환산의 역할 구분. [제안] 값 이름 |

| 값 | 의미 | 승인 상태 |
|---|---|---|
| `VALUATION` | 주기별 통화별 평가 환율 | 역할 [ACCEPTED]. 시각은 Q8-1 |
| `DECISION` | `decision_at`까지 이용 가능한 사이징·위험 환율 | [ACCEPTED] |
| `CONVERSION_EXECUTION` | 실제 환전 실행 환율 (P0-03B) | 역할 [ACCEPTED] |
| `FEE_CONVERSION` | 수수료 환산 환율 | **미결정** (ADR-0001 Q1-4, Q8-11) |

### TC-E4 `ValuationFxSet` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 평가 주기 하나의 통화별 평가 환율 (통화별 정확히 하나) |
| 분류 | Derived Record (선택 결과) |
| 입력·출력 관계 | FX 관측들 + 평가 시각 + FX 평가 기준 시각 → 통화별 평가 환율. NAV 계산(P0-03B)의 입력 |
| 예상 예외 | 같은 통화에 두 값 → `INVALID_VALUE` (A: X8-5). 분자 ≠ 기준통화 → `CURRENCY_MISMATCH` [제안]. 키와 분모 불일치 → `CURRENCY_MISMATCH` [제안] |
| 참조하는 타입 | TC-D1, TC-B4, TC-E2 |
| V1 대응 | 없음 (V1은 상품별 `fx_to_base`. 같은 통화의 두 상품이 다른 값을 가져도 막지 않음, ADR-0001 R2) |
| 관련 ADR·질문 | ADR-0008 §5.1 (FX Valuation Time), §6.2, §6.5, X8-3, X8-5. Q8-1, Q8-2, Q8-7. D3A-27, D3A-28 |
| 승인 구분 | [ACCEPTED] 주기마다 통화별 평가 환율 하나, 결측 시 1로 대체 금지, 표시 없는 이전 값 금지, 평가 시각과 FX 기준 시각 기록. [제안] 결측 통화 표시 필드 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `valuation_at` | `Instant` | 필수 (A) | — | 평가 주기의 평가 시각 | — | — |
| `base_currency` | `CurrencyCode` | 필수 (A) | — | 기준통화 | — | 모든 환율의 분자 |
| `fx_valuation_reference_time` | `Instant` | 필수 (A: FX Valuation Time). 값의 규칙은 미결정 (Q8-1) | — | 평가 환율을 고르는 기준 시각 | — | 시장 평가 시각과 다를 수 있음. 둘 다 기록 (A) |
| `rates` | 통화 κ → `FxObservation` 매핑 | 필수 | BC/κ | 통화별 평가 환율 | 각 관측의 시각 | 통화마다 최대 하나 (A). 분모 = 키. 기준통화 항목 없음 (항등) |
| `missing_currencies` | 통화 집합 | 필수 (제안) | — | 필요하지만 환율이 없는 통화 | — | 비어 있지 않으면 NAV 확정 불가 (A: ADR-0008 §6.2) |
| 이전 환율 사용 표시 | 미정 | 미결정 (Q8-7) | — | 정책이 허용할 때만, 신선도와 함께 | — | 표시 없는 복사 금지 (A) |

### TC-E5 `DecisionFxSnapshot` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 의사결정 시각에 이용 가능했던 통화별 환율 (사이징·거래 전 위험용) |
| 분류 | Derived Record (선택 결과) |
| 입력·출력 관계 | FX 관측들 + `decision_at` → PIT 환율. 위험 예산·명목가치 계산의 입력 |
| 예상 예외 | `data_available_at > decision_at`인 환율 포함 → `PIT_VIOLATION` (A: I-1) |
| 참조하는 타입 | TC-D1, TC-B4, TC-E2 |
| V1 대응 | 없음 (V1은 같은 날 `fx_to_base` 하나를 손익·사이징·비용·명목가치에 모두 씀, ADR-0008 §3.1) |
| 관련 ADR·질문 | ADR-0008 §6.5 ("평가 환율과 다를 수 있으며 둘 다 기록"), ADR-0001 I-1 |
| 승인 구분 | [ACCEPTED] 결정 시점 이용 가능 환율, 평가 환율과 별도 기록. [제안] 필드 이름 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `decision_at` | `Instant` | 필수 (A) | — | 의사결정 시각 | — | — |
| `base_currency` | `CurrencyCode` | 필수 (A) | — | 기준통화 | — | 분자 |
| `rates` | 통화 κ → `FxObservation` | 필수 | BC/κ | 통화별 결정 환율 | 각 관측의 시각 | 각 관측의 `data_available_at ≤ decision_at` (A) |
| `missing_currencies` | 통화 집합 | 필수 (제안) | — | 필요하지만 이용 가능한 환율이 없는 통화 | — | LIVE에서 그 통화 상품의 위험 증가 차단 (A: ADR-0008 §6.5) |

---

## 7. Input Bundles

### TC-F1 `MarketObservationSet` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 묶음 (1): 시장 관측값만 담는 입력 계약 |
| 분류 | Input Contract |
| 입력·출력 관계 | Data Boundary 검증과 PIT 뷰를 거쳐 Engines가 계층에 넘긴다 |
| 예상 예외 | 체결 가정·정책 값 포함 → 책임 경계 위반 (`UNSUPPORTED_OR_UNAPPROVED`) (A: INV-15) |
| 참조하는 타입 | TC-C4, TC-C5, TC-E2 |
| V1 대응 | `ExecutionMarketDay.quotes`, `fx_to_base` (나머지 필드와 섞여 있음, `system_backtest.py:28-47`) |
| 관련 ADR·질문 | ADR-0004 §6.3 (1). D3A-31 |
| 승인 구분 | [ACCEPTED] 관측값 묶음의 분리 (월물별 quote, 월물별 평가가격, 통화별 FX). [제안] 타입 구성 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `raw_prices` | `RawPriceObservation` 집합 | 필수 (제안. 비어 있을 수 있음) | — | raw 가격 관측 | 각 관측 | 값은 관측값 (관측 타입). 이용 가능 시각의 근거는 각 관측의 `availability_basis` |
| `quotes` | `MarketQuote` 집합 | 필수 (제안. 비어 있을 수 있음) | — | quote 관측 | 각 관측 | 같음 |
| `fx` | `FxObservation` 집합 | 필수 (제안. 비어 있을 수 있음) | — | 환율 관측 | 각 관측 | 같음 |

- 참조 데이터(상품 사양, 달력, 롤·기업 행사, 거래 제약)는 세 묶음 밖의 별도 참조 데이터 입력이다 (ADR-0004 §5.1의 "참조 데이터"·"참조 이벤트" 분류). 별도 묶음 타입을 둘지는 D3A-31.

### TC-F2 `ExecutionAssumptionSet` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 묶음 (2): Backtest·Paper의 체결 시뮬레이션 가정 |
| 분류 | Input Contract |
| 입력·출력 관계 | Engines 설정. Cost·Execution Model 계층의 순수 함수가 적용한다 (ADR-0004 §6.3) |
| 예상 예외 | 관측값 포함 → 책임 경계 위반. Live 모드에서 사용 → `UNSUPPORTED_OR_UNAPPROVED` [제안] (Live는 실제 브로커 체결·수수료를 씀) |
| 참조하는 타입 | TC-F3, TC-C2 |
| V1 대응 | `ExecutionMarketDay.commission_per_contract`, `slippage_ticks` (일별 필드, `system_backtest.py:36, 40`) |
| 관련 ADR·질문 | ADR-0004 §6.3 (2), §6.6, §9 ("슬리피지 0" 같은 낙관적 기본값이 드러남). ADR-0001 Q1-1. D3A-13, D3A-31 |
| 승인 구분 | [ACCEPTED] 수수료표, 슬리피지 모델, 체결 규칙, 데이터 지연 가정을 가정값 묶음으로 분리, 적용 기간. [제안] 각 요소의 명시 필수 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `applicable_period` | (`Instant`, `Instant`) | 필수 (A: "적용 기간") | — | 가정의 적용 기간 | — | 시작 < 끝 |
| `fill_rule` | 미정 | 필수 (제안). 내용은 미결정 (Q1-1) | — | 어느 quote·시각에서 체결하는지 | — | — |
| `slippage_model` | 미정 (V1: 정수 tick) | 필수 (제안: 0이어도 명시) | tick | 슬리피지 가정 | — | 0을 기본값으로 두지 않음 [제안] |
| `simulated_fee_schedule_ref` | 미정 | 필수 (제안) | — | 가상 수수료표 (선물 계약당, ETF 비율·최소·세금은 새 공식) | — | — |
| `data_latency_assumptions` | `DataLatencyAssumption` 시퀀스 | 미결정 (Q4-3. 없을 때 fail-closed가 ADR-0004 권장) | — | 백테스트 이용 가능 시각 가정 | — | — |
| `provenance` | `ValueProvenance` | 필수 (제안) | — | `ASSUMED` 고정 | — | — |

### TC-F3 `DataLatencyAssumption` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 백테스트에서 관측의 `data_available_at`을 정하는 가정 |
| 분류 | Execution Assumption |
| 입력·출력 관계 | 관측의 `observed_at` 또는 세션 종료 → 가정된 `data_available_at`. 관측의 `availability_basis = ASSUMED`가 참조한다 |
| 예상 예외 | 지연 < 0 → `INVALID_VALUE` |
| 참조하는 타입 | TC-D6 (선택) |
| V1 대응 | 없음 (V1은 시각이 없음) |
| 관련 ADR·질문 | ADR-0004 §6.5, Q4-3. ADR-0011 FP-11 (가정은 입력 fingerprint에 포함), Q11-8. D3A-13 |
| 승인 구분 | [ACCEPTED] 백테스트의 `data_available_at`은 가정값이며 체결 가정 묶음에 속하고 manifest에 기록. [제안] 형태 전체 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `scope` | (데이터셋, 가격 종류, 거래소) | 필수 (제안) | — | 적용 범위 | — | — |
| `basis` | 열거 (`OBSERVED_AT_PLUS`, `SESSION_END_PLUS`, `PUBLICATION_EXPECTATION`) | 미결정 (D3A-13) | — | 가정의 기준 | — | — |
| `delay` | 시간 길이 | 미결정 (값은 사용자) | 시간 | 지연 | — | ≥ 0 |
| `provenance` | `ValueProvenance` | 필수 (제안) | — | `ASSUMED` | — | — |

### TC-F4 `RiskPolicyInput` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 묶음 (3): 위험 목표, 한도, 평가 정책 선택, 적격성 정책, 증거금 요구량 |
| 분류 | Input Contract |
| 입력·출력 관계 | Portfolio & Risk, Research(적격성), Accounting(평가 정책)이 읽는다 |
| 예상 예외 | 프로필 없음·알 수 없음 → `UNSUPPORTED_OR_UNAPPROVED` (A: §8.0). 승인되지 않은 입력(Q4-7) → `UNSUPPORTED_OR_UNAPPROVED`. Paper/Live에서 `V1_COMPAT` → 거부 (A) |
| 참조하는 타입 | TC-F5, TC-F6, TC-F7, TC-F8 |
| V1 대응 | `BacktestConfig` (`backtest_config.py:71-191`), `PortfolioRiskPolicy` (`risk_guardrail.py:157-185`), `ExecutionMarketDay.daily_cash_vol_target`, `margin_per_contract_base` |
| 관련 ADR·질문 | ADR-0004 §6.3 (3), ADR-0003 §6.4, §6.6, ADR-0002 §6.4, ADR-0007 §6.5. Q3-1, Q2-1, Q2-2, Q4-7, Q7-3. D3A-32, D3A-33 |
| 승인 구분 | [ACCEPTED] 위험 입력의 분리, 프로필 명시, LIVE 위험 예산은 결정 시점 계좌로 계산, 한도·임계값은 설정되어야 함(값은 미정). [제안] 구성 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `profile` | `PolicyProfile` | 필수 (A) | — | 정책 프로필 | — | 기본값 없음 |
| `risk_target` | `Num` | 미결정 (값은 사용자) | 연율 소수 (frac/y) | 연 변동성 목표 | 적용 기간 | > 0 |
| `risk_budget_mode` | 열거 (`FROM_DECISION_ACCOUNT`, `V1_LEGACY_WITH_EXPLICIT_LEVEL`, `EXPLICIT_SERIES`) | 필수 (제안) | — | 위험 예산 출처 | — | `LIVE`는 `FROM_DECISION_ACCOUNT`만 (A: ADR-0004 §6.3). `EXPLICIT_SERIES`는 Q4-7 결정 전 거부. `V1_LEGACY_WITH_EXPLICIT_LEVEL`은 `V1_COMPAT` 재현 전용 (A: AT-0004-4) |
| `risk_limits` | 미정 (ADR-0003 지표별 한도) | 값은 미결정 (Q3-1). Paper/Live에서 없으면 그 지표는 판단 불가 → 위험 증가 차단 (A: ADR-0003 §6.2.2) | 배수, 소수 | 위험 한도 | 적용 기간 | — |
| `valuation_policy` | `ValuationPolicySelection` | 필수 (A: 기본값 없음, ADR-0007 §6.5) | — | 평가 정책 | — | — |
| `eligibility_policy` | 미정 (임계값) | 값은 미결정 (Q2-1, Q2-2). LIVE에서 없으면 `POLICY_NOT_CONFIGURED` (A) | — | 적격성 정책 | — | — |
| `margin_requirements` | `MarginRequirementRecord` 집합 | 미결정 (Q4-5, Q3-11) | — | 증거금 요구량 | — | 출처 표시 (A) |
| `explicit_risk_budget` | `ExplicitRiskBudgetSeries` | **비허용** (Q4-7 결정 전) | — | 자리표시자 | — | 들어오면 거부 |

### TC-F5 `PolicyProfile` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 실행의 정책 프로필 |
| 분류 | Enumeration |
| 예상 예외 | 누락, 알 수 없는 값, 빈 문자열, `None`, 대소문자 변형 → `UNSUPPORTED_OR_UNAPPROVED` (A). Paper/Live에서 `V1_COMPAT`·`RESEARCH` → 거부 (A) |
| V1 대응 | 기존 V1 API의 동작이 곧 암묵적 `V1_COMPAT` (A: §8.0) |
| 관련 ADR·질문 | ADR-0001~0003 §8.0, ADR-0002 §6.1, §6.4, ADR-0005 E-1 |
| 승인 구분 | [ACCEPTED] 전부 |

| 값 | 사용 가능한 실행 모드 |
|---|---|
| `V1_COMPAT` | 기존 V1 API(암묵적), 새 연구 API(명시적 재현 목적) |
| `RESEARCH` | 새 연구 API |
| `LIVE` | Paper, Live (유일하게 허용) |

### TC-F6 `ValuationPolicySelection` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 데이터 상태별 평가 처리와 환율 결측 처리를 명시적으로 고른다 |
| 분류 | Policy Input |
| 입력·출력 관계 | `DataStatusAssessment` + 선택 → 평가가격 선택 (P0-03B가 기록) |
| 예상 예외 | 선택 누락 → `MISSING_REQUIRED` (A: 기본값 없음). 금지된 처리(가격 0, 보간, 표시 없는 forward fill, 포지션 삭제) → `UNSUPPORTED_OR_UNAPPROVED` (A: X7-1~X7-3) |
| 참조하는 타입 | TC-D8, TC-F5 |
| V1 대응 | 없음 (V1은 결측 시 fail-fast) |
| 관련 ADR·질문 | ADR-0007 §6.5, Q7-3, Q7-4, Q7-5. ADR-0008 Q8-7. D3A-33 |
| 승인 구분 | [ACCEPTED] 명시적 선택과 기본값 없음 (ADR-0007 원칙 8, §6.5), 금지 사항 (X7-1~X7-3). 정책이 승인·구현되기 전에는 평가에 필요한 가격이 없으면 fail-fast (ADR-0002 §6.2, ADR-0007 §6.8). **"LIVE에서 `MISSING_DATA` 상품의 위험 증가 차단"은 ADR-0007 §6.5의 "권장 처리" 열에만 있어 승인되지 않았다 (Q7-3의 선택지).** [제안] 선택지 이름. 선택지의 값과 채택은 미결정 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `profile` | `PolicyProfile` | 필수 (A) | — | 선택이 적용되는 프로필 | — | — |
| `on_market_closed` | 선택지 (후보: 표시된 마지막 공식 가격 사용, …) | 필수 (A). 값은 미결정 (Q7-3) | — | `MARKET_CLOSED` 처리 | — | 가격 0·포지션 삭제 금지 |
| `on_pending_official` | 선택지 (후보: 잠정 평가 표시, 평가 연기, 장중 가격 명시 허용) | 필수 (A). 값은 미결정 (Q7-4) | — | `PENDING_OFFICIAL` 처리 | — | 장중 가격을 표시 없이 공식 가격처럼 쓰지 않음 |
| `on_missing_data` | 선택지 (후보: 실행 중단, 표시된 마지막 가격 + 위험 증가 차단) | 필수 (A). 값은 미결정 (Q7-3) | — | `MISSING_DATA` 처리 | — | 보간·0·표시 없는 복사 금지 (A). "LIVE 위험 증가 차단"은 Q7-3의 선택지이며 미승인 |
| `on_missing_fx` | 선택지 | 필수 (A: 기본값 없음, Q8-7). 값은 미결정 | — | 환율 결측 처리 | — | 1 대입·표시 없는 복사 금지 |
| `freshness_limits` | 미정 | 값은 미결정 (Q7-5) | 시간 | 신선도 허용 기간 | — | 휴장과 결측을 따로 둘지 미정 |

### TC-F7 `MarginRequirementRecord` (가칭)

| 항목 | 내용 |
|---|---|
| 책임 | 거래 단위별 증거금 요구량과 출처 |
| 분류 | Reference Data / Assumption (묶음 3) |
| 입력·출력 관계 | 거래 전 위험 L1의 margin usage 입력 |
| 예상 예외 | 출처 없음 → `MISSING_REQUIRED` (A). 음수·비유한 값 → `INVALID_VALUE` |
| 참조하는 타입 | TC-A4, TC-B5, TC-A15 |
| V1 대응 | `ExecutionMarketDay.margin_per_contract_base` (월물 → 기준통화 금액 dict, 포트폴리오 사후 가드레일에서만 사용 `portfolio_backtest.py:111-122`) |
| 관련 ADR·질문 | ADR-0004 §6.3, Q4-5. ADR-0003 Q3-11. ADR-0008 Q8-6. ADR-0012 Q12-6. D3A-08 |
| 승인 구분 | [ACCEPTED] 증거금은 참조 데이터 또는 가정값이며 출처를 기록. [제안] 필드 구성 |

| 필드 | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `tradable_unit` | `TradableUnitRef` | 필수 (제안) | — | 대상 월물 | — | 선물 월물 |
| `amount_per_contract` | `MoneyAmount` | 필수 (제안) | 통화/계약 | 계약당 증거금 | 출처의 `as_of` | 유한, ≥ 0. 통화는 Q8-6 |
| `model` | 열거 (계약당 단순 합 / 포트폴리오) | 미결정 (Q3-11) | — | 증거금 모델 | — | — |
| `provenance` | `ReferenceProvenance` (`REFERENCE` 또는 `ASSUMED`) | 필수 (A: 출처 기록) | — | 거래소·브로커 공지인지 가정인지 | — | — |

### TC-F8 `ExplicitRiskBudgetSeries` (가칭, 자리표시자)

| 항목 | 내용 |
|---|---|
| 책임 | `RESEARCH`의 날짜별 위험 예산 직접 입력. **Q4-7이 결정되기 전에는 받지 않는다** |
| 분류 | Policy Input (자리표시자, **비허용**) |
| 입력·출력 관계 | 없음. 들어오면 거부한다 (ADR-0005 E-10: 받은 입력을 조용히 무시하지 않음) |
| 예상 예외 | 어떤 프로필에서든 → `UNSUPPORTED_OR_UNAPPROVED` (Q4-7 결정 전) |
| 참조하는 타입 | TC-B5, TC-D1, TC-F5 |
| V1 대응 | `ExecutionMarketDay.daily_cash_vol_target`. 경로에 따라 의미가 다르다 (ADR-0004 §3.3). V1 재현은 이 타입이 아니라 변환 경계에서 수준을 명시받아 처리한다 (A: AT-0004-4) |
| 관련 ADR·질문 | ADR-0004 §6.3, Q4-7. ADR-0005 E-11. D3A-32 |
| 승인 구분 | **허용 여부 미결정 (Q4-7).** 아래 필드는 허용을 검토할 때 ADR-0004 §6.3이 요구하는 조건을 옮긴 것이다. "비허용"은 Q4-7의 "금지" 결정이 아니라 미결정 상태의 fail-closed다 |

| 필드 (허용 검토 시 필요) | 자료형 후보 | 필수 여부 | 단위 | 의미·출처 | 시점 의미 | 불변조건 |
|---|---|---|---|---|---|---|
| `level` | 열거 (`ACCOUNT`, `INSTRUMENT`) | (허용 시) 필수 (A: ADR-0004 §6.3 "수준") | — | 위험 예산 수준 | — | 기본값 없음 |
| `unit` | 고정 (BC/d 등) | (허용 시) 필수 (A: "단위") | BC/d | 단위 | — | — |
| `values` | (`decision_at` 또는 라벨, `MoneyAmount`) 시퀀스 | (허용 시) 필수 | BC/d | 날짜별 값 | 각 값의 이용 가능 시각 | 각 값의 `data_available_at ≤ decision_at` (A: I-1) |
| `source` | `str` | (허용 시) 필수 (A: "출처") | — | 값의 출처 | — | — |
| `profile` | `PolicyProfile` | (허용 시) 필수 (A: "적용할 정책 프로필") | — | — | — | `LIVE` 불가 (A) |
| manifest 기록 | — | (허용 시) 필수 (A: "재현성 기록") | — | — | — | — |

---

## 8. 개정 이력

| 개정 | 날짜 | 내용 |
|---|---|---|
| R0 | 2026-10-17 | 최초 작성 (P0-03A). 상태 PROPOSED, 사용자 검토 대기 |
| R1 | 2026-10-17 | P0-03A-R1 (문서 전용 보완. 독립 검토 지적 반영 포함: TC-B1 표 깨짐 수정, 반올림 금지의 [제안] 표기, TC-C4 오류 표기). TC-B1: lot 규칙의 세 상황(새 주문, 부분 체결, 기업 행사 후 보유)을 구분하고 실제 수량 처리를 D3A-49 보류로 연결 (I6-5 의미는 바꾸지 않음). TC-C4·TC-C5: raw 가격과 체결 가능성을 구분 (INV-33). TC-D9: `reference_sessions` 예시 철회, `assessment_kind` 후보 추가, 판정 기록 불변 제안 (D3A-19). 상태 PROPOSED 유지 |
| R1-FIX | 2026-10-17 | P0-03A-R1-FIX. TC-C4·TC-C5의 quote 변환 문구를 "계약에 변환 경로를 두지 않음, 생성자 수준 강제는 미확인"으로 정정 (AT-03A-25 (b)). 2차: TC-C4 평가·체결 조건 문구를 AT-03A-25 (c)·(d)와 맞춤. 3차: 조건을 필요조건으로 표기 |
| R2 | 2026-10-17 | P0-03A-FINAL. 2026-10-17 사용자의 D3A-19·D3A-49·D3A-50 핵심 원칙 승인을 반영. 범례에 "(P: D3A-xx)"와 [APPROVED_PRINCIPLE] 표기 추가. TC-B1: 실제 수량·주문 수량 역할 구분(별도 TC는 만들지 않음), 원칙 (1)·(3)~(6) 승인 표기, 원칙 (2)는 ADR-0006 I6-5와 충돌하여 적용 보류 (CA-49). TC-C4·TC-C5: Raw 관측·Quote·평가가격·시뮬레이션 체결가·실제 체결가 구분을 승인 원칙으로 표기. TC-D8·TC-D9: D3A-19 원칙 표기, `valuation_period`·`session_states` 필드 후보 추가 (형태는 미결정), 하위 질문 ID로 연결. TC 수 51개 유지. 상태 PROPOSED 유지. 독립 검토 반영: TC-D9 세 필드를 "필수 (제안)"으로 정정(판정 원칙과 기록 필드를 구분), 원칙 (6)의 확장을 [제안]으로 구분, 원칙 (3)·(7) 문구를 원문에 맞춤, TC-A8 `lot_size`에 CA-49 연결. 재확인 반영: TC-C4의 "승인된 체결 가정" 한정을 [제안]으로 표시, "단주"를 "소수 주"로 정리 |
