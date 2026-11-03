# P1-03 EWMAC Forecast 최소 명세 (P1-03A 설계, 구현 전)

| 항목 | 내용 |
|---|---|
| 작업 | P1-03A EWMAC Forecast 설계 (구현 코드 없음) |
| 기준 | HEAD `5759146` + 커밋 전 P1-02 작업 트리 (P1_02_COMPLETE — READY_TO_COMMIT, P1-02 명세 §10) |
| 문서 상태 | 설계 명세. ADR이 아니며 [제안]은 승인 전이고 [OPEN]은 미결정이다. P1-03B 구현 명세의 출발점 |
| 표기 | CONFIRMED = 원문·코드·실행으로 확인, INFERRED = 근거로부터 추론, UNVERIFIED = 확인하지 못함 |

## 1. 범위와 근거

- **하는 것:** P1-02 As-of 연속 시계열 하나(decision cutoff 하나)로 fast·slow EWMA와 raw EWMAC를 계산하고, cutoff마다 따로 계산한 값을 모아 PIT forecast 시계열을 만든다. 변동성 정규화는 입력 계약만 정한다.
- **하지 않는 것:** 포지션 사이징, 위험 목표, 주문, 포트폴리오, 백테스트, forecast 결합·FDM, 거래 허용 판정(ADR-0002 정책 계층), 변동성 추정기 구현, forecast scalar·cap 값 확정.
- **Carver 원문 (UNVERIFIED):** *Advanced Futures Trading Strategies* PDF가 이 기기에 없어 확인하지 못했다. 아래 V1 내용은 코드로 확인한 것(CONFIRMED)이며, 원문과 대조하지 않았다.
  - EWMA는 `ewm(span, adjust=False)`이고 slow = 4 × fast다 (`forecast.py:76-91, 190-206`).
  - forecast = raw ÷ 가격 변동성 × scalar, cap ±20이다 (`forecast.py:94-157`).
  - `AFTS_EWMAC_SCALARS` 값의 상태는 UNVERIFIED다 (CLAUDE.md §7).
- **ACCEPTED 제약:**
  - **ADR-0004 §6.4:** 조정 가격은 신호 전용이고 `as_of`에 묶인다. 서로 다른 `as_of` snapshot끼리 차분하지 않는다. TC-C6도 같다.
  - **ADR-0002:** 계산 함수와 거래 허용 정책을 분리한다. 새 연구 API는 프로필을 명시해야 하며 기본값이 없다. warm-up 임계값은 Q2-1~Q2-9로 OPEN이다.
  - **ADR-0005:** 새 기능은 새 엔진에만 넣고, V1은 동결한다.
  - **ADR-0010:**
    - PK-9: lab이 V1 `forecast`·`volatility`를 import하는 것은 **미승인**이다.
    - PK-1·PK-2: 위치는 `lab.research`이고, `lab.domain`만 import한다.
  - **P1-02 명세 §10:** P1-03에 넘기는 필수 조건 다섯 가지.
- **V1 선례 (CONFIRMED):** V1의 PIT 신호는 as_of 날짜마다 조정 시계열을 다시 만들고, 전체를 계산한 뒤 마지막 점만 쓴다 (`research_pipeline.py:191-268`). 이 명세의 PIT 구성도 같은 원칙(snapshot마다 다시 계산)이다.

## 2. 입력 계약 [제안]

| 입력 | 계약 | 어기면 |
|---|---|---|
| `decision_cutoff` | 시간대가 있는 UTC 순간. 연구용 cutoff 목록은 호출부가 준다 (실제 의사결정 시각은 ADR-0007 Q7-1) | ValueError |
| `series` | P1-02 `AdjustedPriceSeries`. `basis = AS_OF_CUTOFF`, `as_of == decision_cutoff`, `method = FUTURES_ADDITIVE_BACK_ADJUSTED`, `algorithm_version`은 알려진 판본(`p1-02-additive-back-adjustment/1`) | ValueError (FULL_SAMPLE도 거부) |
| `accepted_evidence` | 요청한 근거와 `series.accepted_evidence`가 같음. 연구용 VENDOR_CAPTURE_PROXY | ValueError |
| `fast_span`, `slow_span` | `int`(bool 제외), 2 ≤ fast < slow (V1 `EWMACConfig`와 같은 제약). 쓸 규칙 조합은 호출부가 명시하며 기본값은 없다 | ValueError |
| `volatility` (선택) | §4의 변동성 입력. 없으면 raw EWMAC만 계산한다 | §4 |

- 계산에는 `series.points`의 `adjusted_price`만 쓴다. `excluded`(NOT_AVAILABLE, ROLL_NOT_YET_KNOWN, AFTER_ROLL_REFERENCE_DATE 등)는 보간하거나 다른 월물로 채우지 않고 출력에 그대로 보고한다.
- **늦게 도착한 정산가:** 금요일 최종가는 일요일에야 수집된다. 그 전 cutoff의 snapshot에는 그날 점이 없으므로 마지막 점은 목요일이다. 출력에 마지막 점의 날짜와 이용 가능 시각을 남긴다. 신선도 판단은 Q7-5다.
- **snapshot마다 다시 계산:** cutoff마다 그 cutoff의 snapshot 하나로 처음부터 계산한다. 이전 cutoff의 EWMA 상태를 이어 쓰는 증분 API는 두지 않는다. 롤이 알려지면 과거 조정 가격이 다시 쓰이고, R < d < N 점이 빠질 수도 있기 때문이다 (§6 (c)(d)).

## 3. EWMAC 계산 [제안: V1과 같은 공식]

**입력·출력·단위:** 입력은 조정 가격 p_0…p_n(index point)이다. α = 2 / (span + 1)이고 t는 snapshot 안의 연속한 점 순서(관측 단계)이며 달력 일수가 아니다.
- e_0 = p_0 (첫 점을 초기값으로)
- e_t = α·p_t + (1 − α)·e_{t−1}
- raw EWMAC_t = e^fast_t − e^slow_t (index point)

**성질 (§6에서 Fraction으로 확인):**
- 상수 이동 불변: p + k → raw 그대로
- 대칭: 2c − p → −raw
- 비례: λp → λ·raw
- 횡보: 0
- 선형 상승(기울기 s): raw_t = s·[(slow − 1)/2·(1 − (1 − α_s)^t) − (fast − 1)/2·(1 − (1 − α_f)^t)]. 극한은 s·(slow − fast)/2다.

**롤과의 관계:**
- raw EWMAC은 가격 차이만으로 정해진다. 그래서 롤이 알려져 과거 전체가 같은 값만큼 이동해도, 점 집합이 같으면 값이 같다.
- 점 집합이 바뀌면(R < d < N 제외) 값이 달라진다. 그때는 snapshot을 다시 계산하며, 그것이 올바른 값이다.
- EWMA 수준(e^fast, e^slow)은 그 snapshot 기준의 조정 가격 수준이므로 다른 snapshot과 차분하지 않는다. raw EWMAC과 정규화 값은 기준과 무관한 신호 값이다.

**Warm-up:**
- 계산은 임계값을 두지 않는다. 대신 진단 값 두 가지를 출력한다.
  - `observation_count`: 쓴 점 수
  - `slow_seed_weight`: slow EWMA에 남은 초기값 가중치 (1 − α_slow)^(n−1)
- 최소 관측 수의 형태와 값은 Q2-1로 OPEN이며, 거래 허용 정책 계층이 정한다.

**실패 조건:**
- ValueError: §2 표의 위반, 같은 거래일이 두 번 나오거나 순서가 어긋난 점, 비유한값.
- 계산 불가(예외 없이 값 없음 + 사유):
  - `NO_PRICE_POINTS`: 점 0개. 이른 cutoff에서는 정상적인 상황이다.
  - `VOLATILITY_NOT_AVAILABLE`, `ZERO_VOLATILITY`: 정규화만 해당한다.
- 점이 1개면 raw는 0이고 `observation_count`는 1이다.

**수치 정책 [OPEN, D3A-11]:**
- lab의 `EXACT_DECIMAL_CONTEXT`는 반올림이 생기면 실패한다. 그래서 α가 2/3, 2/9처럼 무한소수가 되는 span(2, 4, 8 … 256)으로는 계산할 수 없다 (CONFIRMED).
- 후보:
  - (A) 내부 Fraction 정확 계산, 출력에서 한 번 반올림
  - (B) 고정 Decimal 문맥(예: prec 28, ROUND_HALF_EVEN)으로 단계마다 반올림하고, 판본에 문맥을 기록 — **권장**: 결정적이고 float가 없다
  - (C) V1처럼 float
- 어느 쪽이든 테스트는 Fraction 기준값과 비교하고, 허용 오차를 명시한다.

## 4. 변동성 정규화 경계

- **raw와 정규화 구분:** raw EWMAC은 index point 단위다. 정규화 EWMAC = raw ÷ σ_p이며 단위가 없다. σ_p는 일별 가격 변동성(일별 가격 변화의 표준편차, index point / 거래일)이다.
- **σ_p 입력 계약 [제안]:**
  - P1-02 시계열과 같은 snapshot에서 만든 값이어야 한다: 같은 연구 ID, `as_of`, 근거, 롤 계획.
  - 시계열 마지막 점과 같은 거래일의 값이어야 한다.
  - 값은 Decimal ≥ 0 또는 None이고, 추정기 이름·판본과 쓴 변화 수를 함께 담는다.
  - 처리:
    - 다른 snapshot이거나 날짜가 다름 → ValueError
    - None → `VOLATILITY_NOT_AVAILABLE`
    - 0 → `ZERO_VOLATILITY` (V1과 같음)
    - 아주 작은 양수 → 거래 허용 정책의 `VOL_IMPLAUSIBLY_LOW` (Q2-2)
- **V1 재사용 불가 (PK-9 미승인).** V1 변동성은 다음과 같다.
  - `ewm(span=32, adjust=False, min_periods=2).std(bias=False)`
  - 여기에 `rolling(2560, min_periods=1)` 장기 평균을 0.7 : 0.3으로 섞는다 (`volatility.py:44-95, 97-145, 147-226`).
  - 가격 공백 전후의 차이를 변화 하나로 센다 (ADR-0002 §3.2). 이는 P1-02 §10 조건 3("공백을 1일 변화로 해석하지 않음")과 맞지 않는다.
  - 따라서 lab 변동성 추정기는 별도 명세가 필요하다. 정할 것: span, 장기 평균 혼합, 편향 보정, 공백 처리, `min_periods`(Q2-6). 이것은 P1-03C로 제안한다.
- **scalar와 cap:**
  - scalar는 정규화 값을 forecast 척도로 옮기고, cap은 ±한도로 자른다.
  - 어느 ACCEPTED ADR도 값을 정하지 않았다 (CONFIRMED, ADR 검색).
  - V1의 `AFTS_EWMAC_SCALARS`와 cap 20은 변경 승인이 필요한 V1 상수이며, 출처는 UNVERIFIED다.
  - 그래서 P1-03B는 scale·cap을 계산하지 않는다. 계산한다면 명시 파라미터와 출처를 받아야 하고, 기본값은 두지 않는다.

## 5. 출력 계약 [제안]

**`EwmacAtCutoff`** (cutoff 하나, 규칙 하나):
- 식별:
  - `research_instrument_id`, `decision_cutoff`(= `series.as_of`), `accepted_evidence`
  - `roll_plan_id`, P1-02 `algorithm_version`, 적용한 롤 수
  - `fast_span`, `slow_span`, 이 계산의 `algorithm_version`(가칭 `p1-03-ewmac/1`, P1-03B 커밋에서 처음 고정), `numeric_policy`
- 값:
  - `last_point_trading_date`, `last_point_available_at`, `observation_count`, `slow_seed_weight`
  - `fast_ewma`, `slow_ewma` (snapshot 기준 수준이며 진단용)
  - `raw_ewmac` (index point)
  - 선택: `price_volatility`, `risk_normalised_ewmac` (단위 없음)
- 보고:
  - `not_calculable_reasons`: 값이 있으면 비어 있다
  - snapshot의 제외 거래일
  - 앞 점과 거래일이 이어지지 않는 단계 수(`irregular_steps`). 달력이 없으므로 평일 공백 기준이며 INFERRED다.

**`PitEwmacSeries`:**
- 오름차순 cutoff 목록에 대한 `EwmacAtCutoff`의 나열이다. 각 원소는 자기 snapshot만으로 계산한다.
- raw·정규화 값은 cutoff 사이에 비교할 수 있다. EWMA 수준은 비교할 수 없다.

## 6. 독립 손계산 예제 (CONFIRMED)

가격은 모두 합성 값이고, 저장소 밖의 표준 라이브러리 Fraction 스크립트로 계산했다.

| 예 | span | 가격 | fast | slow | raw |
|---|---|---|---|---|---|
| (a) 상승 | 3, 7 (α = 1/2, 1/4) | 100, 102, 104, 106 | 100, 101, 102.5, 104.25 | 100, 100.5, 101.375, 102.53125 | 0, 0.5, 1.125, 1.71875 |
| (a) 하락 | 3, 7 | 100, 98, 96, 94 | 100, 99, 97.5, 95.75 | 100, 99.5, 98.625, 97.46875 | 0, −0.5, −1.125, −1.71875 |
| (a) 횡보 | 3, 7 | 100 × 4 | 100 … | 100 … | 0, 0, 0, 0 |
| (b) 상승 | 2, 8 (α = 2/3, 2/9) | 100, 102, 104, 106 | 100, 304/3, 928/9, 2836/27 | 100, 904/9, 8200/81, 74572/729 | 0, 8/9, 152/81, 2000/729 |

- **(b)의 추가 확인:**
  - prec 28 HALF_EVEN으로 바꾸면 raw_3 = 2.743484224965706447187928669이고, float는 2.7434842249657065(오차 약 9.4e−17)다.
  - 선형 상승 닫힌 식 s = 2, t = 3이 2000/729로 일치한다. 극한은 6이다.
- **(c) 롤 전후** (P1-02 합성 예: 9월물 100, 102(R) / 12월물 108, 110(R), 112(N), gap −8), span 2, 8:

| snapshot | 점 | raw |
|---|---|---|
| known_at 전 | 100, 102 | 0, 8/9 |
| known_at | 108, 110 | 0, 8/9 (같음: 이동 불변) |
| N 최종가 뒤 | 108, 110, 112 | 0, 8/9, 152/81 |
| 잘못된 예: raw 이어 붙임 | 100, 102, 112 | 0, 8/9, 440/81 (가짜 성분 32/9) |

- **(d) R < d < N** (P1-02 M2 예: R = Day 1, N = Day 3):
  - known_at 전 점 D1·D2(100, 102)의 raw는 8/9다.
  - known_at 뒤 점 D1·D3(108, 112)의 raw는 16/9다. 한 단계가 2거래일을 담으므로 `irregular_steps` = 1로 보고한다.
- **(e) 정규화:** raw_3 2000/729 ÷ σ 2 = 1000/729 ≈ 1.3717 (단위 없음). σ는 합성 값이다.

## 7. P1-03B 인수 테스트 목록 (명세)

1. **산술:**
   - (a) 예 정확값, (b) 예와 Fraction 기준(수치 정책의 허용 오차 안)
   - 선형 상승 닫힌 식과 극한
   - 이동 불변·대칭·비례·횡보 0
   - 상승 fast > slow, 하락 반대
   - span 검증 (fast ≥ slow, 정수 아님, bool, < 2 → ValueError)
2. **Warm-up:**
   - 점 0개 → `NO_PRICE_POINTS`
   - 점 1개 → raw 0
   - `observation_count`·`slow_seed_weight`가 손계산과 같음
   - 계산이 임계값으로 값을 숨기지 않음 (ADR-0002 AT-0002-2와 같은 분리)
3. **입력 시각과 종류 (ValueError):**
   - FULL_SAMPLE
   - `as_of ≠ cutoff`, 시간대 없는 cutoff
   - 근거 불일치
   - 다른 snapshot의 σ, 날짜가 다른 σ, 음수·비유한 σ
4. **σ 상태:** σ None → `VOLATILITY_NOT_AVAILABLE`, σ 0 → `ZERO_VOLATILITY`.
5. **결측:**
   - NOT_AVAILABLE 거래일을 보간하지 않고 보고함
   - 금요일 최종가 일요일 수집: 금요일 밤 cutoff의 마지막 점은 목요일
   - 평일 공백은 `irregular_steps`로 보고
6. **롤:**
   - (c): E − 1µs와 E에서 raw가 같음, N 뒤 152/81, raw 이어 붙임과 다름
   - (d): R–N 점 집합 변화 뒤 다시 계산한 값 16/9와 `irregular_steps`
7. **PIT:**
   - cutoff C의 값 = C까지 보인 기록만으로 만든 snapshot의 값 (미래 기록 추가 불변)
   - 앞 cutoff 값은 뒤 snapshot과 무관함
   - PIT 시계열 원소를 어떤 순서로 계산해도 같음 (상태 이월 없음)
   - 정정 전 cutoff는 정정 전 값을 씀 (소급 없음)
8. **정밀도:**
   - 두 번 실행해 바이트 단위로 같음
   - 입력·출력에 float 없음 (Decimal 정책일 때)
   - Fraction 기준과의 오차가 정책 한도 안
9. **V1 차등 비교 (참고용):**
   - 같은 가격 목록에서 V1 `calculate_ewmac_forecast`의 `raw_crossover`와 비교한다. 허용 오차는 D3A-42·ADR-0011이며 OPEN이다.
   - V1 결과는 정답이 아니다 (ADR-0011).
10. **실데이터 (선택 실행, 설정 없으면 skip):**
    - P1-02 원본으로 cutoff 여러 개(9-10 23:59:59.999999Z, 9-11T00:00Z, 9-13 11:35:53.511418Z, 9-30 끝)의 raw EWMAC (2,8)·(4,16)·(8,32)를 계산한다.
    - known_at 전후 값이 같아야 한다 (이동 불변).
    - 원본 CSV만 읽는 독립 재계산과 일치해야 하고, PIT sweep에서 불일치가 0이어야 한다.

## 8. 실데이터 적용 가능성

**지금 있는 데이터:** FULL_SAMPLE은 64개 점(2026-07-01~09-30)이다. 저장소 밖 원본으로 어느 cutoff의 As-of snapshot이든 새로 받지 않고 만들 수 있다 (CONFIRMED, P1-02B).

**초기값 잔존 가중치** (1 − α)^n:

| span | 64점 (n=63) | 1년 (n≈251) | 2년 (n≈503) |
|---|---|---|---|
| 8 | 0.0000 | 0 | 0 |
| 16 | 0.0004 | 0 | 0 |
| 32 | 0.0195 | 0 | 0 |
| 64 | 0.1396 | 0.0004 | 0 |
| 128 | 0.3737 | 0.0198 | 0.0004 |
| 256 | 0.6113 | 0.1407 | 0.0196 |

**판단 (INFERRED):**
- **64점:**
  - (2,8)·(4,16)·(8,32): 의미 있음
  - (16,64): 초기값 영향 14%
  - (32,128)·(64,256): 의미 없음
- **span 32 변동성:** 63개 변화의 뒷부분에서만 안정적이다.
- **V1식 장기 평균(2560일):** 불가능하다. MES 상장은 2019-05로 추정한다 (INFERRED).
- **실데이터에서 검증할 수 있는 것:** 롤 전후, PIT, 이동 불변, 결정성. 긴 규칙의 의미 있는 값은 검증할 수 없다.

**추가 이력 견적:** Databento `metadata.get_cost`로 무료 조회만 했다 (2026-11-03). **다운로드하지 않았고, 별도 승인 전에는 받지 않는다.** 롤 규칙은 P1-02 연구 시나리오와 같은 것(만기 8일 전 목요일)을 가정했다.

| 안 | 월물과 구간 (statistics + definition) | 레코드 | 견적 USD |
|---|---|---|---|
| 1년 | MESU5 2025-07-01~09-16, MESZ5 09-01~12-16, MESH6 2025-12-01~2026-03-17, MESM6 03-01~06-16, MESU6 06-01~07-01 | 199,067 | 0.015108697116 |
| 2년 추가 | MESU4 2024-07-01~09-17, MESZ4 09-01~12-17, MESH5 2024-12-01~2025-03-18, MESM5 03-01~06-17, MESU5 06-01~07-01 | 205,835 | 0.015615198761 |
| 합계 (2년) | | 404,902 | 0.030723895877 |

**조건:**
- 기존 MESU6 Snapshot(07-01부터)과 겹치지 않는다.
- 롤이 4~8개 늘어난다. 롤마다 연구 시나리오 승인이 필요하고, P1-02의 여러 롤 실데이터 검증도 필요하다. P1-02는 지금 롤 하나만 실데이터로 확인했다.

## 9. OPEN 정책

| ID | 내용 | 근거 |
|---|---|---|
| O-1 | 수치 정책 (Fraction / 고정 Decimal 문맥 / float), 출력 자릿수, 허용 오차 | D3A-11, ADR-0011 Q11-6 |
| O-2 | EWMA 초기값(첫 점, V1과 같음)과 단계 기준(관측 단계, V1과 같음 / 달력 일수)의 승인 | 이 명세 [제안], 달력 Q7-2 |
| O-3 | 쓸 규칙 조합(span 쌍)과 slow = 4 × fast 관례 | 전략 결정, Carver UNVERIFIED |
| O-4 | warm-up 최소 관측 수의 형태·값, `RESEARCH` 임계값 누락 처리 | ADR-0002 Q2-1, Q2-6, Q2-9 |
| O-5 | 변동성 추정기 (span, 장기 평균 혼합, 편향 보정, 공백 처리), vol 하한 | P1-03C 제안, ADR-0002 Q2-2, Q2-3 |
| O-6 | forecast scalar 값과 출처, cap 값 | V1 상수, UNVERIFIED |
| O-7 | 연구용 decision cutoff 일정, 실제 의사결정 시각, 신선도 임계값 | ADR-0007 Q7-1, Q7-5 |
| O-8 | V1 차등 비교 허용 오차 | D3A-42, ADR-0011 |
| O-9 | 모듈 위치와 이름 (제안: `lab/domain/ewmac.py`, `lab/research/ewmac.py`) | ADR-0010 PK-2, PK-12 |
| O-10 | 추가 이력 다운로드 범위·비용 상한, 과거 롤 시나리오 | 사용자 승인 |
| O-11 | ADR-0001 `signal_as_of`(가장 늦은 `observed_at`)를 정산가에 어떻게 채울지 (P1-01 정산가는 `observed_at`이 없다) | ADR-0001 §5.1.1, P0-03A |

## 10. P1-03B 구현 가능 여부

**조건부 가능.**

- **선행 조건:**
  1. P1-02 커밋 (지금 READY_TO_COMMIT이며 미커밋)
  2. O-1·O-2·O-9 결정
  3. P1-03B 범위 결정
- **제안 범위:**
  - §2 입력 검증
  - §3 raw EWMAC과 진단 값
  - §5 `EwmacAtCutoff`·`PitEwmacSeries`
  - §4의 σ 입력 계약에 따른 정규화 (σ는 호출부가 준다)
  - §7의 1~9 합성 테스트, 10은 기존 데이터로
- **제외:** 변동성 추정기(P1-03C), scale·cap(O-6), 결합·FDM, 거래 허용 정책, 사이징, 백테스트.
