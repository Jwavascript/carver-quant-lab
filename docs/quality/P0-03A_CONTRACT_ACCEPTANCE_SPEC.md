# P0-03A 계약 인수 테스트 명세 (Contract Acceptance Specification)

| 항목 | 내용 |
|---|---|
| 작업 | P0-03A Common Domain Contracts Design |
| 기준 커밋 | `24cae00` |
| 작성일 | 2026-10-17 |
| 개정 | R1, R1-FIX, R2 (2026-10-17. R2 = P0-03A-FINAL: D3A-19·49·50 핵심 원칙 승인 반영, 판정 FINAL BLOCKED. §8) |
| 문서 상태 | **PROPOSED (사용자 검토 대기).** 인수 테스트 상태: `SPECIFIED_NOT_IMPLEMENTED`. D3A-19·49·50의 핵심 원칙만 2026-10-17 사용자 승인 (`APPROVED_PRINCIPLE`) |
| 구현 상태 | **명세만 존재, 미구현.** 이 문서의 어떤 테스트도 작성하지 않았다. `tests/`는 바꾸지 않았다 |
| 관련 문서 | [../architecture/P0-03A_DOMAIN_CONTRACTS.md](../architecture/P0-03A_DOMAIN_CONTRACTS.md) (불변조건 `INV-xx`), [../architecture/P0-03A_TYPE_CATALOG.md](../architecture/P0-03A_TYPE_CATALOG.md) (`TC-xx`), [../architecture/P0-03A_DECISION_REGISTER.md](../architecture/P0-03A_DECISION_REGISTER.md) (`D3A-xx`) |

## 0. 공통 규칙

- **이 문서는 인수 테스트 명세일 뿐이다.** 테스트 코드는 계약 구현이 별도로 승인된 뒤에 작성한다 (CLAUDE.md §5).
- 예외 이름(`INVALID_VALUE`, `PIT_VIOLATION` 등)은 [중심 문서 §12.2](../architecture/P0-03A_DOMAIN_CONTRACTS.md)의 **오류 분류 후보**다. Python 예외 클래스는 구현하지 않았고 형태는 D3A-34에서 정한다. V1 관례에 따라 모두 `ValueError` 계열일 수 있다.
- 결과가 미결정 사항에 달려 있는 테스트는 "**기대 결과 보류 (D3A-xx)**"로 표시했다. 그 경우에도 "조용히 정하지 않는다"는 부분은 지금 기준으로 검증할 수 있다.
- 기대 결과가 ACCEPTED ADR의 인수 테스트 명세나 승인 원칙 목록 밖 본문에만 근거하면 "(ADR 본문 근거, D3A-48)"로 표시했다. 그런 기대 결과는 해당 규칙이 확인되어야 확정된다.
- (R2) 기대 결과가 2026-10-17 사용자가 승인한 P0-03A 핵심 원칙(D3A-19, D3A-49, D3A-50)에 근거하면 "(승인 원칙 D3A-xx)"로 표시했다. 원칙 승인은 구현 승인이 아니며, 그 원칙의 세부(하위 질문 D3A-xx.n)에 달린 기대 결과는 계속 보류다. ACCEPTED ADR과 충돌해 적용이 보류된 원칙(D3A-49 원칙 (2))에 기대는 결과는 "(승인 원칙, ADR 개정 대기)"로 표시했다 (결정 등록부 §9 CA-49).
- 각 테스트의 "새 테스트 후보" 이름은 제안이다.

### 0.1 가상 데이터와 실제 데이터의 구분

**아래의 시장, 거래소, 상품, 식별자, 가격, 승수, tick, lot, 수수료, 환율은 모두 계산을 보여 주기 위한 가상 값이다.** 실제 거래소의 거래 시간, 휴장일, 공표 지연, 계약 사양을 주장하지 않는다 (UNVERIFIED). 식별자 형식(예: `FUT.ALPHA.C1`)도 설명용이며 형식은 D3A-02에서 정한다.

| 가상 대상 | 정의 (가상) |
|---|---|
| 시장 `XKR` | 타임존 Asia/Seoul. 세션 09:00~15:30. 공식 종가 공표 예상 = 세션 종료 + 30분. ADR-0007 §10과 같은 가상 시장 |
| 시장 `XUS` | 타임존 America/New_York. 세션 09:30~16:00. 공식 종가 공표 예상 = 세션 종료 + 30분. ADR-0007 §10과 같은 가상 시장 |
| 시장 `XF` | 타임존 Asia/Seoul. 선물 세션 종료 15:45. 공식 정산가 공표 예상 = 세션 종료 + 2시간 |
| 선물 `FUT.ALPHA` | 거래통화 USD. 월물 `FUT.ALPHA.C1`(구월물), `FUT.ALPHA.C2`(신월물). 각 `M[c]` = 10 USD/pt/계약 |
| 선물 `FUT.BETA` | 거래통화 USD. 월물 `FUT.BETA.B1`. `M[c]` = 50 USD/pt/계약. 고정 tick 0.25 pt |
| ETF `ETF.US1` | 거래통화 USD. 거래소 `XUS`. lot size 1 |
| ETF `ETF.KR1` | 거래통화 KRW. 거래소 `XKR`. lot size 10 |
| ETF `ETF.KR2` | 거래통화 KRW. 거래소 `XKR` |
| 계좌 | 기준통화 BC = KRW. 환율 방향은 KRW per USD (ADR-0008 §5.1) |

### 0.2 실제로 계산해 확인한 값

- 시각 변환은 IANA tz 규칙으로 계산했다 (CONFIRMED: 저장소 밖 일회성 계산, 이 환경의 tzdata 2026.3). ADR-0007 AT-0007-3의 값(tzdata 2026.5)과 같다.
- 금액 계산은 독립 산술로 확인했다 (CONFIRMED: 일회성 계산).

---

## 1. 식별자와 상품

### AT-03A-01 선물 상품 ID와 월물 ID

| 항목 | 내용 |
|---|---|
| Given | `FuturesInstrument` `FUT.ALPHA` (κ = USD, 월물 체인 {`C1`, `C2`}). `FuturesContract` `FUT.ALPHA.C1`, `FUT.ALPHA.C2` (각 `M` = 10 USD/pt/계약, κ = USD). `C1` 5계약 보유. 주기 t의 평가가격 `V[C1,t]` = 101, `V[C2,t]` = 111. t에 `C1 → C2` 롤 |
| When | (a) `TradableUnitRef(FUTURES_CONTRACT, FUT.ALPHA.C1)`로 raw 가격 관측을 만든다. (b) 거래 단위 자리에 상품 ID `FUT.ALPHA`를 넣어 관측을 만든다. (c) `FUT.ALPHA`의 데이터로 `FUT.BETA.B1`(다른 상품 체인의 월물)을 넣는다. (d) κ = KRW인 월물을 USD 상품 `FUT.ALPHA`에 연결한다. (e) 롤일 포지션을 상품 ID 하나로 키를 잡는다 |
| 입력값 | 위 Given의 값 |
| Then (기대 결과) | (a) 통과. (b) `IDENTITY_MISMATCH`. (c) `IDENTITY_MISMATCH` (경계에서 체인 검사). (d) `CURRENCY_MISMATCH`. (e) 상품 ID 키는 허용되지 않는다. 월물별 키를 쓰면 `C1` −5, `C2` +5가 각각 기록된다 (기록 계약은 P0-03B). 상품 ID 키를 썼다면 롤 체결이 상쇄되어 기록되지 않고, 평가가격이 101에서 111로 바뀌어 5 × (111 − 101) × 10 = **+500**의 가짜 이익이 생긴다 (테스트에서 실패해야 함) |
| 전제조건 | 월물 체인이 참조 데이터로 주어진다 (I6-3) |
| 예외조건 | 문자열 값이 같아도 `InstrumentId`와 `ContractId`는 같은 것으로 보지 않는다. 활성 월물을 추측해서 채우지 않는다 |
| 관련 ADR | ADR-0006 승인 원칙 4, I6-3, AT-0006-2. ADR-0001 §6.2 (월물은 상품 하나, 통화 하나), AT-0001-3 |
| 관련 불변조건·결정 | INV-01, INV-02, INV-20. D3A-02, D3A-03 |
| V1 영향도 | 없음. V1은 월물 이름 문자열을 쓰고, V1 변환기는 그 이름을 `ContractId`로 쓴다 (ADR-0006 §6.7) |
| 새 테스트 후보 | `test_instrument_and_contract_ids_are_distinct_types`, `test_futures_observation_requires_contract_unit`, `test_contract_outside_chain_rejected`, `test_contract_currency_must_match_instrument` |

### AT-03A-02 ETF 상품과 거래 단위

| 항목 | 내용 |
|---|---|
| Given | `EtfInstrument` `ETF.US1` (κ = USD, 단위 `SHARE`, lot 1). 거래 단위 `TradableUnitRef(ETF_LISTING, ETF.US1)` |
| When | (a) ETF 거래 단위로 raw 가격 관측을 만든다. (b) `ETF.US1`을 가리키는 `FuturesRollEvent`를 넣는다. (c) `ETF.US1`에 가산 back-adjustment를 요청한다. (d) `EtfInstrument`에 만기일이나 승수를 지정한다. (e) `ETF.US1`에 2:1 분할 `CorporateAction`을 넣는다. (f) 선물 `FUT.ALPHA`에 분배금 `CorporateAction`을 넣는다 |
| 입력값 | 분할 비율 신주 2 / 구주 1. 분배금 주당 0.50 USD |
| Then (기대 결과) | (a) 통과. (b) `ASSET_TYPE_MISMATCH`. (c) `ASSET_TYPE_MISMATCH`. (d) 거부 (필드가 없으므로 표현할 수 없음, `INVALID_VALUE`). (e) 통과 (이벤트 계약만. 수량·기준가격 변환은 P0-03B). (f) `ASSET_TYPE_MISMATCH` |
| 전제조건 | 상품에 자산 유형 판별자가 있다 |
| 예외조건 | 롤 이벤트가 없는 ETF, 기업 행사가 없는 선물은 정상 입력이다 |
| 관련 ADR | ADR-0006 I6-1, I6-2, I6-4, I6-6, AT-0006-1 |
| 관련 불변조건·결정 | INV-03, INV-29 |
| V1 영향도 | 없음 (V1은 ETF를 표현하지 않음) |
| 새 테스트 후보 | `test_etf_tradable_unit_is_listing`, `test_etf_rejects_roll_event`, `test_etf_rejects_additive_back_adjustment`, `test_etf_has_no_expiry_or_multiplier`, `test_futures_rejects_corporate_action` |

---

## 2. 가격과 관측

### AT-03A-03 Raw 종가와 Adjusted 종가

| 항목 | 내용 |
|---|---|
| Given | ADR-0004 AT-0004-2의 값. 선물 `C1` 5계약, `M` = 10. t−1의 raw `C1` 종가 = 100. 롤일 t의 gap = 111 − 101 = 10이므로 `as_of` = t인 PIT 가산 조정 시계열에서 t−1 값은 110. ETF raw 50.00, 분배금 조정 값 49.50 |
| When | (a) raw 100으로 명목가치를 계산한다. (b) 조정 시계열의 110으로 명목가치를 계산한다. (c) ETF 조정 값 49.50을 체결가 검증에 넘긴다. (d) `as_of` = t1 snapshot과 `as_of` = t2 snapshot의 조정 값끼리 차분한다. (e) 시계열 끝에서 조정 값과 raw가 같다는 이유로 마지막 조정 값을 raw 관측으로 바꾼다 |
| 입력값 | 위 Given의 값 |
| Then (기대 결과) | (a) 5 × 100 × 10 = **5,000**. (b) `PRICE_KIND_MISMATCH`. 잘못 계산하면 5 × 110 × 10 = 5,500 (**10% 과대**). (c) `PRICE_KIND_MISMATCH`. (d) `PRICE_KIND_MISMATCH`. (e) 거부 (조정 → raw 변환 함수가 없음) |
| 전제조건 | 조정 시계열은 `AdjustedPriceSeries` 타입이고 거래 단위가 없다 (TC-C6) |
| 예외조건 | 같은 snapshot 안의 조정 값 차분은 정상이다 (신호 계산) |
| 관련 ADR | ADR-0001 §5.1.4, §6.2 전제조건. ADR-0004 §6.4, AT-0004-2. ADR-0006 I6-7 |
| 관련 불변조건·결정 | INV-04, INV-28 |
| V1 영향도 | 없음. V1 경로의 adjusted 차분 계산은 그대로다. V1 조정 값은 변환기에서 "차분 전용"으로 표시되고, 구성(full-history / as-of snapshot)은 명시받거나 "구성 미상"으로 표시된다 (D3A-35) |
| 새 테스트 후보 | `test_notional_rejects_adjusted_series`, `test_fill_rejects_adjusted_price`, `test_adjusted_snapshots_not_differenced_across_as_of`, `test_no_adjusted_to_raw_conversion` |

### AT-03A-04 데이터 이용 가능 시각이 의사결정보다 늦음

| 항목 | 내용 |
|---|---|
| Given | `XUS` 2026-03-05 세션의 공식 종가: `observed_at` = 2026-03-05 21:00Z (16:00 America/New_York, EST), `data_available_at` = 21:30Z (Asia/Seoul 03-06 06:30). 계좌 `decision_at` = 2026-03-06 05:45 Asia/Seoul = **2026-03-05 20:45Z** |
| When | (a) `decision_at`의 PIT 뷰를 만든다. (b) 이 종가를 사이징 입력으로 쓴다. (c) FX 관측의 `data_available_at`이 `decision_at`과 같은 경우와 1초 늦은 경우. (d) 시장 관측 기록에 `decision_at` 필드를 넣는다 |
| 입력값 | 위 시각 |
| Then (기대 결과) | (a) 이 종가는 제외된다 (21:30Z > 20:45Z). 직전 세션(03-04) 종가가 최신 입력이다. (b) `PIT_VIOLATION`. (c) 같으면 허용, 1초 늦으면 `PIT_VIOLATION` (신호가 아닌 사이징 입력에도 적용). (d) 표현할 수 없음 (관측 계약에 `decision_at` 필드 없음) |
| 전제조건 | 관측에 `observed_at`, `data_available_at`이 있다 |
| 예외조건 | LIVE에서 시각이 없는 관측은 `TIMESTAMP_MISSING`으로 적격성 판단 불가 (ADR-0002 §6.4) |
| 관련 ADR | ADR-0001 I-1, AT-0001-5 B-1, B-2. ADR-0004 §6.5. ADR-0007 AT-0007-3 |
| 관련 불변조건·결정 | INV-06, INV-21. D3A-16 |
| V1 영향도 | 없음 (V1에는 시각이 없음) |
| 새 테스트 후보 | `test_pit_view_excludes_late_observation`, `test_late_sizing_input_is_pit_violation`, `test_available_exactly_at_decision_is_allowed`, `test_observation_has_no_decision_time` |

### AT-03A-05 공표 예상 시간은 지났지만 실제 관측은 미도착

| 항목 | 내용 |
|---|---|
| Given | `XKR`의 세션 D(가상 라벨 2026-11-05) 09:00~15:30 Asia/Seoul. 공표 예상 16:00 (= 07:00Z). `ETF.KR2`의 D일 공식 종가는 판정 시각 τ = 16:30 (= 07:30Z)까지 도착하지 않았다. D−1 공식 종가 10,000 KRW는 D−1 16:05에 도착해 이용 가능. 계좌의 정기 판정 시각은 매일 16:30이다 (가상. D−1 16:30에도 판정함). (d3)의 변형에서는 정기 판정 시각이 매일 08:00이다 |
| When | (a) τ = 16:30에서 데이터 상태를 판정한다. (b) 종가가 16:45 (07:45Z)에 도착한 뒤, τ = 16:30의 의사결정 입력을 다시 구성한다. (c) 16:50 (07:50Z)에 같은 세션을 다시 판정한다 (정기 일정 밖의 재판정). (d) **반복 판정 반례 (R1)**: R0의 D3A-19 대안 A("직전 판정 이후 τ까지 끝난 세션"만 판정 대상)로 16:50을 판정한다. (d1) 정기 16:30 일정. (d2) 종가가 16:50에도 도착하지 않은 경우. (d3) 정기 08:00 일정에서 16:30 판정을 한 경우와 하지 않은 경우. (e) 16:50 판정 뒤 16:30 판정 기록을 다시 조회한다. (f) (R2) 같은 입력으로 16:50 판정을 반복한다 (16:30 판정이 있는 경우와 없는 경우) |
| 입력값 | 위 시각 |
| Then (기대 결과) | (a) `MISSING_DATA`. `FRESH`나 `MARKET_CLOSED`가 아니다. 기준 세션은 D. D−1 가격을 D의 공식 가격처럼 쓰지 않는다. (b) 16:30의 의사결정은 여전히 이 종가를 쓸 수 없다. (c) `FRESH`, 기준 세션 D. (d) 이 규칙은 기대 결과를 내지 못하므로 **테스트에서 실패해야 한다**: (d1) (16:30, 16:50]에 끝난 세션이 0개라서 `MARKET_CLOSED`가 된다 ((c)의 기대값과 충돌). (d2) 기대 결과는 `MISSING_DATA`인데 `MARKET_CLOSED`가 된다 (결측을 휴장으로 처리. X7-6과 승인 원칙 D3A-19 원칙 (4) 위반). (d3) 같은 입력, 같은 τ = 16:50인데 16:30 판정이 있으면 `MARKET_CLOSED`, 없으면 `FRESH`다 (호출 이력 의존. R1 성질 P1 위반. R0 규칙은 판정 창을 명시적 평가 주기가 아니라 직전 호출 시각으로 정하므로 승인 원칙 D3A-19 원칙 (1)과도 맞지 않는다. 원칙 (2)는 기준 세션 집합이 같을 때의 결정성을 요구하므로 (f)에서 따로 검증한다). (CONFIRMED: 저장소 밖 일회성 시뮬레이션.) (a)와 (d2)의 `MISSING_DATA`는 ADR-0007 §6.4 문구상 그 상태의 조건만 성립하므로 어떤 판정 규칙도 만족해야 한다 ([ACCEPTED] 원칙 6, X7-6). 같은 기준 세션 집합에서의 호출 이력 독립성은 승인 원칙 D3A-19 원칙 (2)다 ((f)). (c)의 `FRESH`는 §6.4 `FRESH` 조건(세션 D의 공표 예상 16:00 ≤ τ, 실제 이용 가능 16:45 ≤ τ)을 만족하고 승인 원칙 D3A-19 원칙 (3)(늦은 도착 시 같은 세션 재판정)과 맞는 기대값이다. 이 결과를 내는 기계적 판정 규칙(비정기 재판정이 속하는 주기 등)은 승인되지 않았다 (D3A-19.3, DETAILS_OPEN). (e) 16:30 기록은 `MISSING_DATA` 그대로다. 늦은 도착은 새 판정 기록으로만 반영한다 (승인 원칙 D3A-19 원칙 (7). 기록 형식과 오류 정정 절차는 D3A-19.8). (f) **결정성 (R2)**: 같은 데이터, 같은 τ = 16:50, 같은 평가 주기, 같은 기준 세션 집합 {D}로 판정하면, 16:30 판정을 했는지와 관계없이 몇 번을 판정해도 결과가 같다 (승인 원칙 D3A-19 원칙 (2)). 결과 값은 (c)와 같다 |
| 전제조건 | 달력과 공표 예상 규칙이 주어진다 |
| 예외조건 | 달력이 없으면 AT-03A-23. (c)의 기계적 판정 규칙(판정 대상 세션, 비정기 재판정이 속하는 주기)은 D3A-19.1~19.3에서 정한다 (DETAILS_OPEN). ADR-0007 §6.4 문구만으로는 16:50에 `FRESH`와 `MARKET_CLOSED`의 조건이 함께 성립한다 (AT-0007-1의 K1과 같은 형태). R2에서 승인된 방향은 대안 3-(i)이다. 비정기 재판정을 "다음 주기 미리보기"로 읽는 해석(대안 3-(ii))은 이 기대값과 승인 원칙 (3)에 맞지 않는다 |
| 관련 ADR | ADR-0007 §6.4, 승인 원칙 5·9, X7-6, AT-0007-1, AT-0007-5 |
| 관련 불변조건·결정 | INV-07, INV-08, INV-24. D3A-19 (승인 원칙 (1)~(7), 세부 D3A-19.1~19.8) |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_expected_publication_does_not_imply_arrival`, `test_late_arrival_not_usable_for_earlier_decision`, `test_reassessment_of_same_session_reflects_late_arrival`, `test_reassessment_never_turns_missing_into_market_closed`, `test_status_is_independent_of_assessment_call_history`, `test_earlier_assessment_record_is_not_rewritten` |

### AT-03A-11 공급자 과거 가격 수정

| 항목 | 내용 |
|---|---|
| Given | `XUS` 2026-03-05 세션의 `ETF.US1` 종가. 원본: 101.00, `observed_at` 21:00Z, `data_available_at` 2026-03-05 21:30Z. 수정본: 101.50, `observed_at` 21:00Z (같음), `data_available_at` 2026-03-09 14:00Z (10:00 America/New_York) |
| When | (a) `decision_at` = 2026-03-06 00:00Z와 2026-03-10 00:00Z의 PIT 뷰. (b) 고른 레코드가 서로 다른 두 vintage(한쪽에는 원본만, 다른 쪽에는 수정본이 포함)에 묶인 두 실행. (c) 수정본이 원본을 덮어쓴다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) 첫 의사결정에 이용 가능한 관측은 원본(**101.00**)뿐이다. 두 번째에는 원본과 수정본이 모두 이용 가능하다 (CONFIRMED: 시각 비교). 두 번째의 사용 값은 **기대 결과 보류 (D3A-14)**: "이용 가능한 관측 가운데 가장 늦은 `data_available_at`" 규칙([제안], 중심 문서 §6.5)을 채택하면 **101.50**. (b) 고른 레코드가 다르므로 `content_hash`가 다르다 (ADR-0011 FP-13). vintage를 지식 기준 시각으로 정의할지는 D3A-14. (c) 거부. 원본과 수정본을 모두 보관한다 |
| 전제조건 | 수정본은 별도 관측이다 |
| 예외조건 | `content_hash`가 같아도 각 의사결정은 `data_available_at`으로 다시 거른다 (INV-31). 수정본의 `observed_at`이 원본과 다르면 연결 오류 (D3A-14 제안) |
| 관련 ADR | ADR-0001 §5.1.1, ADR-0004 §6.5, ADR-0011 승인 원칙 6~8, FP-13, AT-0011-9 |
| 관련 불변조건·결정 | INV-14, INV-31. D3A-14, D3A-15 |
| V1 영향도 | 없음 (V1에는 수정 이력이 없음) |
| 새 테스트 후보 | `test_revision_is_separate_observation`, `test_pit_view_selects_latest_available_revision`, `test_content_hash_differs_when_selected_revision_differs` |

### AT-03A-14 결측 가격을 0으로 치환

| 항목 | 내용 |
|---|---|
| Given | `XKR` 세션 D 있음. `ETF.KR2` 50주 보유, D−1 공식 종가 20,000 KRW. 공표 예상 이후 평가 시각에 D일 종가 없음 |
| When | (a) 평가한다. (b) 가격을 0으로 둔다. (c) D+1 종가로 D를 보간한다. (d) 표시 없이 20,000을 복사한다. (e) 공급자 값이 NaN이다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) 상태 `MISSING_DATA`. 포지션은 그대로 남는다. 평가 처리: Q7-3 정책이 승인·구현되기 전에는 fail-fast (`ValueError`) (ADR-0002 §6.2, ADR-0007 §6.8). 정책 승인 후의 처리(표시된 마지막 가격 사용, LIVE 위험 증가 차단 등)는 **기대 결과 보류 (Q7-3, D3A-33)**. (b) 거부. 0을 쓰면 50 × (0 − 20,000) = **−1,000,000 KRW** 가짜 손실과 다음 날 같은 크기의 가짜 이익. (c) 거부 (look-ahead). (d) 거부. 정책이 허용한 경우에만 사유 `MISSING_DATA` 표시와 함께 사용. (e) `INVALID_VALUE`. 결측으로 조용히 바꾸지 않는다 |
| 전제조건 | 달력상 세션이 있었다 |
| 예외조건 | V1 경로는 지금처럼 `ValueError` (fail-fast, 변경 없음) |
| 관련 ADR | ADR-0007 X7-1~X7-3, X7-6, AT-0007-5. ADR-0001 §6.2 예외조건 |
| 관련 불변조건·결정 | INV-09, INV-13. D3A-33 |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_missing_price_never_zero`, `test_missing_price_never_interpolated`, `test_last_price_use_requires_marked_policy`, `test_nan_price_rejected_not_treated_as_missing` |

### AT-03A-15 관측값에 체결 가정을 혼합

| 항목 | 내용 |
|---|---|
| Given | V1 형태의 일별 입력: quote bid 101.9 / ask 102.1, 수수료 1 USD/계약, 슬리피지 1 tick (tick 0.1), 일간 위험 예산 625,000 BC/d, 증거금 값 |
| When | (a) 수수료·슬리피지 필드를 가진 `MarketObservationSet`을 만든다. (b) 체결 모델이 슬리피지를 적용한 결과(102.2)를 quote 관측으로 되돌려 저장하는 경로가 있는지 확인한다. (c) V1 변환기가 `ExecutionMarketDay`를 나눈다. (d) 체결 모델이 매수 체결가를 계산한다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) 표현할 수 없음 (관측 묶음에 해당 필드 없음). (b) 그런 경로가 없다. 체결 모델의 출력은 체결가(P0-03B 체결 기록)이고 입력 quote 객체는 바뀌지 않는다 (불변 객체). 손으로 지어낸 102.2를 `MarketQuote`로 만드는 것은 타입으로 검출할 수 없으므로, 관측의 출처는 Data Boundary에서 확인한다 (남은 위험, D3A-31). (c) quote → 묶음 (1), 수수료·슬리피지 → 묶음 (2), 위험 예산·증거금 → 묶음 (3). 위험 예산 수준과 데이터 지연 가정을 명시하지 않으면 거부. (d) 체결가 102.1 + 0.1 = **102.2**. quote 관측은 101.9 / 102.1 그대로 |
| 전제조건 | 세 입력 계약이 분리되어 있다 (TC-F1, TC-F2, TC-F4) |
| 예외조건 | — |
| 관련 ADR | ADR-0004 승인 원칙 2, §6.3, AT-0004-4 |
| 관련 불변조건·결정 | INV-15. D3A-31 |
| V1 영향도 | 없음. V1 `ExecutionMarketDay`는 그대로이며 변환기만 나눈다 |
| 새 테스트 후보 | `test_observation_set_has_no_assumption_fields`, `test_execution_model_does_not_write_back_quotes`, `test_quote_stays_raw_after_slippage`, `test_v1_execution_day_split_into_three_bundles` |

### AT-03A-25 Raw 정산가를 체결가로 확정하려는 시도 (R1 추가)

| 항목 | 내용 |
|---|---|
| Given | 선물 월물 `FUT.ALPHA.C1` (`M` = 10 USD/pt/계약, κ = USD). 시장 `XF` 세션 D의 공식 정산가 관측 `RawPriceObservation(kind = SETTLEMENT, price = 100.0)`, `observed_at` = 세션 종료 15:45, `data_available_at` = 세션 종료 + 2시간 = 17:45 (가상). 체결 구간의 `MarketQuote`는 없다 (확인되지 않음). 체결 기록 없음. 승인된 체결 가정(`ExecutionAssumptionSet`의 `fill_rule`, TC-F2)이 주입되지 않았다. 정산가 공표 뒤 `decision_at` = D 18:00 Asia/Seoul (가상. `XF` 세션 종료 15:45, 정산가 공표 예상 17:45)에 `FUT.ALPHA.C1` 2계약 매수 주문 의도가 생겼다. 그 시각에는 체결 구간이 없으므로 체결은 다음 `XF` 체결 구간에서만 가능하다 |
| When | (a) 정산가가 raw라는 이유로 매수 체결가를 100.0으로 확정한다 (시뮬레이션 체결 기록을 만든다). (b) 정산가 관측으로 bid = ask = 100.0인 `MarketQuote`를 만든다. (c) 정산가로 `FUT.ALPHA.C1` 기존 보유분을 평가한다: (c1) 승인된 평가 정책이 `SETTLEMENT`를 평가가격 종류로 명시적으로 선택했고 `valuation_at` = D 18:00 (≥ `data_available_at` 17:45). (c2) 평가 정책이 주입되지 않았거나 승인되지 않았다. (c3) Given 그대로, `valuation_at` = D 17:00 (공표 예상과 실제 도착 17:45 전). (c4) **변형**: Given과 달리 세션 D 정산가가 18:30까지 도착하지 않았고 `valuation_at` = D 18:30이다. (c5) 다른 월물(`FUT.ALPHA.C2`)의 정산가나 조정 가격으로 `C1`을 평가한다. (d) 테스트가 "정산가로 체결한다"는 체결 가정을 명시적으로 주입한다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) 거부 (승인 원칙 D3A-50 원칙 (2)·(5), INV-33. 오류 분류 후보 `MISSING_REQUIRED`: 체결가를 정할 체결 가정이나 체결 기록이 없음). 정산가가 raw라는 사실(호가 단위에 맞더라도)은 체결 가능성의 근거가 아니다. **이 Given에는 quote도 실제 체결가도 없으므로, 정산가 100.0만으로는 실제 체결 비용이나 과소 계상 금액을 확정할 수 없다.** 크기를 보여 주기 위한 비교용 가상 시나리오 (이 테스트의 Given이 아님): 다음 `XF` 체결 구간에서 2계약이 실제로 101.5에 체결되었고, 이 체결가는 그 시각의 ask와 같다고 가정한다 (스프레드는 이 체결가에 들어 있고, ask 대비 추가 슬리피지는 없음). 수수료는 ADR-0001 §6.2의 별도 항 `fee[k]`로 두 경우에 같은 금액이 한 번만 차감되므로 비교에서 빠진다 (이중 차감 금지, ADR-0008 원칙 9·14). 이때 체결분 항 `Δq × (V − F) × M`에서 F를 101.5 대신 100.0으로 기록하면, 평가가격 V와 관계없이 체결분 손익이 2 × (101.5 − 100.0) × 10 = **30 USD** 과대 계상된다. 회계상으로는 체결 비용을 30 USD 과소 계상한 것과 같다 (CONFIRMED: 일회성 계산). 이 1.5 pt 차이에는 스프레드뿐 아니라 정산 이후 다음 체결 구간까지의 가격 변동도 들어 있으므로, 30 USD를 순수 거래비용으로 읽지 않는다. 다른 체결가를 가정하면 금액과 방향이 달라진다. (b) 계약상 허용하지 않는다 (승인 원칙 D3A-50 원칙 (6), INV-33). 도메인 계약에는 raw 관측(정산가)을 실행 가능한 `MarketQuote`로 바꾸는 변환 경로를 두지 않는다. 정산가는 거래소가 정한 기준 가격(`RawPriceObservation`, `PriceKind` = `SETTLEMENT`)이고, bid/ask는 관측 시각의 호가(`MarketQuote`)다. 정산가를 bid와 ask에 복사하면 존재하지 않는 호가 관측을 만드는 무단 변환이 된다. 다만 `MarketQuote` 생성자가 숫자 bid/ask를 받는 한, 누군가 100.0을 직접 넣어 객체를 만드는 것을 Python 자료형이 구조적으로 막는다고 단정하지 않는다 (구현이 없음, UNVERIFIED). 실제로 막는지는 향후 구현과 인수 테스트로 확인해야 한다. 그때까지의 방어 수단은 Data Boundary가 quote 관측을 공급자의 호가 출처에서만 만들고 출처를 기록하는 것이다 (남은 위험, D3A-31. AT-03A-15 (b)와 같음). 그런 quote로 계산한 값은 시뮬레이션 체결가일 뿐 실제 체결 기록이 아니다 (승인 원칙 D3A-50 원칙 (4)·(7)). (c) 무조건 허용이 아니다. 정산가 평가의 **필요조건**은 다음 넷이다. (1) 보유 월물 `FUT.ALPHA.C1` 자신의 raw 정산가다 ([ACCEPTED] ADR-0001 §6.2의 `V[c,t]`는 그 월물의 raw 가격, ADR-0004 §6.4). (2) 평가 정책이 `SETTLEMENT`를 평가가격 종류로 명시적으로 선택했다. 평가가격 종류는 [OPEN] ADR-0001 Q1-2이고 (ADR-0007 §5.1), 평가 정책은 명시적으로 선택하며 기본값을 두지 않는다 ([ACCEPTED] ADR-0007 §6.5). (3) `data_available_at ≤ valuation_at`이다 ([ACCEPTED] ADR-0007 §6.4, 원칙 9). (4) 그 정산가가 `valuation_at`까지 이용 가능해야 했던 세션(여기서는 세션 D)의 것, 즉 상태가 `FRESH`다 (ADR-0007 §6.4. 판정 규칙은 D3A-19의 세부, DETAILS_OPEN). 다른 상태에서 이전 세션의 정산가로 평가하는 것(잠정 평가, 이전 가격 사용)은 Q7-3·Q7-4 정책이 명시적으로 허용할 때만이다 ([ACCEPTED] ADR-0007 원칙 8). 결과: (c1) 네 조건을 만족하므로 100.0을 평가가격으로 쓸 수 있다. 다만 평가가격 종류(Q1-2)가 결정되고 그 정책이 승인되기 전에는 이것은 **정책 승인 후의 기대 결과**다. (c2) 평가를 확정하지 않고 오류를 낸다 ([ACCEPTED] ADR-0007 §6.5의 기본값 없음. ADR-0007 AT-0007-1·AT-0007-4 예외조건과 같음). 정책이 승인·구현되기 전에는 fail-fast가 유지된다 (ADR-0007 §6.8 정합성 표. AT-03A-14와 같은 근거). 정책 기본값을 만들지 않는다. (c3) 세션 D의 정산가를 쓸 수 없다 (조건 (3)·(4) 불만족). 상태는 `PENDING_OFFICIAL`이다 (AT-0007-4와 같은 형태). D−1 정산가로 잠정 평가할지 평가를 미룰지는 [OPEN] Q7-4이고, 정책이 정해지기 전에는 오류를 낸다 (AT-0007-4 예외조건). 같은 17:00 시점이라도 정산가가 공표 예상 전에 실제로 먼저 도착했다면, 그 상태는 AT-03A-22 (ii)처럼 보류다 (D3A-19). (c4) 세션 D의 정산가를 쓸 수 없다. 상태는 `MISSING_DATA`이며 처리는 [OPEN] Q7-3이다. 그 전까지는 fail-fast다 (AT-03A-14). (c5) 거부 (`IDENTITY_MISMATCH` / `PRICE_KIND_MISMATCH`, AT-03A-01·AT-03A-03). (c1)과 (c3)의 상태 이름을 내는 판정 규칙은 D3A-19의 세부(D3A-19.1~19.4, DETAILS_OPEN)에서 정한다. 정산가가 평가용일 수 있다는 것은 승인 원칙 D3A-50 원칙 (3)이지만, 평가가격 종류와 기본 정책은 승인되지 않았다 (Q1-2, D3A-50.5). 어느 경우에도 평가가격은 체결가가 아니다 ((a), INV-33). (d) **기대 결과 보류 (ADR-0001 Q1-1, D3A-09, D3A-50.2)**. 지금 검증할 수 있는 것: 어떤 체결 가정도 [ACCEPTED] ADR-0001 I-2(`decision_at ≤ order_submitted_at ≤ fill_at`)와 ADR-0007 원칙 10(체결은 체결 가능 구간에서만)을 지켜야 한다. 이 주문의 `fill_at`은 다음 체결 구간에 있으므로, 세션 D의 정산가 100.0(`observed_at` 15:45, `decision_at` 18:00보다 앞섬)을 그 체결의 체결가로 쓰는 것은 체결 시점보다 오래된 가격을 쓰는 것이다. 그런 가정을 허용할지, 허용한다면 어떻게 표시할지는 체결 모델 결정(Q1-1) 전에는 정하지 않는다. 어느 경우에도 정산가 관측 자체가 체결 기록으로 바뀌지 않는다 |
| 전제조건 | raw 관측에 가격 종류가 표시되어 있다 (TC-C1). 체결 가정은 체결 가정 묶음(TC-F2)으로만 들어온다 |
| 예외조건 | V1 경로는 호출자가 넘긴 quote로 체결가를 계산하며 바뀌지 않는다 (`execution.py`). ADR-0001 대안 A(V1)의 전제 `mid[c,fill_at] = V[c,t]`는 V1의 체결 가정이다. 새 경로에서 같은 가정을 쓰려면 명시적으로 선택해야 한다 (Q1-1) |
| 관련 ADR | ADR-0001 §5.1.4, §5.2, §6.2, I-2, Q1-1, Q1-2. ADR-0002 §6.2. ADR-0004 원칙 2, §6.4. ADR-0007 원칙 8·9·10, §5.1, §6.4, §6.5, §6.8, Q7-3, Q7-4, AT-0007-1, AT-0007-4. ADR-0008 원칙 9·14. ADR-0009 원칙 18 |
| 관련 불변조건·결정 | INV-15, INV-33. D3A-09, D3A-31, D3A-50 |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_settlement_observation_is_not_fill_price_without_assumption`, `test_no_conversion_from_raw_observation_to_quote`, `test_valuation_price_and_fill_price_are_distinct_roles`, `test_settlement_valuation_requires_selected_policy_and_availability` |

---

## 3. 시각과 달력

### AT-03A-06 한국 거래일·미국 휴장일

| 항목 | 내용 |
|---|---|
| Given | **가상 달력 정의**: `XKR`은 라벨 2026-11-26에 세션이 있고, `XUS`는 라벨 2026-11-26에 세션이 없다 (가상 휴장. 실제 거래소 휴장 여부를 주장하지 않음). 보유: `ETF.KR2` 100주 (D−1 10,000 → D 10,100 KRW, D 종가의 실제 `data_available_at` = 2026-11-26 07:05Z, 가상), `ETF.US1` 10주 (마지막 공식 종가는 `XUS` 2026-11-25 세션의 50.00 USD, `observed_at` 2026-11-25 21:00Z = 16:00 EST). `valuation_at` = 2026-11-27 08:00 Asia/Seoul = **2026-11-26 23:00Z**. 직전 평가 시각 = 2026-11-25 23:00Z |
| When | `valuation_at`에서 두 상품의 상태를 판정하고 평가한다 |
| 입력값 | 위 값. 평가 정책은 테스트가 명시적으로 주입한다 (Q7-3) |
| Then (기대 결과) | `ETF.KR2`: `FRESH` (`XKR` 11-26 세션 종료 06:30Z, 공표 예상 07:00Z, 실제 `data_available_at` 07:05Z ≤ 23:00Z). 보유분 손익 100 × (10,100 − 10,000) = **+10,000 KRW**. `ETF.US1`: `MARKET_CLOSED` (11-25 공식 가격 이후 `XUS` 세션 없음). 평가가격 50.00 USD는 "정책이 고른 평가가격, 현재 시장가치와 같다고 단정하지 않음"으로 표시. 경과 시간 = 23:00Z(11-26) − 21:00Z(11-25) = **26시간**. 선택한 평가가격을 유지한 경우의 평가상 가격 손익 **0 USD** (실제 가치 변화가 0이라는 뜻이 아님). `ETF.US1`은 이 날 체결 구간이 없다 |
| 전제조건 | 두 거래소의 달력과 공표 예상 규칙이 있다. `MARKET_CLOSED` 처리 정책이 승인·선택되어 있다 (Q7-3). 그 전에는 새 엔진도 평가 가격이 없으면 fail-fast다 (ADR-0002 §6.2, ADR-0007 §6.8). 기대 결과는 ADR-0007 AT-0007-1과 같고, 이 결과를 내는 판정 규칙(판정 대상 세션과 우선순위)은 D3A-19에서 정한다 |
| 예외조건 | 평가 정책이 주입되지 않으면 오류 (기본값 없음). `XUS`가 11-26 세션이 있었는데 가격이 없으면 `MISSING_DATA`이지 `MARKET_CLOSED`가 아니다. 거래일 라벨은 UTC 날짜에서 추론하지 않는다 |
| 관련 ADR | ADR-0007 AT-0007-1, §6.4, §6.5, X7-6, C7-3 |
| 관련 불변조건·결정 | INV-08, INV-22, INV-25. D3A-33 |
| V1 영향도 | 없음. V1은 이 입력을 날짜 불일치로 거부한다 (`portfolio_backtest.py:216-242`). 그 동작은 그대로다 |
| 새 테스트 후보 | `test_holiday_is_market_closed_not_missing`, `test_market_closed_mark_labeled_not_market_value`, `test_session_with_no_price_is_missing_data` |

### AT-03A-07 미국 DST 변경

| 항목 | 내용 |
|---|---|
| Given | 계좌 `decision_at`은 매 영업일 05:45 Asia/Seoul. `XUS` 종가 16:00 America/New_York, 공표 예상 +30분 |
| When | 네 세션의 종가를 같은 현지 의사결정 시각에 쓸 수 있는지 판정한다 |
| 입력값 | 아래 표 |
| Then (기대 결과) | 아래 표 (CONFIRMED: IANA tz 규칙, tzdata 2026.3) |
| 전제조건 | 타임존 데이터가 있다 (D3A-24) |
| 예외조건 | 타임존 데이터가 없으면 `MISSING_REQUIRED`. 존재하지 않거나 두 번 존재하는 현지 시각은 AT-03A-18 |
| 관련 ADR | ADR-0007 AT-0007-3, C7-1, C7-2, X7-5. ADR-0011 FP-14 |
| 관련 불변조건·결정 | INV-05, INV-22, INV-23. D3A-18, D3A-24 |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_availability_uses_instants_across_spring_dst`, `test_availability_uses_instants_across_autumn_dst`, `test_no_fixed_offset_conversion`, `test_tz_data_version_recorded` |

| `XUS` 세션 | 종가 UTC | 공표 예상 Asia/Seoul | 의사결정 시각 | 쓸 수 있는가 |
|---|---|---|---|---|
| 2026-03-05 (EST) | 21:00Z | 03-06 06:30 | 03-06 05:45 | **아니오** → 직전 세션 종가 사용 |
| 2026-03-10 (EDT) | 20:00Z | 03-11 05:30 | 03-11 05:45 | **예** |
| 2026-10-29 (EDT) | 20:00Z | 10-30 05:30 | 10-30 05:45 | **예** |
| 2026-11-02 (EST) | 21:00Z | 11-03 06:30 | 11-03 05:45 | **아니오** |

- 고정 시차 "미국 종가 = 한국 다음 날 06:00"을 쓰는 구현은 03-11과 10-30에 쓸 수 있는 종가를 버린다. 고정 시차 "05:00"을 쓰는 구현은 03-06과 11-03에 아직 공표되지 않은 종가를 쓴다 (look-ahead). 두 구현 모두 테스트에서 실패해야 한다.
- 이 실행의 manifest에는 타임존 데이터 출처와 버전을 기록해야 한다 (FP-14).

### AT-03A-17 naive 시각과 UTC가 아닌 aware 시각

| 항목 | 내용 |
|---|---|
| Given | (a) naive `2026-03-05 21:00`. (b) 고정 오프셋 aware `2026-03-06 06:00+09:00`. (c) UTC aware `2026-03-05 21:00Z` |
| When | `Instant`나 `ObservationMeta`를 만든다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) `NAIVE_OR_AMBIGUOUS_TIME`. (c) 통과. (b) **기대 결과 보류 (D3A-17)**: 도메인에서 거부하거나 경계에서 `2026-03-05 21:00Z`로 정규화한다. 어느 쪽이든 06:00을 UTC로 보거나(9시간 오류) 정보 없이 처리해서는 안 된다 |
| 전제조건 | — |
| 예외조건 | 고정 오프셋은 IANA 타임존 규칙을 대신하지 않는다 (C7-2) |
| 관련 ADR | ADR-0007 C7-1, ADR-0011 FP-10 |
| 관련 불변조건·결정 | INV-05. D3A-16, D3A-17 |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_naive_datetime_rejected`, `test_non_utc_aware_is_not_silently_treated_as_utc` |

### AT-03A-18 존재하지 않거나 두 번 존재하는 현지 시각

| 항목 | 내용 |
|---|---|
| Given | (a) `ZonedLocalTime(2026-03-08 02:30, America/New_York)`. 봄 DST 전환으로 존재하지 않는 시각. (b) `ZonedLocalTime(2026-11-01 01:30, America/New_York)`. 가을 전환으로 두 번 존재하는 시각 |
| When | 해석 규칙 없이 `Instant`로 바꾼다 |
| 입력값 | 위 값 |
| Then (기대 결과) | 둘 다 `NAIVE_OR_AMBIGUOUS_TIME`으로 거부한다. 라이브러리 기본값으로 조용히 바꾸지 않는다. 참고 사실 (CONFIRMED, tzdata 2026.3): Python `zoneinfo`는 (a)를 오류 없이 `fold=0`이면 07:30Z(왕복 시 03:30 EDT), `fold=1`이면 06:30Z(왕복 시 01:30 EST)로 바꾸고, (b)를 05:30Z 또는 06:30Z로 바꾼다. 따라서 왕복 변환 검사가 필요하다. 해석 규칙이 정해진 뒤의 기대 값은 **보류 (D3A-18, Q7-8)** |
| 전제조건 | 타임존 데이터가 있다 |
| 예외조건 | 명시적 오프셋이나 앞쪽·뒤쪽 선택이 주어지면 규칙에 따라 처리 (Q7-8 결정 후) |
| 관련 ADR | ADR-0007 Q7-8, AT-0007-3 예외조건 |
| 관련 불변조건·결정 | INV-17, INV-23. D3A-18 |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_nonexistent_local_time_rejected`, `test_ambiguous_local_time_rejected_without_rule` |

### AT-03A-22 공식 가격 공표 대기와 조기 도착

| 항목 | 내용 |
|---|---|
| Given | 가상 선물 `F1` (시장 `XF`). 세션 종료 15:45 Asia/Seoul, 정산가 공표 예상 17:45. 직전 공식 정산가 100.0 (이용 가능). 판정 시각 τ = 16:45. 장중 마지막 체결가 102.0 있음 |
| When | (i) 정산가가 τ까지 도착하지 않았다. (ii) 정산가 101.5가 16:30에 먼저 도착했다 (`data_available_at` 16:30 ≤ τ < 공표 예상 17:45) |
| 입력값 | 위 값 |
| Then (기대 결과) | (i) `PENDING_OFFICIAL` (ADR-0007 AT-0007-4와 같음). 판정 대상 세션은 오늘 세션. 같은 시각의 의사결정 입력은 직전 공식 정산가 100.0까지만 쓴다. 장중 102.0은 정책이 명시적으로 허용할 때만 쓰고 표시한다. (ii) **기대 결과 보류 (D3A-19.6)**: 실제 이용 가능을 우선하는 해석(원칙 9의 대칭 적용. D3A-19 비교표의 공통 매핑)은 `FRESH`, 공표 예상 시각을 우선하는 해석은 17:45까지 `PENDING_OFFICIAL`이다. R0에 적었던 "대안 A"는 반복 판정 반례로 권장안에서 철회했다 (R1, AT-03A-05 (d)). R2에서 승인된 D3A-19 원칙 (3)은 늦은 도착만 다루므로 조기 도착은 결정되지 않았다. 어느 경우에도 상태 기록에 판정 대상 세션이 있어야 하고, 101.5를 16:30 이전의 의사결정에 쓰면 안 된다 |
| 전제조건 | 공표 예상 규칙이 데이터 계약으로 주어진다 |
| 예외조건 | 평가 정책이 정해지지 않았으면 평가를 확정하지 않는다 (ADR-0007 AT-0007-4) |
| 관련 ADR | ADR-0007 §6.4, 승인 원칙 9, AT-0007-4 |
| 관련 불변조건·결정 | INV-07. D3A-19 |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_pending_official_matches_adr_0007_at_4`, `test_status_records_reference_sessions`, `test_early_arrival_status_per_decision` |

### AT-03A-23 달력이 없어 휴장과 결측을 구분할 수 없음

| 항목 | 내용 |
|---|---|
| Given | `ETF.KR1`의 거래소 달력이 로드되지 않았거나, 판정 시각이 달력 적용 기간 밖이다. 날짜 D의 관측이 없다 |
| When | 데이터 상태를 판정한다 |
| 입력값 | — |
| Then (기대 결과) | LIVE: `MISSING_DATA`, 사유 "달력 없음", 위험 증가 주문 차단 (ADR 본문 근거: ADR-0007 AT-0007-5 예외조건, D3A-48). `MARKET_CLOSED`로 추측하지 않는다 ([ACCEPTED] ADR-0007 원칙 6). 다섯 번째 상태를 만들지 않는다. LIVE가 아닌 프로필: **기대 결과 보류 (Q7-3)** |
| 전제조건 | — |
| 예외조건 | — |
| 관련 ADR | ADR-0007 AT-0007-5 예외조건, §6.4 |
| 관련 불변조건·결정 | INV-08, INV-24. D3A-33 |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_missing_calendar_is_missing_data_in_live`, `test_status_enum_has_exactly_four_values` |

### AT-03A-19 휴장 평가가격을 체결 가격으로 쓰기, 장 밖 접수 미확인

| 항목 | 내용 |
|---|---|
| Given | AT-03A-06의 `ETF.US1` (`MARKET_CLOSED`, 평가가격 50.00 USD). `TradingConstraintSet`의 `XUS` 주문 접수 구간 = 확인되지 않음 (UNVERIFIED) |
| When | (a) 평가가격 50.00을 시뮬레이션 체결가나 체결 가능 quote로 쓴다. (b) LIVE에서 개장 전 접수를 가정하고 `ETF.US1` 주문을 제출 대상으로 만든다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) 거부. 체결가는 실제 체결 기록이나, 체결 가능 구간의 quote 등에 명시적인 체결 가정을 적용한 값에서만 나온다 (그 가정이 승인된 것이어야 한다는 한정은 [제안]. 체결 구간 요건은 [ACCEPTED] ADR-0007 원칙 10과 ADR-0001 §5.1.1. 체결 기록의 출처와 가격 구분은 승인 원칙 D3A-50 원칙 (5)·(7), INV-33). 평가가격은 "정책이 고른 평가가격"이다. (b) [제안] 규칙에 따른 기대 결과 (D3A-22, INV-18의 일반화 부분): 제출을 가정하지 않고 주문 의도는 `INTENT`로 남는다 (ADR-0007 AT-0007-7과 같은 처리). Live 시작 시 필수 기능 검증은 [ACCEPTED] ADR-0012 BR-1 |
| 전제조건 | — |
| 예외조건 | 평가가격을 거래 전 위험의 `P_ref`로 쓸 수 있는지는 Q3-3 (이 테스트 범위 밖) |
| 관련 ADR | ADR-0007 승인 원칙 7, 10, AT-0007-1, AT-0007-7. ADR-0012 BR-1 |
| 관련 불변조건·결정 | INV-18, INV-25, INV-33. D3A-22 |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_market_closed_mark_is_not_execution_price`, `test_unverified_acceptance_window_not_assumed` |

---

## 4. 통화와 FX

### AT-03A-08 서로 다른 통화 금액 합산

| 항목 | 내용 |
|---|---|
| Given | `MoneyAmount(300, USD)`, `MoneyAmount(420,000, KRW)`. BC = KRW. `FxRate(numerator=KRW, denominator=USD, 1,400)` |
| When | (a) 두 금액을 그대로 더한다. (b) USD 금액을 환산한 뒤 더한다. (c) 300 USD와 420,000 KRW의 크기를 비교한다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) `CURRENCY_MISMATCH` (그대로 더한 420,300은 의미 없는 값). (b) 300 × 1,400 + 420,000 = **840,000 KRW**. (c) `CURRENCY_MISMATCH` |
| 전제조건 | — |
| 예외조건 | 같은 통화끼리는 정상 |
| 관련 ADR | ADR-0008 X8-8, ADR-0001 R2, AT-0001-9 W1, ADR-0006 AT-0006-3 W1 |
| 관련 불변조건·결정 | INV-11. D3A-12 |
| V1 영향도 | 없음. V1은 상품별로 환산한 뒤 더하므로 환산 전 합산 오류가 없다 (ADR-0001 R2) |
| 새 테스트 후보 | `test_money_add_rejects_different_currencies`, `test_money_compare_rejects_different_currencies`, `test_convert_then_sum` |

### AT-03A-09 FX 방향 반전

| 항목 | 내용 |
|---|---|
| Given | 공급자 값: USD per KRW = 1/1,400 = 0.000714285…. BC = KRW. 금액 1,000 USD |
| When | (a) Data Boundary가 공급자 값을 방향 그대로 `FxRate(numerator=USD, denominator=KRW)`로 저장하고 USD 금액을 환산한다. (b) 명시적으로 뒤집은 새 관측 `FxRate(numerator=KRW, denominator=USD, 1,400)`, `inverted_from_source = true`로 환산한다. (c) 0.000714…를 KRW per USD 자리에 넣는다. (d) 환율 값 0 또는 음수, 분자 = 분모 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) `CURRENCY_MISMATCH` (금액 통화 USD ≠ 분모 KRW). (b) **1,400,000 KRW**. (c) 방향 표시는 맞게(`numerator=KRW, denominator=USD`) 하고 숫자만 0.000714로 넣는 오류는 타입으로 막을 수 없다 (남은 위험). 수집 단계에서 공급자 표기의 방향을 정확히 지정해야 하며, 값 타당성 검사(범위 등)는 새 규칙이므로 미결정이다 (D3A-26). 이 오류가 나면 1,000 USD → 0.714 KRW (**1,960,000배 오류**, CONFIRMED: 일회성 계산). (d) `INVALID_VALUE` |
| 전제조건 | — |
| 예외조건 | 반전 결과의 수치 허용 오차는 D3A-11 결정 후 정한다 |
| 관련 ADR | ADR-0008 §5.1, §6.5, X8-4 |
| 관련 불변조건·결정 | INV-10. D3A-26, D3A-11 |
| V1 영향도 | 없음. V1 `fx_to_base`는 곱하는 값이므로 방향은 BC/κ와 같다 (`fx.py:23`) |
| 새 테스트 후보 | `test_fx_rate_carries_direction`, `test_reverse_quote_requires_explicit_inversion`, `test_fx_rate_must_be_positive`, `test_provider_quote_direction_declared_at_ingestion` |

### AT-03A-10 계약승수와 Tick Size

| 항목 | 내용 |
|---|---|
| Given | 선물 월물 `FUT.BETA.B1`: `M` = 50 USD/pt/계약, κ = USD, 고정 tick 0.25 pt. BC = KRW, `fx[USD]` = 1,400 KRW/USD. ETF `ETF.US1` (승수 필드 없음, 1 고정) |
| When | (a) 2계약, 가격 변화 +3 pt의 금액을 계산한다. (b) 가격 5,000.25와 5,000.10의 tick 정렬을 검사한다. (c) 승수가 확정되지 않은 월물로 금액을 계산한다. (d) `M` = 0 또는 −50, tick = 0, 가격 NaN. (e) ETF 100주 × +0.5 pt의 금액. (f) 거래소가 계약 사양을 바꿔 승수가 25가 되었는데 기존 월물 ID의 `M`을 고친다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) 2 × 3 × 50 = **300 USD** → × 1,400 = **420,000 KRW**. (b) 5,000.25 / 0.25 = 20,001 → 정렬됨. 5,000.10 / 0.25 = 20,000.4 → `INVALID_VALUE`. (c) 계산하지 않고 거부 (`MISSING_REQUIRED`). (d) 모두 `INVALID_VALUE`. (e) 100 × 0.5 × 1 = **50 USD**. 선물 승수 250,000을 쓰는 경로가 없어야 한다 (잘못 쓰면 12,500,000). (f) 거부. 사양 변경은 다른 월물 ID로 다룬다 |
| 전제조건 | 월물 사양이 참조 데이터로 주어진다 |
| 예외조건 | tick 정렬의 수치 허용 오차는 D3A-11 결정 후 정한다 (V1은 `abs_tol=1e-9`, `execution.py:15-26`) |
| 관련 ADR | ADR-0001 §6.2 (`M[c] > 0`, 전제조건, 예외조건). ADR-0006 I6-6, AT-0006-3 W2 |
| 관련 불변조건·결정 | INV-12, INV-13, INV-19. D3A-05, D3A-11 |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_futures_pnl_units`, `test_price_on_tick`, `test_unresolved_multiplier_blocks_money_calc`, `test_etf_uses_unit_multiplier`, `test_contract_multiplier_immutable` |

### AT-03A-16 같은 상품 통화의 복수 평가 환율

| 항목 | 내용 |
|---|---|
| Given | 평가 주기 t, BC = KRW. USD 평가 환율 후보로 1,500과 1,501이 함께 들어온다. USD 상품 두 개를 보유 |
| When | (a) `ValuationFxSet`을 만든다. (b) 결정 환율 1,495(이용 가능 08:30 Asia/Seoul)와 평가 환율 1,500(FX 평가 기준 시각 17:00 Asia/Seoul)을 함께 기록한다. (c) USD 순자산 1,000 USD가 있는데 USD 평가 환율이 없다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) `INVALID_VALUE`. 하나를 고르거나 평균 내지 않는다. (b) 허용. 역할(`DECISION`, `VALUATION`)과 시각이 각각 기록된다. (c) `missing_currencies = {USD}`, NAV를 확정하지 않는다. 1로 대체하지 않는다 (1로 쓰면 1,000 KRW로 평가되어 1,500,000 대비 **−1,499,000 KRW** 오류). LIVE에서는 USD 상품의 위험 증가 주문 차단 |
| 전제조건 | — |
| 예외조건 | 이전 환율 사용은 명시적 정책과 신선도 표시가 있을 때만 (Q8-7) |
| 관련 ADR | ADR-0008 X8-3, X8-5, §6.2, §6.5, AT-0008-8. ADR-0001 R2 예외조건 |
| 관련 불변조건·결정 | INV-26, INV-27. D3A-27, D3A-28 |
| V1 영향도 | 없음 (새 경로 전용) |
| 새 테스트 후보 | `test_one_valuation_rate_per_currency`, `test_decision_and_valuation_fx_both_recorded`, `test_missing_fx_never_defaults_to_one` |

### AT-03A-24 V1 변환기의 상품별 `fx_to_base` 충돌

| 항목 | 내용 |
|---|---|
| Given | V1 포트폴리오 입력. 가상 기호 `V1A`, `V1B` (둘 다 `InstrumentSpec.currency = "USD"`). 같은 날짜의 `ExecutionMarketDay`에서 `V1A`의 `fx_to_base` = 1,350, `V1B`의 `fx_to_base` = 1,351. V1은 이 입력을 받는다 (ADR-0001 R2) |
| When | (a) V1 API로 실행한다. (b) V1 변환기로 새 계약을 만든다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) V1 동작 그대로 (변경 없음). (b) 하나를 고르거나 평균 내지 않는다. **기대 결과 보류 (D3A-35)**: 후보 B는 `V1_COMPAT` 재현 전용의 상품별 환율 호환 기록, 후보 A는 변환 거부. 새 경로(`RESEARCH`, `LIVE`)에서 같은 통화에 두 값이면 거부한다 (X8-5) |
| 전제조건 | — |
| 예외조건 | 값이 같으면 통화별 환율 하나로 변환된다 |
| 관련 ADR | ADR-0001 R2, ADR-0008 X8-5, ADR-0004 AT-0004-4 |
| 관련 불변조건·결정 | INV-26. D3A-35 |
| V1 영향도 | 없음 (V1 API는 그대로) |
| 새 테스트 후보 | `test_v1_bridge_does_not_guess_conflicting_fx`, `test_v1_api_unchanged_with_per_instrument_fx` |

---

## 5. 정책, 열거값, 수량

### AT-03A-12 RESEARCH 위험 예산 입력

| 항목 | 내용 |
|---|---|
| Given | 새 연구 API 입력: 프로필 `RESEARCH`, `ExplicitRiskBudgetSeries` (수준 `ACCOUNT`, 625,000 BC/d, 출처, 이용 가능 시각) |
| When | (a) 입력을 검증한다. (b) 프로필 `LIVE`에 같은 입력을 넣는다. (c) V1 재현: V1 `ExecutionMarketDay.daily_cash_vol_target` = 625,000, 상품 가중치 0.5, IDM 1.2를 변환기로 옮긴다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) `UNSUPPORTED_OR_UNAPPROVED`로 거부 (Q4-7 미결정). 조용히 무시하거나 받지 않는다 (ADR-0005 E-10). **이것은 Q4-7의 "금지" 결정이 아니라 미결정 상태의 fail-closed다.** (b) 거부 (`LIVE`는 결정 시점 계좌로 계산, 승인된 원칙). (c) 수준 = 계좌 → 625,000 × 0.5 × 1.2 = **375,000 BC/d**. 수준 = 상품 → **625,000 BC/d**. 수준을 지정하지 않으면 거부 (ADR-0004 AT-0004-4) |
| 전제조건 | — |
| 예외조건 | Q4-7이 결정되면 (a)의 기대 결과를 승인된 변경으로 갱신한다 |
| 관련 ADR | ADR-0004 §6.3, Q4-7, AT-0004-4. ADR-0005 E-10, E-11 |
| 관련 불변조건·결정 | INV-17. D3A-32 |
| V1 영향도 | 없음. V1 API의 위험 예산 입력은 그대로다 |
| 새 테스트 후보 | `test_explicit_risk_budget_rejected_until_q4_7`, `test_live_rejects_explicit_risk_budget`, `test_v1_risk_budget_conversion_requires_level` |

### AT-03A-20 알 수 없는 열거값, 통화 코드, 프로필 우회

| 항목 | 내용 |
|---|---|
| Given | 값을 세 묶음으로 나눈다 (R1). **(1) 명백한 무효값**: 자산 유형 `"BOND"`(정의되지 않은 값), `None`, `""`. 데이터 상태 `"UNKNOWN"`(네 상태가 아님). 프로필 `""`, `None`. 통화 코드 `""`, `None`. **(2) 대소문자만 다른 열거값**: 프로필 `"live"`, `"V1_compat"`. 자산 유형 `"futures"`. **(3) 정책에 따라 결과가 달라지는 값**: 통화 `"usd"`(대소문자 정규화), `"US"`(형식 규칙), 형식상 세 글자 대문자지만 지원 목록에 없는 가상 코드 `"XQZ"`. 가격 종류 `"VALUATION"`(값 목록은 D3A-09) |
| When | 각 값으로 계약 객체나 설정을 만든다 |
| 입력값 | 위 값 |
| Then (기대 결과) | **(1) 거부.** 기본값(`FUTURES`, `V1_COMPAT`, 기준통화 등)으로 대체하지 않는다. Paper/Live 설정이면 시작을 거부한다. 근거: 프로필의 누락·빈 값·`None` 우회 금지는 [ACCEPTED] ADR-0001~0003 §8.0, 자산 유형 판별자는 [ACCEPTED] ADR-0006 §6.2, 데이터 상태가 네 값뿐인 것은 [ACCEPTED] ADR-0007 §6.4, 나머지 열거값으로 넓힌 것은 [제안] INV-32. 빈 통화 코드는 어떤 D3A-25 대안에서도 거부된다 (V1도 빈 값은 거부). **(2) 거부.** 프로필의 대소문자 변형은 [ACCEPTED] §8.0이 명시적으로 금지한다. 자산 유형 `"futures"`는 그 금지를 다른 열거값으로 넓힌 [제안] INV-32다. **(3) 기대 결과 보류 (통화: D3A-25, D3A-48 (4). 가격 종류: D3A-09)**. 가격 종류 `"VALUATION"`은 "평가가격을 종류 값으로 두지 않는다"는 [제안]을 채택하면 거부된다. 정책과 관계없이 지금 검증할 수 있는 것: `"usd"`가 `"USD"`와 다른 통화로 공존하지 않는다 (같은 통화의 금액·환율이 두 키로 갈라지지 않음). 어떤 값도 기본 통화나 기준통화, 다른 가격 종류로 조용히 대체되지 않는다. 정규화를 채택하더라도 조용히 하지 않고 Data Boundary에서 명시적으로 한다 |
| 전제조건 | — |
| 예외조건 | — |
| 관련 ADR | ADR-0001~0003 §8.0, ADR-0006 §6.2, ADR-0007 §6.4, ADR-0008 AT-0008-10 |
| 관련 불변조건·결정 | INV-17, INV-32. D3A-25, D3A-48 |
| V1 영향도 | 없음. V1 manifest의 기준통화 `.strip().upper()` 정규화는 V1 범위에서 그대로다 (`backtest_manifest.py:279-283`). 이 테스트는 새 계약에만 적용된다 |
| 새 테스트 후보 | `test_unknown_asset_type_rejected`, `test_profile_bypass_variants_rejected`, `test_empty_currency_code_rejected`, `test_currency_case_variant_never_creates_second_currency` |

### AT-03A-21 수량 단위·거래 단위 혼합과 lot

| 항목 | 내용 |
|---|---|
| Given | `Quantity(2, CONTRACT, FUT.ALPHA.C1)`, `Quantity(100, SHARE, ETF.US1)`, `Quantity(50, SHARE, ETF.KR1)`. `ETF.KR1`의 lot size = 10 (가상 참조 데이터). (c)용 가상 상황: `ETF.KR1` 10주 보유, 분할 전 가격 30,000 KRW, 3:2 분할(구주 2주당 신주 3주) |
| When | (a) 계약 수와 주 수를 더한다. (b) `ETF.US1` 100주와 `ETF.KR1` 50주를 더한다. (c) lot 규칙의 세 상황 (R1): (c1) 새 주문 수량으로 `ETF.KR1` 15주를 만든다. (c2) 10주 매수 주문이 3주만 체결되어 실제 포지션 +3주를 표현한다 (lot 미만 부분 체결이 생길 수 있는지는 시장·브로커별 UNVERIFIED). (c3) 3:2 분할 뒤 실제 보유 10 × 3/2 = 15주를 표현한다. (c4) (c3)의 15주를 lot 배수(10주 또는 20주)로 반올림해 기록한다. (c5) 15주 보유에 다시 3:2 분할을 적용한다. (d) 수량 값으로 `2.0`(실수)이나 `True`(bool)를 넣는다 |
| 입력값 | 위 값 |
| Then (기대 결과) | (a) `UNIT_MISMATCH`. (b) `UNIT_MISMATCH` (거래 단위가 다름. 제안 규칙, D3A-12). (c1) `UNIT_MISMATCH` (lot 10의 배수가 아님. [ACCEPTED] I6-5를 그대로 적용, 완화하지 않음. 승인 원칙 D3A-49 원칙 (3)과 같은 방향). (c2), (c3) **기대 결과 보류 (승인 원칙, ADR 개정 대기)**: 승인 원칙 D3A-49 원칙 (2)에 따르면 3주와 15주를 유효한 실제 수량 기록으로 표현해야 한다. 그러나 ACCEPTED ADR-0006 I6-5("정수여야 하고 lot size의 배수여야 한다")는 이 입력을 ValueError로 정한다 ([ADR 본문] AT-0006-3 예외조건도 같은 문장). 이 규범 충돌(결정 등록부 §9 CA-49)이 ADR 개정 승인이나 승인 범위의 해석 확인(§9.2.4 (라))으로 풀리기 전에는 기대 결과를 확정하지 않는다. 개정이 승인되면 기대 결과는 "정수 실제 수량으로 기록하고 lot 배수 검사를 하지 않음"이다. 그 뒤에도 새 주문과 목표 포지션에는 현행 lot 규칙이 적용되므로, 15주를 가진 상품의 자동 주문은 주문 수량(목표 − 15)이 lot 10의 배수가 될 수 없어 거래 단위 검사에 걸린다 (결정 등록부 §9.2.3의 알려진 결과). 남은 주문 잔량(7주)의 lot 처리는 D3A-49.1(결정 등록부 §9.2.1의 개정안 B를 따로 승인하지 않는 한), lot 미준수 표시 방식은 D3A-49.9 (미결정). (c4) 거부 (승인 원칙 D3A-49 원칙 (4). I6-5도 반올림이 아니라 거부를 요구하므로 충돌하지 않는다). 조용히 반올림하면 분할 후 기준가격 30,000 × 2/3 = 20,000 KRW에서 평가액이 15 × 20,000 = 300,000 KRW 대신 200,000 KRW(−100,000 KRW, −33%)나 400,000 KRW(+100,000 KRW, +33%)로 기록된다. (c5) 15 × 3/2 = 22.5주. 정수가 아니므로 거부 ([ACCEPTED] I6-5의 정수 규칙. AT-0006-4 예외조건과 같음. 소수 주 처리는 Q6-5). 이 사례는 15주 보유가 표현 가능하다는 (c3)의 전제(ADR 개정 대기) 위에 있지만, 정수가 아닌 분할 결과를 거부한다는 결론은 그 전제와 관계없이 같다 (예: lot 1인 `ETF.US1` 25주 × 3/2 = 37.5주도 거부). (d) `INVALID_VALUE` |
| 전제조건 | lot size가 참조 데이터로 주어진다 |
| 예외조건 | lot size가 없으면 LIVE에서 위험 증가 차단 (ADR 본문 근거: I6-11, D3A-48 (1)) |
| 관련 ADR | ADR-0006 I6-5, I6-8, AT-0006-3, AT-0006-4, Q6-5. ADR-0009 원칙 3·12 |
| 관련 불변조건·결정 | INV-12, INV-30. D3A-12, D3A-49 (승인 원칙. 원칙 (2)는 CA-49 개정 대기) |
| V1 영향도 | 없음 |
| 새 테스트 후보 | `test_contracts_and_shares_not_summed`, `test_quantities_of_different_units_not_summed`, `test_order_quantity_lot_multiple_required`, `test_actual_quantity_never_silently_rounded_to_lot`, `test_non_integer_split_result_rejected`, `test_quantity_rejects_float_and_bool` |

---

## 6. V1 보호

### AT-03A-13 V1 기존 타입과 신규 타입

| 항목 | 내용 |
|---|---|
| Given | V1 모듈 34개 (변경 없음). 새 도메인 계약 (향후 구현) |
| When | (a) V1 dataclass의 필드 이름·순서·기본값을 확인한다. (b) 테스트가 쓰는 V1 import 경로를 확인한다. (c) Stage 0 golden fixture로 V1 입력·결과 fingerprint를 계산한다. (d) 새 도메인 모듈만 import한 새 인터프리터의 `sys.modules`를 확인한다. (e) 새 도메인 클래스가 V1 클래스의 서브클래스인지, 도메인 타입 필드에 V1 인스턴스가 들어가는지 확인한다. (f) `python -m pytest -q -W error`를 실행한다 |
| 입력값 | 아래 |
| Then (기대 결과) | (a) `InstrumentSpec` = (symbol, currency, multiplier, tick_size). `ContractPrice` = (date, contract, close). `RollEvent` = (date, old_contract, new_contract). `BackAdjustedPrice` = (date, active_contract, raw_price, adjusted_price). `ContractQuote` = (bid, ask). `ExecutionMarketDay` = (date, daily_cash_vol_target, quotes, commission_per_contract, fx_to_base = 1.0, slippage_ticks = 0, margin_per_contract_base = 빈 dict 팩토리). 모두 현재와 같다. (b) `ContractQuote`(`carver_quant.roll_execution`), `ContractPrice`·`BackAdjustedPrice`(`carver_quant.futures_data`), `InstrumentSpec`(`carver_quant.instrument`), `ExecutionMarketDay`·`_prepare_backtest_from_point_in_time_signals`(`carver_quant.system_backtest`) 경로가 동작한다. (c) golden 값과 문자 단위로 같다. (d) V1 모듈과 pandas가 로드되지 않는다. (e) 둘 다 아니다. (f) 306 passed, 경고 0 (현재 기준) |
| 전제조건 | (c)는 Stage 0 golden이 있어야 실행할 수 있다 (D3A-41). 그 전까지 fingerprint 보존은 INFERRED다 |
| 예외조건 | 해시가 달라지면 변경을 되돌린다. golden 값을 고쳐 맞추지 않는다 (ADR-0004 AT-0004-3) |
| 관련 ADR | ADR-0004 P-1~P-6, AT-0004-3. ADR-0010 PK-1, PK-8, AT-0010-1, AT-0010-3. ADR-0011 FP-1~FP-4, AT-0011-1. ADR-0005 AT-0005-1 |
| 관련 불변조건·결정 | INV-16. D3A-36, D3A-40, D3A-41 |
| V1 영향도 | 이 테스트가 V1 보호의 직접 근거다 |
| 새 테스트 후보 | `test_v1_dataclass_fields_unchanged`, `test_v1_import_paths_unchanged`, `test_domain_import_loads_no_v1_or_pandas`, `test_domain_types_do_not_subclass_or_hold_v1_types` |

---

## 7. 기존 ADR 인수 테스트와의 관계

| AT-03A | 이어받거나 구체화하는 기존 테스트 | 관계 |
|---|---|---|
| 01 | ADR-0006 AT-0006-2, ADR-0001 AT-0001-3 | 월물 ID 필수를 식별자 타입으로 구체화. 가짜 손익 예제 추가 |
| 02 | ADR-0006 AT-0006-1 | 같은 규칙을 거래 단위 표현과 함께 검증 |
| 03 | ADR-0004 AT-0004-2 | 같은 숫자. 조정 → raw 변환 금지 추가 |
| 04 | ADR-0001 AT-0001-5 (B-1, B-2), ADR-0007 AT-0007-3 | PIT 술어를 관측 계약 수준에서 검증 |
| 05 | ADR-0007 AT-0007-5, AT-0007-1 | 공표 예상 ≠ 도착을 독립 시나리오로. R1: 같은 세션의 반복 판정 반례와 호출 이력 독립성 추가 (D3A-19) |
| 06 | ADR-0007 AT-0007-1 | 실제 UTC 시각과 경과 시간을 추가 |
| 07 | ADR-0007 AT-0007-3 | 가을 DST 전환 두 행 추가 |
| 08 | ADR-0001 AT-0001-9 W1, ADR-0006 AT-0006-3 W1, ADR-0008 X8-8 | 금액 계약의 연산 규칙으로 구체화 |
| 09 | ADR-0008 AT-0008-1 예외조건 | 방향을 필드로 가진 표현으로 검증 |
| 10 | ADR-0006 AT-0006-3 W2, ADR-0001 §6.2 | 작업 명세의 단위 예제, 사양 변경 규칙 추가 |
| 11 | ADR-0011 AT-0011-9 | 관측 계약과 PIT 뷰 쪽에서 같은 원칙 검증 |
| 12 | ADR-0004 AT-0004-4, ADR-0005 AT-0005-2 | Q4-7 미결정 상태의 fail-closed 추가 |
| 13 | ADR-0004 AT-0004-3, ADR-0010 AT-0010-1·AT-0010-3, ADR-0011 AT-0011-1, ADR-0005 AT-0005-1 | V1 보호 항목을 한곳에 모음 |
| 14 | ADR-0007 AT-0007-5 | NaN 입력 추가 |
| 15 | ADR-0004 AT-0004-4 | 슬리피지가 quote를 바꾸지 않음 추가 |
| 16 | ADR-0008 AT-0008-8, ADR-0001 AT-0001-9 예외조건 | 결정 환율과 평가 환율 공존 추가 |
| 17 | ADR-0007 C7-1, ADR-0011 FP-10 | naive·비UTC 시각 입력 규칙 (새 시나리오) |
| 18 | ADR-0007 AT-0007-3 예외조건 (Q7-8) | DST로 없거나 두 번 있는 현지 시각. Python `zoneinfo` 동작 확인 추가 |
| 19 | ADR-0007 AT-0007-1, AT-0007-7 | 휴장 평가가격을 체결 가격으로 쓰지 않음, 장 밖 접수 미확인 |
| 20 | ADR-0002 AT-0002-7, ADR-0008 AT-0008-10, ADR-0001 §8.0 | 열거값·프로필·통화 코드 우회를 한곳에 모음. R1: 명백한 무효값(거부)과 정책 의존 값(보류)을 분리 |
| 21 | ADR-0006 AT-0006-3, AT-0006-4 | 수량 단위·거래 단위 혼합과 lot 배수. R1: 새 주문 / 부분 체결 / 기업 행사 후 보유를 구분 (D3A-49) |
| 22 | ADR-0007 AT-0007-4 | (i)은 같은 기대 출력. (ii) 조기 도착은 새 시나리오 (보류) |
| 23 | ADR-0007 AT-0007-5 예외조건 | 달력 없음을 독립 시나리오로 |
| 24 | ADR-0004 AT-0004-4 | V1 변환기의 상품별 환율 충돌 (새 시나리오, 보류) |
| 25 | ADR-0004 AT-0004-4, ADR-0007 AT-0007-1, AT-0007-4 | Raw 정산가를 체결가로 확정하려는 시도 (R1 새 시나리오, (d) 보류). R1-FIX: 정산가 평가 조건 (c1)~(c5) |

### 7.1 승인 원칙과 인수 테스트의 대응 (R2)

새 AT를 만들지 않고 기존 AT에 대응시켰다. "명세상 확정"은 기대 결과가 명세에서 정해졌다는 뜻이며 구현되었다는 뜻이 아니다 (`SPECIFIED_NOT_IMPLEMENTED`).

| 승인 원칙 (2026-10-17) | 관련 AT | 기대 결과 상태 |
|---|---|---|
| D3A-19 원칙 (1) 세션별 상태 + 명시적 평가 주기 | AT-03A-05 (d3), 06, 22 | 원칙 반영. 기계적 규칙은 D3A-19.1~19.4 (보류) |
| D3A-19 원칙 (2) 같은 기준 세션 집합이면 호출 이력과 무관하게 같은 결과 | AT-03A-05 (f) | 명세상 확정. (d3)은 원칙 (1)과 R1 성질 P1의 반례 |
| D3A-19 원칙 (3) 늦은 도착 시 같은 세션 재판정 | AT-03A-05 (c) | 기대값 `FRESH`. 이를 내는 규칙은 D3A-19.3 (보류) |
| D3A-19 원칙 (4) 결측이 다음 세션·재호출 때문에 휴장으로 바뀌지 않음 | AT-03A-05 (d2), AT-03A-06 예외조건 | 명세상 확정 |
| D3A-19 원칙 (5) 미해결 세션을 조용히 가리지 않음 | AT-03A-05 | 외부 상태로의 집계는 D3A-19.4 (보류) |
| D3A-19 원칙 (6) 외부 상태 네 가지 유지 | AT-03A-23 | 명세상 확정 |
| D3A-19 원칙 (7) 확정한 판정 기록을 나중 데이터로 조용히 덮어쓰지 않음 | AT-03A-05 (e) | 명세상 확정. 기록 형식과 정정 절차는 D3A-19.8 (보류) |
| D3A-49 원칙 (1)·(6) 의미 분리, 책임 분리 | AT-03A-21 | 원칙 반영 |
| D3A-49 원칙 (2) 실제 수량의 사실 기록 | AT-03A-21 (c2)·(c3) | **보류 (ADR-0006 I6-5 개정 또는 해석 확인 대기, CA-49)** |
| D3A-49 원칙 (3) 신규 주문 제약의 별도 검증 | AT-03A-21 (c1) | 명세상 확정 (I6-5와 같음) |
| D3A-49 원칙 (4) 조용한 반올림·버림 금지 | AT-03A-21 (c4) | 명세상 확정 |
| D3A-49 원칙 (5) 미체결 잔량 ≠ 신규 주문 | AT-03A-21 (c2)의 남은 잔량 | 잔량의 lot 처리는 D3A-49.1 (보류) |
| D3A-50 원칙 (1)~(3) Raw의 의미, 정산가의 평가 사용 가능성 | AT-03A-03, AT-03A-25 (c) | 평가 사용은 평가 정책 승인 대기 (Q1-2, Q7-3, Q7-4) |
| D3A-50 원칙 (4)·(5)·(7) Quote ≠ Fill, 체결 기록의 출처, 세 가격 구분 | AT-03A-15, AT-03A-19 (a), AT-03A-25 (a)·(d) | (a)는 명세상 확정, (d)는 보류 (Q1-1, D3A-50.2) |
| D3A-50 원칙 (6) 정산가 → Quote 금지 | AT-03A-25 (b) | 계약상 확정. Python 생성자 수준의 강제는 구현 후 확인 |
| D3A-50 원칙 (8) Raw/Adjusted 분리 유지 | AT-03A-03 | 명세상 확정 (ACCEPTED ADR-0004 §6.4와 같음) |

## 8. 개정 이력

| 개정 | 날짜 | 내용 |
|---|---|---|
| R0 | 2026-10-17 | 최초 작성 (P0-03A). AT-03A-01~24. 모두 명세, 미구현. 작성 후 읽기 전용 독립 검토의 지적을 사용자 검토 전에 반영했다 (AT-03A-14의 LIVE 차단을 Q7-3 보류로 변경, AT-03A-11·22 보류 표시, AT-03A-09·15의 남은 위험 명시, AT-03A-07의 토요일 날짜 정정 등) |
| R1 | 2026-10-17 | P0-03A-R1 (문서 전용 보완). AT-03A-05에 반복 판정 반례 (d)와 판정 기록 불변 (e) 추가 (D3A-19 OPEN 유지). AT-03A-20을 명백한 무효값(거부) / 대소문자 변형 열거값(거부) / 정책 의존 통화 값(보류)으로 분리. AT-03A-21 (c)를 새 주문·부분 체결·기업 행사 후 보유로 나누고 실제 수량은 D3A-49 보류. AT-03A-22 (ii)의 철회된 대안 A 언급 정정. AT-03A-25 추가 (raw 정산가와 체결 가능성). 독립 검토 지적 반영: AT-03A-05 (c)·P1을 [제안] 기대값으로 표시, AT-03A-20 묶음 재배치(`"VALUATION"`은 보류), AT-03A-19 (a) 문구를 INV-33과 맞춤, AT-03A-25에 `decision_at`과 I-2 제약 추가, (b) 오류 표기 정정. 모두 명세, 미구현 |
| R1-FIX | 2026-10-17 | P0-03A-R1-FIX. AT-03A-25와 문서 머리의 개정 표기만 수정. (a) 30 USD 예제를 Given 밖의 가상 비교 시나리오로 분리하고 전제(ask 101.5 실제 체결, 스프레드 포함, 슬리피지 0, 수수료 별도 항)와 계산 근거(ADR-0001 §6.2 체결분 항)를 명시. quote와 체결가가 없으면 금액을 확정할 수 없음을 명시. (b) "표현할 수 없음"을 "계약상 변환 경로를 허용하지 않음, Python 생성자 수준 강제는 미확인"으로 정정. (c) 조건 없는 "허용"을 평가 정책 선택·월물·이용 가능 시각 조건과 (c1)~(c5)로 정정. 모두 명세, 미구현. 2차(수정 후 독립 검토 반영): (c)의 조건을 필요조건 넷으로 정리하고 세션 일치(`FRESH`) 조건 추가, (c3)·(c4) 변형 표시, Given에 `observed_at` 명시, (a)에서 실제 체결과 가정 구분 및 1.5 pt에 가격 변동이 포함됨을 명시, (c2)·(c3)의 근거를 AT-0007-1·AT-0007-4 예외조건으로 정정, 수수료 근거에 ADR-0008 원칙 14 추가. 3차: 문장 위치·관련 ADR·개정 표기 정리 |
| R2 | 2026-10-17 | P0-03A-FINAL. 2026-10-17 사용자의 D3A-19·D3A-49·D3A-50 핵심 원칙 승인을 반영. §0에 승인 원칙 표기 규칙 추가. AT-03A-05·19·21·22·25의 근거 표기를 승인 원칙과 하위 질문 ID로 갱신. AT-03A-21 (c2)·(c3)은 D3A-49 원칙 (2)가 ADR-0006 I6-5와 충돌하므로 "승인 원칙, ADR 개정 대기"로 보류. §7.1 승인 원칙과 AT의 대응표 추가 (새 AT 없음, AT 25개 유지). 기존 기대값과 숫자는 바꾸지 않음. 독립 검토 반영: AT-03A-05 (d3)의 근거를 원칙 (1)·P1로 정정하고 원칙 (2)를 검증하는 (f) 추가, AT-03A-19 (a)의 체결 구간 요건 출처 정정, AT-03A-21의 AT-0006-3을 [ADR 본문]으로 정정하고 (c5)에 전제 설명 추가, §7.1 갱신. 재확인 반영: AT-03A-05 원칙 (2) 문구에 같은 기준 세션 집합 조건 추가, AT-03A-19 (a)의 "승인된 체결 가정" 한정을 [제안]으로 표시, AT-03A-21에 개정안 A의 알려진 결과 연결. 모두 명세, 미구현 |
