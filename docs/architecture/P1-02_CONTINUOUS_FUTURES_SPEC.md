# P1-02 연속 선물과 롤 최소 명세 (MES, 명시적 롤 계획, 가산 back-adjustment)

| 항목 | 내용 |
|---|---|
| 작업 | P1-02 Continuous Futures & Roll |
| 기준 커밋 | `5759146` (P1-01 COMPLETE) |
| 문서 상태 | 이 Slice의 구현 명세. ADR이 아니며 실거래 롤 정책을 정하지 않는다. [OPEN]은 미결정 |
| 종료 상태 | P1_02_COMPLETE — RESEARCH_BASELINE_COMPLETE (2026-11-03, §10). P0의 LIVE_NOT_READY는 그대로다 |
| 표기 | CONFIRMED = 원문·코드·실행으로 확인, INFERRED = 근거로부터 추론, UNVERIFIED = 확인하지 못함 |

## 1. 범위

- 대상: CME Micro E-mini S&P 500, 2026년 9월물(`CME.MES.2026-09`)에서 12월물(`CME.MES.2026-12`)로 가는 롤 한 번. 연구용 식별자는
  `CME.MES.CONTINUOUS`이며 주문할 수 있는 계약이 아니다.
- 하는 것: 명시적 롤 계획, 거래일별 월물 선택, 롤 gap 계산, 가산(additive, Panama) back-adjustment, 일별 가격 변화, 품질·PIT 검사, 결정적 산출물.
- 하지 않는 것: 롤 날짜 자동 결정(거래량·미결제약정 기준 포함), 롤 주문·체결·비용, 손익, 포지션, 승수 사용, forecast, 여러 시장용 범용 엔진.

## 2. 근거와 이 구현의 선택

**Carver 원문 (UNVERIFIED)**: *Advanced Futures Trading Strategies*의 해당 장(작업 명세가 가리킨 PDF 24~30쪽, Appendix B)은 이 환경에 파일이
없어 확인하지 못했다. 아래 1~5는 작업 명세가 원문 내용으로 제시한 것이며, 이 문서는 이를 Carver의 확인된 주장으로 인용하지 않는다.

1. 선물은 만기가 있어 계약을 교체(롤)해야 한다.
2. 다른 월물의 가격을 그대로 이어 붙이면 월물 간 가격 차이가 가짜 가격 변화로 들어간다.
3. 가산 back-adjustment는 롤 시점의 두 월물 가격 차이만큼 과거 가격을 옮겨 이 차이를 없앤다.
4. 롤 거래비용은 가격 조정과 따로 다룬다.
5. 조정 가격은 거래소에서 체결할 수 있는 가격이 아니다.

**이 구현의 선택 (프로젝트 결정, P1-02 한정)**: 롤 날짜는 입력으로 받은 명시적 계획을 따른다. 롤 gap은 그 계획이 정한 시각
(`evidence_cutoff_at`)에 P1-01 PIT 조회로 보인 두 최종 정산가로 한 번 정하고, 그 뒤의 정정은 반영하지 않는다. 최신 월물을 기준으로 과거를
옮긴다 (최신 구간의 조정 가격 = raw 가격).

**승인된 설계 원칙 (ACCEPTED)**: ADR-0004 §6.4 — 조정 가격은 Research 계층만 만들고, `as_of`에 묶이며, 신호 계산에만 쓰고 체결·평가·명목가치·
증거금·현금에 쓰지 않으며, 서로 다른 `as_of` snapshot끼리 차분하지 않는다. P0-03A TC-C6(`AdjustedPriceSeries`)·TC-C7(`FuturesRollEvent`)의
ACCEPTED 부분(상품 ID, 효력일, 구·신월물 ID, known_at, 새 엔진은 PIT 구성만)을 따른다. V1 `futures_data`는 gap 부호가 반대(V1: 신 − 구, 조정 =
raw + Σgap)이고 날짜만으로 as-of를 정한다. 새 코드는 V1을 import하지 않는다 (ADR-0010 PK-9 미승인).

**Databento**: 개별 월물 raw symbol(`MESU6`, `MESZ6`)의 원래 정산가만 쓴다. 연속 symbol(`MES.c.0` 등)은 P1-01 Adapter가 거부한다.

## 3. 타입 (`lab/domain/continuous.py`, 이름은 가칭)

| 타입 | 필드 | 불변조건 |
|---|---|---|
| `RollPlanEntry` | `from_contract_id`, `to_contract_id`, `roll_reference_date`, `new_contract_first_date`, `selection_policy_id`, `evidence_cutoff_at` | 구 ≠ 신, 기준일 < 신월물 첫 거래일, cutoff은 UTC 순간이며 기준일 UTC 자정 이후 |
| `RollPlan` | `plan_id`, `research_instrument_id`, `initial_contract_id`, `accepted_evidence`, `entries` | 월물 사슬이 이어짐(앞 롤의 신월물 = 다음 롤의 구월물), 같은 월물 반복 없음, 날짜 순서, 연구용 ID ≠ 월물 ID. 중복·상충 롤은 만들 수 없다 |
| `FuturesRollEvent` (TC-C7) | 위 계획 항목 + `old_reference_price`, `new_reference_price`, `roll_gap_points`, `reference_prices_available_at`, 원본 레코드·Snapshot ID | gap = 구 − 신 (정확한 Decimal). 효력일 = 신월물 첫 거래일, known_at = `evidence_cutoff_at`, 두 가격의 이용 가능 시각 ≤ known_at |
| `AdjustedPricePoint` | `trading_date`, `selected_contract_id`, `raw_price`, `cumulative_adjustment_points`, `adjusted_price`, `daily_price_change_points`, `change_from_trading_date`, `source_record_id`, `source_snapshot_id`, `available_at`, `availability_evidence` | 조정 = raw − 누적 조정 (정확). 변화량은 같은 시계열 안의 앞 점과의 차이이며 첫 점은 없음. 부호 제약 없음 |
| `AdjustedPriceSeries` (TC-C6) | `research_instrument_id`, `method`, `algorithm_version`, `basis`(FULL_SAMPLE / AS_OF_CUTOFF), `as_of`, `accepted_evidence`, `roll_plan_id`, `initial_contract_id`, `applied_rolls`, `points`, `excluded` | 모든 점의 이용 가능 시각 ≤ `as_of`, 적용한 롤의 known_at ≤ `as_of`, 월물 구간·누적 조정·변화량이 적용한 롤과 맞음 |

가격 종류는 필드로 구분한다: `raw_price`(선택 월물의 최종 정산가, raw), `adjusted_price`(연구용 조정, 신호 전용), `daily_price_change_points`
(같은 시계열 안의 조정 가격 차분, index point). 조정 가격에 백분율 수익률을 계산하지 않는다.

## 4. 계산 (`lab/research/continuous.py`, 알고리즘 `p1-02-additive-back-adjustment/1`)

- 월물 선택: 첫 롤의 신월물 첫 거래일 전까지는 처음 월물, 각 롤의 신월물 첫 거래일부터 다음 롤 전까지는 그 신월물. 선택한 월물의 P1-01
  최종가가 없는 날은 다른 월물로 대신하지 않고 제외 목록에 남긴다. 구월물의 기준일 뒤·신월물 첫 거래일 전 점은 연속성을 깨므로 제외한다.
- 롤 gap: `roll_gap = old_price_at_roll − new_price_at_roll` (같은 기준일의 두 최종 정산가, `evidence_cutoff_at`에 받아들인 근거로 보인 값).
  둘 중 하나라도 보이지 않으면 gap을 추정하지 않는다 (해결되지 않은 롤).
- 누적 조정: 날짜 d의 누적 조정 = d 뒤에 효력이 생기는 (신월물 첫 거래일 > d) 적용 롤 gap의 합. `adjusted = raw − 누적 조정`.
- 일별 변화: 같은 시계열에서 앞 점과의 조정 가격 차이. 롤 경계에서는 신월물의 기준일 → 첫 거래일 가격 변화와 같아야 한다.
- 손계산 예 (작업 명세 §5): 9월물 100, 102(기준일), 12월물 108, 110(기준일), 112 → gap −8, 조정 108, 110, 112, 변화 +2, +2.

## 5. PIT

- 롤은 `evidence_cutoff_at`(known_at)부터 알려진다. 기준 가격은 P1-01 `get_final_settlement_asof`로 그 시각에 받아들인 근거(연구용
  VENDOR_CAPTURE_PROXY = Databento `ts_recv`)로 보인 최종가다. `ts_event`로 앞당기지 않는다.
- As-of 시계열(cutoff C): 각 월물의 P1-01 As-of Series(cutoff C)와 known_at ≤ C인 롤만 쓴다. known_at > C인 첫 롤의 신월물 첫 거래일부터는
  선택하지 않고, 그날 이후 보인 구월물 기록은 ROLL_NOT_YET_KNOWN 제외로 남긴다. 그 cutoff의 품질 보고서도 known_at ≤ C인 롤만 판단한다.
- R과 N 사이에 거래일 d가 있으면: 롤이 알려지기 전(C < known_at)의 As-of 시계열은 d의 구월물 점을 조정 없이 쓰고, 알려진 뒤(C ≥ known_at)의
  시계열은 그 점을 AFTER_ROLL_REFERENCE_DATE로 제외한다 (신월물로 대신하지 않음, 경계 변화는 신월물의 R → N 변화). 앞 cutoff의 결과는 바뀌지 않는다.
- Full-sample 시계열: 자료 끝 시각을 `as_of`로 둔 같은 PIT 구성이며 계획의 모든 롤을 적용한다. 사후 연구·시각화용이며, 그 수준을 `as_of` 전의
  판단에 쓰면 안 된다 (미래 롤 gap이 과거 가격에 반영되어 있음).
- 롤 기준일은 가격을 잇는 회계적 기준일이다. 주문 시각·주문 가격·체결 가격·비용이 아니다. 늦게 알려진 최종가로 그날 롤을 실행할 수 있었다고
  가정하지 않는다.

## 6. 품질 검사 (`lab/research/continuous_quality.py`, 규칙 `p1-02-continuous-quality/1`)

입력 연결(같은 계획·근거·처음 월물·알고리즘·cutoff, 롤 결정 결과와 같은 적용 롤, 시계열이 쓴 Snapshot을 덮는 월물 보고서)이 맞지 않으면
ValueError다. CONTRACT_IDENTITY, ROLL_ORDER(만기 순서, 기준일·첫 거래일과 만기), EXPIRY(선택한 날 ≤ 마지막 거래일), REFERENCE_PRICES(같은 기준일의 두 가격,
해결되지 않은 롤), OVERLAP(두 월물에 최종가가 모두 있는 거래일 수), SELECTION_COVERAGE(선택 월물의 누락 정산가, 제외한 점),
MISSING_SESSIONS(요청 범위를 덮는 달력이 있을 때만 판정, 휴장일과 결측 구분), PIT, DECIMAL_PRECISION, ADJUSTMENT_ARITHMETIC(변화량을 원래 월물의
raw 변화로, 롤 경계는 같은 as_of 입력의 신월물 기준일 가격으로 독립 재계산. 기준가가 known_at 뒤에 정정되면 기대 경계 변화 = 신월물 자신의 변화 +
(신월물 정정분 − 구월물 정정분)이며, 이것으로 설명되는 어긋남은 경고, 설명되지 않는 어긋남은 차단),
SOURCE_INTEGRITY, CONTRACT_DATA_QUALITY(월물별 P1-01 품질 보고서). 상태는 P1-01과 같은 PASSED / WARNING /
NOT_ASSESSABLE / BLOCKED.

## 7. 산출물과 조립

- 조립: 테스트(또는 승인된 실행 경계)가 P1-01 Adapter·PIT 조회로 월물별 입력을 만들고 `lab.research`에 넘긴다. `lab.research`는 `lab.domain`만
  import한다 (ADR-0010 PK-2·PK-3. `lab.app`은 미승인이라 만들지 않음).
- 파일 (`lab/adapters/continuous_export.py`): `roll_plan.json`, `roll_events.json`, `continuous_series.json`(FULL_SAMPLE),
  `continuous_series_asof_<cutoff>_<근거>.json`, `quality_report.json`, `processed_manifest.json`(월물별 statistics·definition Snapshot의
  원본·manifest 해시와 월물 ID,
  메타데이터 판본, 롤 계획 ID·해시, 선택 정책, 조정 알고리즘·품질 규칙 판본, P1-01 상위 판본, 달력 출처, 산출물 해시), `run_log.json`(해시 제외).

## 8. 미결정 사항 [OPEN]

- 실거래 롤 정책: 롤 날짜, 유동성 기준, 롤 주문 방식·비용. 실데이터 예시의 기준일(9월물 만기 전 주 목요일)은 연구용 시나리오다.
- Tick value: Databento 문서의 공식(tick 금액 ÷ display factor ÷ (tick × 계약 크기) = 1)으로는 0.0125 / 0.01 / (0.25 × 5) = 1, tick value 1.25 USD.
  Databento도 이 scale을 추론으로 보고 거래소 사양 확인을 권한다. CME 사양 페이지는 이 환경에서 열리지 않았다. P1-02는 tick value를 쓰지 않는다.
- 정산 tick·반올림 규칙 (미확인. 정산가를 이것으로 거부하지 않는다).
- 거래소 달력: 2026-07-03은 정산 기록이 없고 7-2 최종가가 7-5에 다시 나와 휴장으로 추정 (CME 공지 PDF는 이 환경에서 열리지 않음). 9-7(Labor
  Day)도 두 월물 모두 정산 기록이 없어 휴장으로 추정하나 미확인. 전체 기간 달력 없이 결측 검사를 통과했다고 하지 않는다.
- 데이터 라이선스: 원본은 저장소 밖에서만 관리하고 재배포하지 않는다 (P1-01 `DATA_NOTES.md`).
- P1-03(EWMAC)은 PIT As-of 시계열만 입력으로 써야 하고, 다른 `as_of`의 조정 가격끼리 차분하지 않는다. P1-05(백테스트)는 롤 비용을 체결
  다리로 따로 계산해야 한다 (ADR-0006 I6-9).

## 9. 실데이터 검증 (P1-02B, 2026-11-03)

- 원본: Databento GLBX.MDP3 statistics·definition. MESU6는 P1-01 Snapshot(7-01~9-01)과 연장분(9-01~9-21), MESZ6는 8-01~10-01. 원본·설정·산출물은
  저장소 밖(`~/carver-data/databento/`)에만 있고, 실데이터 테스트는 `CARVER_P1_02_REAL_DATA_CONFIG`가 있을 때만 돈다. 가격 값은 라이선스 때문에 이
  문서와 저장소에 적지 않는다.
- 연구용 롤 시나리오 (실거래 정책 아님): 기준일 = 구월물 마지막 거래일(9-18) 8일 전 목요일 9-10, 신월물 첫 거래일 = 다음 거래일 9-11, gap 확정
  시각(known_at) = 기준일 다음 UTC 자정 2026-09-11T00:00:00Z. 두 기준일 최종가는 그 전(9-10 23:39Z경)에 공급자가 수집했다. 기준일 규칙은 CME 지수
  선물 관행을 따른 추론이다 (INFERRED).
- 확인한 것 (CONFIRMED: 실행 결과): 두 월물 definition의 instrument ID·만기·계약 크기·tick·통화가 메타데이터와 맞음, 두 월물에 최종가가 모두 있는
  거래일 34일, 롤 경계 변화 = 신월물 자신의 변화, 원본 CSV만 읽는 별도 스크립트(구현 import 없음)로 gap·모든 조정 가격·변화·As-of 시계열을 정확히
  재계산해 일치, 롤 구간의 cutoff 289개(모든 수집 시각과 그 1µs 전, known_at 전후, UTC 자정 경계)에서 미래 기록이 결과를 바꾸지 않음, 별도
  프로세스로 여러 번 내보낸 결과가 실행 기록(`run_log.json`) 외의 14개 파일 모두 바이트 단위로 같음 (`cmp`. P1-02C 보완 뒤 최종 코드로도 같음).
- 관찰: (1) 금요일 최종가처럼 같은 값이 다시 발행되면 P1-01 선택 규칙(cutoff까지 보인 최신 final)에 따라 점의 `available_at`이 첫 수집이 아니라
  재발행 수집 시각이 된다. 실제보다 늦은 쪽이라 미래 정보 누출은 아니다. (2) 신월물 거래량은 기준일에 구월물보다 훨씬 작았고 다음 주에 역전되었다
  (statistics cleared volume의 `ts_ref` 날짜 의미는 미확인, INFERRED). 실거래 롤 날짜를 정할 때의 참고 자료이며 이 단계는 쓰지 않는다.

## 10. 종료 상태 (2026-11-03)

- **P1_02_COMPLETE — RESEARCH_BASELINE_COMPLETE**: 연구용 연속 선물 가격(명시적 롤 계획, 가산 back-adjustment, PIT As-of 시계열, 품질 검사,
  결정적 산출물)의 구현과 실데이터 검증(P1-02B), 독립 검토(P1-02C, MEDIUM 2건 보완)가 끝났다. P0의 LIVE_NOT_READY 상태는 그대로다.
- 승인되지 않은 것: 실거래 롤 정책(롤 날짜·유동성 기준·주문). 검증 대상이 아닌 것: 롤 비용, 실제 체결, 손익(P&L).
- PIT 근거는 연구용 VENDOR_CAPTURE_PROXY(Databento `ts_recv`)이며 사용자 수신 시각이 아니다.
- OPEN: 거래소 달력, 일부 메타데이터(tick value, 정산 tick, 결제 방식), 데이터 라이선스 (§8).
- 판본과 코드 출처: `p1-02-additive-back-adjustment/1`, `p1-02-continuous-quality/1`, 산출물 형식 `carver-lab-continuous-futures-dataset` 1은
  P1-02 커밋에서 처음 고정된다 (그 전 커밋에는 없음). 처리 manifest는 이 판본들과 P1-01 상위 판본·선택 정책·원본 Snapshot 해시를 기록하지만 코드
  커밋은 기록하지 않는다. 따라서 산출물의 코드 출처는 커밋 해시로 따로 남기며, 이 판본들의 동작을 바꾸는 코드 변경은 판본을 올려야 한다 (같은
  판본 문자열을 같은 동작의 증거로 쓰지 않는다). 실데이터 공식 산출물은 P1-02C 보완 전 작업 트리로 만들었고, 보완 뒤 최종 코드로 다시 내보낸
  결과와 해시 대상 14개 파일이 바이트 단위로 같다.
- P1-03에 넘기는 필수 조건:
  1. Forecast 입력은 한 시점(`as_of`)에 고정된 As-of 연속 시계열을 쓴다.
  2. 서로 다른 `as_of` 판의 조정 가격끼리 직접 차분하지 않는다 (롤이 알려지면 과거 조정 가격이 다시 쓰인다).
  3. 빠진 거래일과 롤 기준일 R ~ 신월물 첫 거래일 N 사이의 공백을 1일 가격 변화로 해석하지 않는다 (`change_from_trading_date`로 실제 간격을 본다).
  4. FULL_SAMPLE 조정 가격을 과거 시점에 알려진 가격으로 쓰지 않는다.
  5. EWMAC forecast 계산과 trading framework(사이징·위험·비용·체결)의 책임을 나눈다.
