# P1-01 시장 데이터 최소 명세 (MES 2026년 9월물 일별 최종 정산가)

| 항목 | 내용 |
|---|---|
| 작업 | P1-01 Market Data Vertical Slice |
| 기준 커밋 | `b79d179` (P0 종료: P0_RESEARCH_READY, LIVE_NOT_READY) |
| 문서 상태 | 이 Slice의 구현 명세. ADR이 아니며 운영 정책을 정하지 않는다. 표의 [OPEN]은 미결정 |
| 표기 | CONFIRMED = 원문·코드로 확인, INFERRED = 근거로부터 추론, UNVERIFIED = 확인하지 못함 |

## 1. 범위

- 대상: CME Micro E-mini S&P 500 선물, 2026년 9월물 하나 (`CME.MES.2026-09`), 요청 기간 2026-07-01 ~ 2026-08-31, 일별 최종 정산가.
- 하는 것: Raw Snapshot 보존, 월물 메타데이터 검증, 공급자 Adapter 하나(Databento GLBX.MDP3 `statistics`), 정산가 사건 정규화,
  품질 검사, PIT 조회, 연구용 정산가 Series와 품질 보고서·처리 manifest 생성.
- 하지 않는 것: 연속 선물, back-adjustment, 롤, forecast, 사이징, 포트폴리오, 비용, 주문·체결, 백테스트, 브로커, 증거금, FX.
  P0의 주문·체결·현금·NAV·안전 게이트·Journal과 연결하지 않는다.

## 2. 월물 메타데이터

| 필드 | 값 | 근거 |
|---|---|---|
| 승수 | 5 USD / index point | INFERRED: CME가 게시한 FAQ·교육 자료 (검색 결과). CME 계약 사양 페이지는 이 환경에서 403 |
| outright tick / tick value | 0.25 pt / 1.25 USD (= 0.25 × 5) | 같음. tick value는 코드가 정확한 Decimal로 다시 계산해 선언값과 비교 |
| 정산 tick (청산 tick) | 미확인 → `None` | [OPEN] 거래 tick과 다를 수 있음 (Databento `stat_flags` bit 2). 확인 전에는 정산가를 outright tick으로 검사하지 않는다 |
| 마지막 거래일·시각 | 2026-09-18, 13:30:00Z (08:30 CT, CDT) | 9월 셋째 금요일은 독립 계산. 08:30 CT 종료는 오래된 CME 자료 (INFERRED). UTC 변환은 고정 시차가 아니라 문서 확인 값을 입력으로 받는다 (타임존 DB 없음, ADR-0010 Q10-7) |
| 결제 | CASH (Special Opening Quotation) | INFERRED: CME FAQ |
| 내부 월물 ID | `CME.MES.2026-09` = `{exchange}.{root}.{YYYY}-{MM}` | 이 Slice의 형식 |

## 3. 공급자 필드 대응 (Databento `statistics`, `stat_type` = 3)

| Databento 필드 | 의미 (CONFIRMED: Databento 문서) | `SettlementEvent` |
|---|---|---|
| `ts_ref` | CME 5796-TradingReferenceDate. 날짜 정밀도이며 현지화하지 않는다 | `trading_date` (UTC 자정이어야 함) |
| `ts_event` | 60-TransactTime, 매칭 엔진 수신 시각 | `published_at` (거래소 근거) |
| `ts_recv` | Databento 수집 서버 수신 시각 | `vendor_received_at` (공급자 근거. 사용자 수신 시각이 아님) |
| (Snapshot 획득 시각) | 이 시스템이 원본을 받은 시각 | `ingested_at` |
| `price` | int64, 1 단위 = 1e-9. `INT64_MAX`는 값 없음 | `price` = `Decimal(price).scaleb(-9)` (float 없음) |
| `stat_flags` bit 0 / 1 / 2 / 3 | 최종 / 실제(이론가 아님) / 거래 tick 정산 / 장중 정산 | `revision_status` FINAL·PRELIMINARY, `actual`, `at_trading_tick`, `price_type` INTRADAY·DAILY. 다른 bit가 있으면 차단 |
| `update_action` | 1 추가, 2 삭제 | 2이면 `WITHDRAWN` |
| `instrument_id`, `symbol` | CME 상품 ID, 원 symbol (`MESU6`) | 대응표로 `contract_id`와 대조. `.`가 든 연속·부모 symbol은 거부 |
| `ts_recv`·`sequence`·`instrument_id`·`stat_type` | 레코드 식별 | `source_record_id` = `databento:{dataset}:{instrument_id}:{ts_recv}:{sequence}:{stat_type}` |
| (Snapshot ID) | 원본 바이트의 SHA-256 | `source_snapshot_id` |
| (도출) | 시스템 수신 전 가장 강한 근거 | `availability_evidence`: 공급자 수집 시각이 있으면 VENDOR_CAPTURE, 거래소 시각만 있으면 EXCHANGE_PUBLICATION, 둘 다 없으면 SYSTEM_RECEIPT |

- 나노초 시각은 마이크로초로 **올림**한다 (이용 가능 시각을 실제보다 앞당기지 않음). 원래 나노초 값은 `source_record_id`에 남는다.
- CSV 열 이름은 Databento 문서의 필드 목록과 `map_symbols`의 `symbol` 열이다 (INFERRED: 실제 파일로 확인하지 못함, §8).
- 정산가가 결정된 시각(`observed_at`)은 이 공급원에 없어 `None`이다.

## 4. 상태, 정정, PIT (선택 정책 `p1-01-final-settlement-selection/1`)

- 공급자 상태는 `PRELIMINARY` / `FINAL` / `WITHDRAWN`이다. 정정(`CORRECTION`)은 같은 거래일에 보인 최종가 가운데 다른 가격이 있는 마지막
  최종가이며, 조회 시점에 보이는 기록만으로 판정한다 (수정본은 별도 관측, ADR-0004 §6.5). 원본 이력은 지우지 않는다.
- 이용 가능 시각 근거: `SYSTEM_RECEIPT`(`ingested_at`) > `VENDOR_CAPTURE`(`vendor_received_at`) > `EXCHANGE_PUBLICATION`(`published_at`).
  `get_final_settlement_asof(events, contract_id, trading_date, cutoff_at, *, accepted_evidence)`는 작업 명세의
  `get_final_settlement_asof(contract_id, trading_date, cutoff_at)`에 순수 함수 입력(`events`)과 받아들일 가장 약한 근거(**기본값 없음**)를
  더한 형태다. 받아들인 근거와 더 강한 근거의 시각 가운데 가장 이른 시각이 `cutoff_at` 이하인 기록만 보인다. cutoff는 시간대가 있어야
  하고 UTC로 바꾼다.
- 순서: 보인 기록은 공급원 순서로 놓는다. **cutoff까지 알려진 시각만 쓴다**: 모든 보인 기록의 공급자 수집 시각이 있고 cutoff 이하이면
  그 시각, 아니면 거래소 시각이 그렇다면 그 시각이다. 두 시각을 모두 쓸 수 있는데 내용이 다른 두 기록의 순서가 서로 반대이면
  `AMBIGUOUS`(SOURCE_ORDER_INVERSION)다. 수신 순서나 공급자 sequence로 고르지 않는다. 늦게 받은 Snapshot에 다시 들어 있는 옛 최종가가
  정정을 덮지 않는다.
- 결과: `AVAILABLE`(최종가, 쓴 근거, 이용 가능 시각, 정정 여부), `NOT_AVAILABLE`(보인 기록 없음, 잠정가만 있음, 철회로 끝남, 장중·이론
  정산가만 있음), `AMBIGUOUS`(같은 순서 위치에 다른 내용, 순서를 정할 수 없는 다른 내용, 순서 시각끼리 반대, 최종가 뒤의 잠정가),
  `EVIDENCE_INSUFFICIENT`(받아들인 근거 수준의 시각이 없고 더 강한 근거의 시각은 cutoff 뒤인 기록이 있음). 더 약한 근거의 시각이 cutoff
  뒤인 기록은 근거 부족이 아니라 아직 보이지 않은 기록이다 (거래소 표시 → 공급자 수집 → 수신 순서). 보인 기록이 없을 때 아직 보이지 않은
  기록이 있다는 사실을 사유로 드러내지 않는다. 장중 정산가와 이론가는 최종가로 쓰지 않는다.
- `SettlementAsOf.event`는 원본 기록 그대로라 cutoff 뒤의 시각 필드를 담을 수 있다. cutoff 시점의 지식으로 쓰는 값은 가격, 정정 여부,
  `available_at`, `evidence_used`이며, 도메인 타입이 이 두 값이 사건의 가장 이른 허용 근거 시각과 맞는지 검사한다.
- 연구 Series는 두 종류이며 API·basis·파일 이름으로 구분한다: `LATEST_FINAL_IN_SNAPSHOT`(`latest_final_series`. Snapshot에 있는 마지막
  최종가. 이용 가능 시각을 보지 않으므로 PIT가 아님)와 `AS_OF_CUTOFF`(`asof_final_series`. cutoff에 알려진 거래일만 넣고 각 점에 이용 가능
  시각과 쓴 근거를 기록).

## 5. 품질 검사 (규칙 버전 `p1-01-settlement-quality/1`)

SCHEMA, CONTRACT_IDENTITY, DECIMAL_PRICE, PRICE_UNIT, TICK(거래 tick·정산 tick 구분), DATE_AND_EXPIRY, TIMESTAMP_TIMEZONE,
DUPLICATES_AND_CONFLICTS, MISSING_SESSIONS(요청 기간을 덮는 달력이 주어질 때만 판정, 없으면 평일 공백을 미확인으로 표시), REVISION_ORDER,
SOURCE_INTEGRITY(합성 데이터 표시, Snapshot 연결. 원본 해시는 Snapshot을 읽을 때 검증), AVAILABILITY_EVIDENCE, COVERAGE(최종가가 있는
거래일 수 ≥ 요청 최소값). 각 검사는 `PASSED` / `WARNING` / `NOT_ASSESSABLE` / `BLOCKED`이며 전체 상태는 가장 심한 검사 상태다. 보간·
forward fill을 하지 않는다. 규칙별 차단·경고 조건은 `lab/marketdata/quality.py` 모듈 설명에 있다.

## 6. 산출물과 재현성

출력 디렉터리마다: `normalized_settlements.json`, `research_settlements_latest_final.json`, (요청 시)
`research_settlements_asof_<cutoff>_<evidence>.json`, `quality_report.json`, `processed_manifest.json`(Raw Snapshot별 원본·manifest SHA-256,
출처 표시, 획득 시각, Adapter·품질 규칙·메타데이터 버전, 선택 정책, 산출물별 SHA-256)과 `run_log.json`(실행 시각 등 실행마다 다른 값.
manifest의 해시에서 제외). 같은 Snapshot·같은 입력이면 `run_log.json`을 뺀 산출물이 바이트 단위로 같다. Raw Snapshot은 `raw-sha256-<해시>`
디렉터리에 원본 바이트와 manifest로 보관한다. Snapshot ID는 원본 바이트만 덮으므로, 읽을 때 기록해 둔 manifest SHA-256을 넘겨야 manifest
(출처 표시·획득 시각) 변경을 검출한다. 해시까지 함께 바꾼 위조는 막지 못한다.

## 7. 모듈, 조립, 테스트 분리

| 개념 | 위치 |
|---|---|
| Contract Metadata, Raw Snapshot manifest, Settlement Event, 품질·PIT·Series 결과 타입 | `lab/domain/market_data.py` |
| PIT 조회, 최신 최종가·As-of Series | `lab/marketdata/settlements.py` (순수) |
| 품질 검사, 메타데이터 비교 | `lab/marketdata/quality.py` (순수) |
| Raw Snapshot 보관·검증 | `lab/adapters/raw_snapshot.py` |
| Provider Adapter (Databento statistics CSV) | `lab/adapters/databento_statistics.py` |
| Research Data Export, 처리 manifest, 실행 기록 | `lab/adapters/settlement_export.py` |

- 조립(Snapshot 읽기 → 번역 → 품질·PIT → 내보내기)은 호출부가 한다. 조립 계층 `lab.app`의 분류와 위치는 미승인이라 만들지 않았다
  (ADR-0010 Q10-4·Q10-5). 지금은 테스트가 조립한다.
- 합성 fixture 테스트는 `tests/lab/test_lab_market_data.py`. 합성 데이터는 `DataOrigin.SYNTHETIC`이며 품질 보고서에서 실데이터 판정을 막는다.
- 실데이터 통합 테스트는 `tests/lab/test_lab_market_data_real.py`이며 환경 변수 `CARVER_P1_01_REAL_DATA_CONFIG`가 저장소 밖 설정 파일을
  가리킬 때만 실행된다 (기본 실행에서는 skip). 원본은 저장소 밖에서 받아 `store_raw_snapshot`(`data_origin=REAL`)으로 보관하고, 설정
  파일에는 Snapshot 위치·ID, MESU6 instrument ID와 그 출처, (있으면) CME 거래일 달력을 둔다. API 키는 어디에도 두지 않는다.

## 8. 미결정 사항 [OPEN]

- 연구용 PIT에서 공급자 수집 시각(`VENDOR_CAPTURE`)을 이용 가능 근거로 인정할지, 지연 가정과 함께 쓸지 (ADR-0004 Q4-3, P0-03A D3A-13).
- MES 정산 tick·반올림 규칙, 거래소 휴장 달력과 반일장, 데이터 vintage 보관 방식 (ADR-0004 Q4-4, ADR-0011 Q11-8), 타임존 데이터 의존성 (Q10-7).
- 원본 데이터의 저장 위치와 라이선스상 저장소 포함 여부 (공급자 약관 미확인).
- Databento CSV 열 구성 (§3, INFERRED): 실제 파일로 확인하기 전이다. 열 집합이 다르면 Adapter가 SCHEMA_COLUMNS로 차단한다.
- 결측 거래일 허용 정도: 지금은 결측을 경고로만 보고하고, 완료 판정은 최소 유효 거래일 수(20)만 본다. 7~8월 약 43 거래일 가운데 몇 일까지
  결측을 허용할지는 정하지 않았다.
- 나노초를 마이크로초로 올리면 1µs 안의 서로 다른 기록이 같은 시각이 되어 AMBIGUOUS가 될 수 있다 (fail closed. 원래 나노초는 레코드 ID에 남음).
- 실제 CME 데이터에서 최종가 뒤 잠정가, 수집·거래소 순서 반대가 생기는지 (지금은 차단·AMBIGUOUS로 처리).
