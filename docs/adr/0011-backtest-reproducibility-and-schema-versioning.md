# ADR-0011: 백테스트 재현성과 schema version (Backtest Reproducibility and Schema Versioning)

## 1. Title

V1 golden master, fingerprint 보존 정책, 새 시스템의 버전 있는 입력·결과 schema와 실행 manifest (결정 ID D-11)

## 2. Status

**ACCEPTED** (2026-10-16)

| 항목 | 내용 |
|---|---|
| 승인일 | 2026-10-16 |
| 승인 주체 | 프로젝트 사용자 |
| 승인 근거 | 사용자의 명시적 승인 (작업 P0-02C2-FINAL, P0-02C2-R1 검토 후) |
| 승인 범위 | **핵심 아키텍처 설계 원칙만** (아래 "승인된 원칙"). §6의 제목 "Proposed Decision"은 ADR 서식의 이름이며, 그 가운데 아래 원칙이 승인된 결정이다. §6 안의 세부 규칙은 아래 "규칙별 승인 상태" 표를 따른다 |
| 제외 범위 | 아래 "승인되지 않은 사항"과 §11의 Open Questions 전부 (Q11-1~Q11-11), 구체 구현 규칙, 운영 기본값, 코드 구현 |
| 구현 상태 | **미구현.** |
| 인수 테스트 | **명세만 존재, 미구현** (§10, AT-0011-1~9) |
| 의미 | 문서 수준의 설계 원칙 승인이다. 코드 구현, 의존성 추가, 테스트 작성, 금융 계산 검증, Paper/Live 준비를 허가하거나 완료했다는 뜻이 아니다 |
| 변경 규칙 | 핵심 결정을 바꾸려면 새 ADR로 대체한다 (`SUPERSEDED by NNNN`). 오탈자, 링크, 명백한 문서 오류만 직접 고친다. 기존 ACCEPTED ADR과 충돌하는 변경은 별도 결정과 승인이 필요하다 |

**승인된 원칙**

1. V1 구조 변경에 앞서 golden master로 현재 결과를 고정한다 (ADR-0005 승인 원칙 6과 같음, §6.3).
2. V1의 기존 인코더, payload, schema version, fingerprint 계산을 바꾸지 않는다 (FP-1~FP-4).
3. golden master는 날짜, 월물별 체결 다리, 위험 예산처럼 V1 결과 fingerprint에 없는 값도 따로 보존할 수 있어야 한다 (§6.3).
4. 새 시스템은 별도의 버전 있는 입력·출력 schema, 인코더, 실행 manifest를 쓴다 (FP-5, FP-16).
5. 새 fingerprint는 V1 fingerprint와 영역과 형식이 구별되어야 한다 (FP-6, FP-7, FP-17).
6. 실제 계산에 쓴 데이터 내용이 입력 fingerprint에 반영되어야 한다 (FP-11, FP-19의 원칙 부분).
7. 코드 버전, 데이터 버전, 실행 환경, 타임존 데이터 버전을 추적할 수 있어야 한다 (FP-12, FP-14, FP-15).
8. 관측 시각, 데이터 이용 가능 시각, 데이터 수정 이력을 구분한다 (FP-13, ADR-0004 §6.5).
9. Golden Regression, Financial Integrity Validation, Differential Testing은 서로 다른 검증이다 (§6.2).
10. golden master 통과를 금융 계산의 정확성 증명으로 취급하지 않는다 (§6.2, 아래 "golden master의 의미").
11. golden 파일은 테스트 실행 중 자동 갱신하지 않는다 (§6.3, §6.7).
12. golden 변경에는 별도 승인과 변경 이력이 필요하다 (§6.7, FP-4).

**Q11-9와의 관계**: 승인 원칙 2와 4는 ADR-0001 Q1-9의 권장 답과 같은 방향의 원칙이다. 다만 Q1-9(타입·payload 설계)의 공식적인 종결은 P0-03에서 하며, 그때까지 Q11-9는 열려 있다.

**golden master의 의미**: golden master는 기존 V1 결과를 고정하는 회귀 기준이며, 그 결과의 금융적 정답 여부를 증명하지 않는다. 롤일 손익과 기존 V1 결함(F-02, A-05 등)은 P0-04 독립 검증 대상이다.

**입력 fingerprint, 실행 manifest, 데이터 vintage의 구분 (R1, 승인 원칙 6~8)**

- 입력 fingerprint: 실제 계산에 쓴 데이터 내용(`content_hash`)과 계산 가정·설정의 식별
- 실행 manifest: 코드, 환경, 타임존 데이터, 데이터 출처·`dataset_id`·vintage 등 추적 정보
- 데이터 vintage: point-in-time 무결성과 공급자 수정 이력
- 같은 가격 레코드 내용이라고 해서 그 데이터가 모든 과거 의사결정 시각에 이용 가능했다고 판단하지 않는다. 이용 가능 여부는 레코드의 `data_available_at`과 `decision_at`의 비교로 정한다 (ACCEPTED ADR-0001 I-1). `content_hash`가 같다는 것은 내용의 동일성일 뿐 시점 적합성의 근거가 아니다.

**규칙별 승인 상태** (§6.5의 FP-1~FP-19. 원문은 바꾸지 않았다)

| 규칙 | 상태 |
|---|---|
| FP-1, FP-2, FP-3, FP-4 | 원칙 승인 (원칙 2, 12). FP-2는 ACCEPTED ADR-0004 P-1과 같음 |
| FP-5, FP-16, FP-17 | 원칙 승인 (원칙 4, 5) |
| FP-6, FP-7 | V1과 영역·형식을 구별한다는 원칙만 승인 (원칙 5). 봉투 구성과 `lab-…/N:sha256:` 형식은 제안 |
| FP-8, FP-18 | 제안 (구체 인코더 규칙, 미승인) |
| FP-9 | 미승인 (수치 직렬화, Decimal, `-0.0`. Q11-6) |
| FP-10 | UTC aware 시각을 쓴다는 원칙은 ACCEPTED ADR-0007 C7-1과 같음. 고정 문자열 형식은 제안 |
| FP-11, FP-12, FP-13, FP-14, FP-15 | 원칙 승인 (원칙 6~8). 코드 버전 자동 수집과 미커밋 변경 처리(Q11-7), vintage 저장 구조(Q11-8, ADR-0004 Q4-4)는 미승인 |
| FP-19 | 데이터 내용을 입력 fingerprint에 반영한다는 원칙만 승인 (원칙 6). canonicalization과 원본 바이트와의 관계는 미승인 (Q11-11) |

**승인되지 않은 사항 (Open Questions로 유지)**

| 사항 | 관련 질문 |
|---|---|
| golden 저장 형식 (권장안은 별도 canonical JSON 파일) | Q11-1, ADR-0005 Q5-4 |
| golden fixture의 최종 목록, 개수, 우선순위 | Q11-2, ADR-0005 Q5-4 |
| 환경 간 부동소수점 차이의 허용 오차 | Q11-3 |
| golden 갱신 명령과 승인 기록 형식의 세부 사항 | Q11-4 |
| golden 테스트 구현 시점과 작업 범위 | Q11-5, ADR-0005 Q5-9 |
| 새 인코더의 Decimal, `-0.0`, 숫자 직렬화 규칙 | Q11-6 |
| 코드 버전 자동 수집과 미커밋 변경(dirty working tree) 처리 | Q11-7 |
| 데이터 vintage의 실제 저장 구조, 데이터 지연 가정 기록 | Q11-8, ADR-0004 Q4-3, Q4-4 |
| ADR-0001 Q1-9의 최종 답 | Q11-9 |
| 주문·체결·NAV 기록의 저장소 구현 | Q11-10, ADR-0009 Q9-9 |
| 데이터 내용 해시의 최종 canonicalization과 원본 파일 바이트와의 관계 | Q11-11 |
| V1·새 엔진 차등 비교의 허용 오차 | ADR-0005 Q5-6 |


- 작성일: 2026-10-16 (작업 P0-02C2)
- 기준 커밋: `a02aede` (`python -m pytest -q -W error` → 306 passed, 경고 0)
- 관련 P0-01 항목: GAP `A-09`, `A-11`, `F-10`. [V1_DEPENDENCY_ANALYSIS.md](../architecture/V1_DEPENDENCY_ANALYSIS.md) §5 D-11
- 관련 ADR (모두 ACCEPTED): [0001](0001-execution-timing-and-valuation.md) (§8.0 `V1_COMPAT`, Q1-9 fingerprint 보존 방법), [0004](0004-market-data-and-domain-boundaries.md) (§3.5 fingerprint 동작, P-1~P-6, Q4-3, Q4-4), [0005](0005-backtest-paths-and-v1-compatibility.md) (Stage 0 golden 원칙, AT-0005-1, AT-0005-3, Q5-4, Q5-6, Q5-9), [0007](0007-multi-market-calendar-and-valuation.md) (IANA 타임존), [0008](0008-multi-currency-fx-accounting.md) (NAV 기록), [0009](0009-order-fill-and-position-lifecycle.md) (이벤트 기록, Q9-9)
- **이미 승인된 것 (ADR-0005 승인 원칙 6)**: 기존 V1을 구조적으로 바꾸기 전에 V1의 결과, 입력 fingerprint, 결과 fingerprint를 golden master로 고정한다.
- **승인되지 않은 것 (이 ADR도 확정하지 않음)**: golden fixture의 최종 저장 형식, 정확한 fixture 목록과 개수 (ADR-0005 Q5-4), 테스트 추가 작업의 구체적 시점 (Q5-9), snapshot 갱신 절차의 세부 형식, 차등 비교의 허용 오차 (Q5-6). P0-02C2-FINAL 승인 뒤에도 이 항목들의 권장안은 **제안**으로 남는다 (위 표).
- **이 ADR은 golden 테스트를 작성하지 않는다.** 새 인코더, manifest, schema도 모두 **PLANNED**다.

## 3. Context

### 3.1 V1 재현성 구성 요소 (CONFIRMED)

| 구성 요소 | 내용 | 근거 |
|---|---|---|
| schema version 상수 | `BACKTEST_MANIFEST_SCHEMA_VERSION = 1`, `BACKTEST_INPUT_SCHEMA_VERSION = 1`, `BACKTEST_RESULT_SCHEMA_VERSION = 1` | `backtest_manifest.py:30-31`, `backtest_result_bundle.py:18` |
| canonical JSON | `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` | `backtest_manifest.py:385-403` |
| 값 변환 | `None`, `bool`(int보다 먼저), `str`, `int`, 유한한 `float`(비유한값은 ValueError), `date` → `isoformat()`, dataclass → **필드 이름과 값의 dict**(클래스 이름 없음), 문자열 키 Mapping, list·tuple → 배열. 그 밖의 타입은 TypeError | `backtest_manifest.py:303-383` |
| 입력 payload | `input_schema_version`, `initial_account_value`, `account_base_currency`(공백 제거·대문자), `portfolio`(정렬한 가중치, IDM), `config`(`BacktestConfig` 전체), 상품별 `instrument_spec`, `prices`, `initial_contract`, `roll_events`, `execution_days`. EWMAC span 등은 `BacktestConfig`가 기준이라 상품 입력에서 뺀다 | `backtest_manifest.py:519-631` (같은 함수가 `:405-517`에도 있고 뒤 정의가 덮어씀, GAP A-11) |
| 입력 fingerprint | canonical JSON을 UTF-8로 인코딩한 SHA-256 16진수 64자 | `backtest_manifest.py:633-669` |
| manifest | schema version, 입력 fingerprint, 계좌, 가중치, IDM, config, 상품별 데이터 범위(시작·끝 날짜, 개수, 월물 목록) | `backtest_manifest.py:48-101, 217-301` |
| 결과 payload | `result_schema_version`과 일별 `opening_account_value`, `closing_account_value`, `gross_pnl`, `trading_cost`, `net_pnl`, 상품별 `gross_pnl`, `trading_cost`, `net_pnl`, `target_position`, `directional_trade`, `contract_positions` | `backtest_result_bundle.py:57-170` |
| 결과 fingerprint | 결과 payload의 canonical JSON SHA-256 | `backtest_result_bundle.py:172-191` |
| 결과 번들 | `result_schema_version`, `code_version`(호출자가 넘기는 문자열, 비어 있으면 ValueError), manifest, 성과 요약, 최종 계좌, 결과 fingerprint | `backtest_result_bundle.py:27-55, 192-246` |

**결과 fingerprint에 들어가지 않는 것** (CONFIRMED: payload 코드에 없음, GAP A-09):

- 날짜 (`PortfolioBacktestDayResult.date`는 있지만 payload에 넣지 않음)
- 월물별 체결 다리(`RollExecution`: 월물, 수량, 체결가, 다리별 비용), `active_contract`, `new_instrument_position`
- 계좌·상품 위험 예산(`account_daily_cash_vol_target`, `instrument_cash_vol_targets`), `risk_snapshot`
- 신호(vol, forecast), 성과 요약 (번들에는 있지만 결과 fingerprint 밖)
- `code_version` (번들 필드이며 fingerprint 밖)

이 값들은 V1 결과 객체(`PortfolioBacktestDayResult` `portfolio_backtest.py:40-65`, `ContractAwareDailyStepResult` `contract_aware_daily_step.py:29-43`, `RollExecution` `roll_execution.py:22-26`)에는 **있다.** 따라서 golden은 V1 fingerprint payload를 바꾸지 않고도 이 값들을 따로 기록할 수 있다 (§6.3).

### 3.2 canonical JSON의 경계 동작 (probe, 2026-10-16)

V1 `to_canonical_json`을 저장소 밖 스크립트로 직접 호출해 확인했다 (CONFIRMED).

| 입력 | 출력 | 의미 |
|---|---|---|
| 필드 `x`, `y`가 같은 서로 다른 dataclass `A(1.5, 2)`, `B(1.5, 2)` | 둘 다 `{"x":1.5,"y":2}` | 타입이 달라도 같은 해시. 타입을 옮겨도 해시가 같은 이유다 (ADR-0004 §3.5) |
| 필드 순서만 다른 dataclass | 같음 | 키 정렬 때문 |
| 기본값이 있는 필드 `z=0` 추가 | `{"x":1.5,"y":2,"z":0}` | 필드 추가는 기본값이 있어도 해시를 바꾼다 (ADR-0004 §3.5 probe: `4c8483d1…` → `5b776aea…`) |
| `{"v": 1}` 대 `{"v": 1.0}` | `{"v":1}` 대 `{"v":1.0}` | 정수와 실수는 다른 해시 |
| `(1, 2)` 대 `[1, 2]` | 같음 | tuple과 list를 구분하지 않음 |
| `0.1 + 0.2`, `1e-7`, `1e16`, `-0.0`, `1/3` | `0.30000000000000004`, `1e-07`, `1e+16`, `-0.0`, `0.3333333333333333` | 가장 짧은 왕복 표현(repr). `-0.0`과 `0.0`은 다른 해시 |
| `date(2026,3,5)` | `"2026-03-05"` | |
| naive `datetime(2026,3,5,6,0)` | `"2026-03-05T06:00:00"` | `datetime`은 `date`의 하위 클래스라 받아들여진다. 시각과 타임존 표기가 붙는다 |
| aware `datetime(..., tzinfo=UTC)` | `"2026-03-05T06:00:00+00:00"` | naive와 다른 해시. 같은 순간을 다른 타임존으로 쓰면 또 다른 해시 |
| `{"통화": "원"}` | `{"통화":"원"}` | 비ASCII 그대로 |
| `NaN`, `Decimal("1.5")`, `{1: 2}`, `set` | ValueError, TypeError, ValueError, TypeError | 거부 |
| `str`을 상속한 Enum | `"KRW"` | 값 문자열로 직렬화 |

### 3.3 V1 재현성의 공백

| 공백 | 내용 | 근거 |
|---|---|---|
| golden 없음 | 테스트에 64자리 해시 리터럴이 0건이다. 최상위 진입점의 손익·포지션·비용·계좌 값을 고정하는 테스트도 없다 | ADR-0004 §3.5, ADR-0005 §3.3 (CONFIRMED) |
| 기존 fingerprint 테스트의 범위 | 순서 무관성, 입력이 바뀌면 값이 바뀜, 같은 실행은 같은 값, canonical 직렬화만 확인한다 (`tests/test_backtest_manifest.py:332-503`, `tests/test_backtest_result_bundle.py:147-321`) | CONFIRMED |
| **D 경로의 롤일** | V1 기준 진입점(D)과 시스템 경로(C)의 테스트는 모두 `roll_events=[]` 또는 `roll_to_contract=None`을 쓴다 (`tests/test_system_backtest.py:57, 132, 142, 221, 379`, `tests/test_portfolio_system_backtest.py:91`, `tests/test_combined_system_backtest.py:57`, `tests/test_portfolio_backtest.py:71, 500`, D 경로 최상위 수용 테스트도 `roll_events=[]`, `tests/test_v1_acceptance.py:133`). 러너 가운데에서는 B2 러너 테스트(`tests/test_contract_aware_backtest.py:34, 135, 173` 등)만 롤일을 지정한다 (스텝 단위 테스트 `test_contract_aware_daily_step.py`, `test_roll_aware_daily_step.py`도 롤을 다룬다). **D 경로로 롤일을 지나는 테스트는 없다** | CONFIRMED (grep) |
| `code_version` | 호출자가 넣는 임의 문자열. Git과 연동되지 않는다 | `backtest_result_bundle.py:41-55`, GAP A-09 |
| 데이터 버전 | 공급자, 수집 시각, 수정 이력(vintage)이 없다 | GAP F-10, ADR-0004 Q4-4 |
| 실행 환경 | Python, pandas, numpy 버전을 기록하지 않는다 | 코드 부재 |
| 타임존 데이터 | 검증된 환경(`.venv`)에 IANA 타임존 데이터가 없다. `ZoneInfo("America/New_York")`가 `ZoneInfoNotFoundError` | ADR-0010 §3.5 (CONFIRMED) |

### 3.4 검증된 환경 (CONFIRMED, 2026-10-16)

Python 3.14.6, Android aarch64, pandas 3.0.6, numpy 2.5.4, pytest 9.1.1, `carver-quant-lab` 0.1.0. 일반 Linux와 CI는 미검증이다 ([DEVELOPMENT_BASELINE.md](../architecture/DEVELOPMENT_BASELINE.md)). V1은 난수와 현재 시각 조회를 쓰지 않는다 (CLAUDE.md §4).

## 4. Decision Drivers

1. **V1 fingerprint 보호**: 기존 V1 fingerprint와 payload를 바꾸거나 새 형식으로 조용히 교체하지 않는다 (ADR-0001 §8.0, ADR-0004 P-1, P-3, ADR-0005 C5-4).
2. **결과 전체의 재현성**: 요약값이 아니라 일별 포지션, 체결, 비용, 손익, 계좌를 고정한다 (ADR-0005 Stage 0).
3. **세 검증의 분리**: golden은 회귀를 잡을 뿐 금융적 정답이 아니다 (ADR-0005 §6.7 golden의 한계).
4. **추적 가능성**: 코드 버전, 데이터 버전, 환경, 타임존 데이터 버전을 결과와 함께 남긴다.
5. **저장 형식의 안정성과 장기 감사**: 몇 년 뒤에도 같은 기록을 읽고 비교할 수 있어야 한다.
6. **유지 비용**: 개인 운영에서 golden 갱신이 일상 작업이 되면 안 된다. 갱신은 드물고 기록이 남아야 한다.
7. **미결정 사항 보존**: Q5-4, Q5-6, Q5-9, Q1-9를 이 ADR이 닫지 않는다.

## 5. Considered Options

### 5.1 대안 A — 기존 pytest 테스트에서 일부 결과 값만 고정

- **내용**: 기존 테스트 파일에 `approx(숫자)` 단언을 몇 개 더 넣거나, 해시 리터럴 몇 개를 고정한다.
- **장점**: 가장 빠르다. 새 파일 형식이 없다.
- **단점**: 고른 값 외의 변화(다른 날짜, 다른 월물 다리)를 놓친다. 무엇을 고정했는지 한눈에 보이지 않는다. 기존 테스트 파일을 수정하므로 테스트 수정 승인 대상이 된다 (CLAUDE.md §5). 환경·코드 버전을 남기지 않는다.

### 5.2 대안 B — 별도 golden fixture와 기대 결과 snapshot

- **내용**: 대표 시나리오마다 입력 fixture와 일별 결과 snapshot을 별도 파일(또는 별도 테스트 모듈)로 둔다. 테스트는 V1을 실행해 snapshot과 비교한다.
- **장점**: 결과 전체를 고정한다. 기존 테스트를 건드리지 않는다. 시나리오별 의미를 문서화할 수 있다.
- **단점**: snapshot 자체의 형식이 버전 관리되지 않으면 나중에 형식을 바꿀 때 혼란이 생긴다. 코드·데이터·환경 버전이 함께 남지 않으면 차이의 원인을 구분할 수 없다.

### 5.3 대안 C — 버전 있는 입력·출력 schema + 실행 manifest + golden fixture

- **내용**: B에 더해, (1) 새 시스템의 입력·결과·기록에 명시적 schema와 version을 붙이고, (2) 실행마다 코드·데이터·환경·타임존 데이터 버전을 담은 manifest를 남기며, (3) golden 기록 자체에도 version을 둔다.
- **장점**: 결과 차이가 생기면 코드 변경, 데이터 변경, 환경 차이, schema 변경 가운데 무엇 때문인지 구분할 수 있다. 장기 감사가 가능하다. Paper/Live 기록(ADR-0008 NAV, ADR-0009 이벤트)에도 같은 규칙을 쓸 수 있다.
- **단점**: 설계와 구현 비용이 가장 크다. 새 인코더와 V1 인코더가 공존한다.

### 5.4 비교

| 기준 | A (일부 값 고정) | B (golden snapshot) | C (schema + manifest + golden) |
|---|---|---|---|
| V1 fingerprint 보호 | 일부 (해시 리터럴을 넣는 경우만) | 높음 (입력·결과 fingerprint를 snapshot에 포함) | **높음** + 새 fingerprint와 구분 (§6.5) |
| 결과 전체 재현성 | 낮음 | 높음 | **높음** |
| 저장 형식 안정성 | 해당 없음 | 형식 버전이 없으면 낮음 | **높음** (golden schema version) |
| 코드 버전 추적 | 없음 | 선택 | **있음** (manifest) |
| 데이터 수정 이력 | 없음 | 없음 | **있음** (데이터 `content_hash`는 입력 fingerprint에, `dataset_id`·vintage는 실행 manifest에) |
| 환경·라이브러리 버전 | 없음 | 선택 | **있음** |
| 테스트 유지 비용 | 낮음 (그러나 기존 테스트 수정) | 중간 | 중간 (V1 golden 자체는 B와 같음. 새 schema 비용은 새 시스템 구현 때 발생) |
| 장기 감사 | 낮음 | 중간 | **높음** |

## 6. Proposed Decision

### 6.1 결정 요지

**C를 목표로 채택한다. V1 쪽은 V1 인코더와 V1 payload를 그대로 쓰는 golden(B 형태)으로 고정하고, 버전 있는 새 schema·새 인코더·실행 manifest는 새 시스템(`lab`, ADR-0010)에만 쓴다.** V1 fingerprint를 새 형식으로 바꾸지 않는다. 두 fingerprint는 이름, 문자열 형식, 해시 대상 바이트가 모두 달라 서로 혼동될 수 없게 한다 (§6.5).

- golden 테스트는 ADR-0005 승인 원칙 6의 **보호 장치**다. 이 ADR은 그 설계 권장안을 제시할 뿐, 저장 형식(Q5-4), fixture 목록(Q5-4), 작성 시점(Q5-9), 갱신 절차 형식(Q11-4)을 확정하지 않는다.
- ADR-0001 Q1-9(`V1_COMPAT`에서 기존 fingerprint를 보존하는 방법)에 대해 "V1 타입·payload 불변 + 새 입력은 별도 타입·payload·schema version"을 **권장 답**으로 제시한다 (ADR-0004 P-4와 같은 방향). Q1-9는 승인 전까지 열린 채로 둔다 (Q11-9).

### 6.2 세 검증의 구분

| 검증 | 묻는 질문 | 기준값 | 실패의 의미 | 다른 검증으로 대신할 수 없는 이유 | 위치 |
|---|---|---|---|---|---|
| **Regression / Golden** | 기존 코드의 결과가 바뀌었는가? | V1을 실행해 기록한 값 (승인된 기록) | 무언가 바뀌었다. 옳고 그름은 모른다 | golden은 기록한 경로(권장: D)의 V1 결함(F-02, A-05, F-06, F-11, F-04 등)까지 그대로 기록한다. D 경로를 지나지 않는 결함(A-04, F-13, F-14)은 D golden에 나타나지 않는다. 통과해도 금융적으로 옳다는 뜻이 아니다 | ADR-0005 Stage 0 (이 ADR §6.3) |
| **Financial Integrity** | 계산이 금융적으로 올바른가? | 구현과 독립인 손계산·별도 스크립트 (CLAUDE.md §3.2) | 공식이나 구현이 틀렸다 | 독립 계산은 대표 사례만 다룬다. 코드가 바뀌지 않았다는 보장은 못 한다 | P0-04, 각 ADR의 숫자 예제 |
| **Differential** | `V1_COMPAT` 모드의 새 엔진이 V1 경로와 같은 결과를 내는가? | 같은 입력으로 실행한 V1 결과 | 새 엔진이 V1을 재현하지 못한다 | 두 구현이 같은 결함을 공유해도 통과한다. V1 자체의 변화는 잡지 못한다 (V1이 기준이므로) | ADR-0005 AT-0005-3 |

- **golden 값을 금융적 정답으로 취급하지 않는다.** golden과 독립 계산이 다르면 golden을 조용히 고치지 않는다. 원인과 처리 방법을 별도로 승인받는다 (ADR-0005 §6.7).
- 세 검증은 서로 다른 실패를 잡는다. AT-0011-8이 세 검증이 서로를 대신하지 못하는 사례를 명세한다.

### 6.3 V1 golden master 설계 (제안)

**기록 단위**: 시나리오 하나당 golden 기록 하나. 아래는 **논리 구조**다. 파일 형식과 배치는 Q5-4 / Q11-1로 남긴다.

| 묶음 | 필드 | 출처 |
|---|---|---|
| 식별 | `golden_schema_version`, V1 schema version 3종(`BACKTEST_MANIFEST_SCHEMA_VERSION`, `BACKTEST_INPUT_SCHEMA_VERSION`, `BACKTEST_RESULT_SCHEMA_VERSION`, 현재 모두 1), 시나리오 ID, 설명, 재현하는 V1 결함·가정 목록 (§6.4) | golden 작성자, V1 상수 |
| 입력 | 입력 fixture 참조(fixture ID + 내용 해시) 또는 입력 자체, V1 **입력 fingerprint** (`calculate_backtest_input_fingerprint`) | V1 함수 |
| V1 기록 | V1 manifest의 canonical 문자열 (`serialize_backtest_manifest`), V1 **결과 fingerprint** (`calculate_backtest_result_fingerprint`) | V1 함수 |
| 일별 계좌 | 날짜, 개장 계좌, 계좌 일간 위험 예산, gross·비용·net PnL, 종가 계좌, `risk_snapshot` (gross 명목, gross leverage, 증거금 요구량, 증거금 사용률) | `PortfolioBacktestDayResult` |
| 일별 상품 | 상품 위험 예산, 목표 포지션, 방향성 거래량, 상품 포지션, 활성 월물, 월물별 포지션, 상품 gross·비용·net PnL | `instrument_results[s]` (`ContractAwareDailyStepResult`) |
| 일별 체결 | 체결 다리마다 월물, 수량, 체결가, 다리별 비용 (롤일에는 구월물·신월물 두 다리) | `RollExecution` |
| 요약 | `PerformanceSummary` 9개 필드, 최종 계좌 | `summarise_portfolio_performance`, 번들 |
| 예상 예외 | 예외로 끝나는 시나리오(가드레일 위반)에서는 예외 타입과 메시지 | V1 실행 |
| 출처 기록 | V1 코드 버전(Git 커밋 전체 해시, 작업 트리 변경 여부), 실행 환경(Python 구현·버전, 플랫폼·아키텍처, pandas·numpy·pytest 버전, 패키지 버전), 기록 시각, 기록 승인(누가, 언제, 왜) | 기록 도구 (`lab.v1_bridge`, ADR-0010) |

- **V1 fingerprint payload를 바꾸지 않는다.** 날짜, 체결 다리, 위험 예산처럼 V1 결과 fingerprint에 없는 값(§3.1)은 golden 기록 도구가 V1 결과 객체에서 **따로 꺼내** 기록한다. V1 `build_backtest_result_payload`에 필드를 추가하지 않는다 (ADR-0004 P-3).
- **비교 규칙**:
  - 정수(포지션, 거래량, 월물별 포지션)는 정확히 같아야 한다.
  - 실수(체결가, 비용, PnL, 계좌, 위험 예산)는 ACCEPTED ADR-0005 AT-0005-1의 기대 결과대로 **같은 환경에서는 정확히 같아야 한다** (연산 경로가 같으므로). Python의 `float` repr은 왕복 시 같은 binary64 값을 돌려주므로(언어 보장), repr 문자열로 저장하면 정확 비교가 가능하다.
  - **다른 환경**(다른 CPU 아키텍처, numpy·pandas 버전)에서 실수가 마지막 자리에서 달라질 수 있는지는 확인하지 않았다 (UNVERIFIED). 환경이 다르고 값이 다르면 자동으로 허용 오차를 적용하지 않고 "환경 차이" 상태로 보고해 사람이 판단한다 (§6.6). 환경 간 허용 오차 정책은 Q11-3이다.
  - 차등 비교(AT-0005-3)의 허용 오차는 Q5-6 그대로 미결정이다. 이 ADR은 정하지 않는다.
- **저장 형식 (권장안, 미확정 Q5-4)**: 테스트 코드 리터럴보다 **별도 canonical JSON 파일**을 권장한다. 이유: (1) 일별 결과는 크기가 커서 코드 리터럴로 읽기 어렵고, (2) 파일 단위 내용 해시로 무단 변경을 검출할 수 있으며 (§6.7), (3) `golden_schema_version`으로 형식 변경을 관리할 수 있다. golden 파일은 V1 `to_canonical_json`이 아닌 golden 전용 직렬화 규칙(정렬된 키, 실수는 repr)으로 쓰되, 그 안에 V1 fingerprint 문자열을 그대로 담는다.
- **pytest는 golden을 쓰지 않는다.** golden 파일 생성·갱신은 별도 명령으로만 한다. 테스트 실행이 기대값을 자동으로 갱신하는 방식(snapshot 자동 갱신)은 쓰지 않는다.

### 6.4 대표 시나리오 후보 (Q5-4 미결정, 목록과 개수는 확정하지 않음)

모든 시나리오는 V1 기준 진입점 `run_combined_ewmac_portfolio_backtest`(경로 D)로 실행하는 것을 권장한다 (ADR-0005 승인 원칙 1). 단일 상품도 "상품 하나짜리 포트폴리오"로 실행할 수 있는지는 구현 시 확인한다 (INFERRED, ADR-0005 Q5-7).

| # | 시나리오 | 재현하는 V1 결함·가정 | 기존 테스트에서 비슷한 입력 | 주의 |
|---|---|---|---|---|
| G-1 | 단일 선물 | 체결가 mid 기준 비용과 adjusted 종가 평가 (F-02, ADR-0001 V1 회계), 항상 전량 체결·새 포지션 = 목표 (A-07, F-08), 계약당 수수료만 (F-05), t−1 신호 정렬, PIT 신호 | `tests/test_system_backtest.py:164` (`test_price_to_account_end_to_end`) | 경로 C 테스트다. D로 같은 입력을 실행해야 한다 |
| G-2 | 롤이 있는 선물 | 하루 전량 롤 (F-07), 롤 이벤트는 입력값, 가산 back-adjustment의 gap과 롤일 손익 (P0-04 V-06), ADR-0001 C-2(롤일 동치성)의 기준값 | 러너 가운데 롤일은 B2 러너 테스트에만 있음 (`tests/test_contract_aware_backtest.py:119`). 스텝 단위 롤 테스트도 있음 | **D 경로로 롤일을 지나는 첫 고정 기록이 된다** (§3.3). 롤일 손익이 옳은지는 golden이 말해 주지 않는다 (P0-04) |
| G-3 | 복수 선물 포트폴리오 | 상품 간 날짜 정확 일치 요구 (A-06), IDM 상한 없음과 고정 가중치 (A-15), 계좌 합산 | `tests/test_portfolio_system_backtest.py:95`, `tests/test_v1_acceptance.py:138` | 상품 순서 무관성은 기존 테스트가 이미 확인 (`:202`) |
| G-4 | KRW 기준통화와 USD 상품 | 상품·날짜별 스칼라 `fx_to_base` 하나를 손익·사이징·비용·위험에 겸용 (F-06), 외화 현금 없음·환산 손익 없음 (P0-02C1 N-1), 수수료 통화 = 상품 통화 (ADR-0001 Q1-4 잠정 가정) | `tests/test_v1_acceptance.py` (fx 1,350), `tests/test_contract_aware_backtest.py:1244, 1621` | 환율이 날마다 바뀌는 날을 포함해야 F-06의 영향이 기록된다 |
| G-5 | bid-ask spread와 slippage | mid 대비 체결가 비용, 정수 tick 슬리피지 (기본값 0은 낙관적, F-05) | `tests/test_contract_aware_backtest.py:778, 847`, `tests/test_v1_acceptance.py` (1 tick) | 슬리피지 0과 1 tick을 모두 두면 비용 차이를 볼 수 있다 |
| G-6 | Buffering | V1 버퍼링 규칙 (`buffering.py`) | `tests/test_portfolio_backtest.py:476` | 버퍼 경계에서 거래가 생기고 안 생기는 날을 포함 |
| G-7 | Legacy risk budget | 호출자가 위험 예산을 공급 (F-11, look-ahead 가능), 계좌가 0 이하여도 진행 (F-12), `daily_cash_vol_target`이 계좌 수준으로 해석됨 (ADR-0004 §3.3) | `tests/test_portfolio_backtest.py` (legacy 모드 테스트) | 차등 비교 때 변환기에 수준 "계좌"를 명시해야 한다 (ADR-0004 AT-0004-4) |
| G-8 | Dynamic risk budget | 전일 종가 계좌로 위험 예산 계산, `daily_cash_vol_target`은 쓰지 않지만 검증은 함 | `tests/test_portfolio_system_backtest.py:312, 393` | 일별 위험 예산 값을 golden에 함께 기록 |
| G-9 | Risk Guardrail | 거래 후 사후 검사, 위반 시 ValueError로 백테스트 중단 (F-04, ADR-0003 §8의 호환 모드 A) | `tests/test_portfolio_backtest.py:646, 737, 791` | (a) 한도 안: 일별 `risk_snapshot` 기록. (b) 한도 위반: 예외 타입·메시지 기록. 결과가 없으므로 결과 fingerprint도 없다 |
| G-10 | Warm-up 경계 | 표본 2~3개로 vol 추정 (F-01), forecast가 없는 날 건너뛰기와 그때의 보유분 손익 누락 가능성 (A-05) | `tests/test_research_pipeline.py:60-84`, ADR-0002 AT-0002-1 (V1 실행값: index 2에서 vol 0.035355, 목표 59계약) | 첫 거래일 전후를 포함. 손익 누락이 실제로 생기는 입력이면 golden이 결함을 그대로 고정한다는 점을 기록 |

### 6.5 Fingerprint 보존 정책

**V1 쪽 (그대로 둔다)**

| ID | 정책 |
|---|---|
| FP-1 | V1 `to_canonical_json`, `build_backtest_input_payload`, `build_backtest_result_payload`, `calculate_*_fingerprint`, schema version 상수 1을 바꾸지 않는다 (ADR-0004 P-3). 중복 정의(A-11)를 정리하는 것도 V1 수정이므로 golden 이후 별도 승인 |
| FP-2 | V1 타입의 필드 이름·기본값·순서를 바꾸지 않고 필드를 추가하지 않는다. ADR-0004 P-1(잠정 규칙)을 그대로 따른다. §3.2처럼 기본값이 있는 필드 하나만 추가해도 해시가 바뀐다 |
| FP-3 | V1 필드 이름(`BacktestManifest.input_fingerprint_sha256`, `BacktestResultBundle.result_fingerprint_sha256`)과 값 형식(16진수 64자)을 바꾸지 않는다. V1 `code_version`은 호출자 문자열 그대로다 |
| FP-4 | golden이 V1 입력·결과 fingerprint를 **문자 단위로** 고정한다. 값이 바뀌면 바뀐 이유와 이전·이후 값을 기록하고 승인받는다 (ADR-0005 AT-0005-1 예외조건) |

**새 시스템 쪽 (`lab.analysis`, PLANNED)**

| ID | 정책 | 이유 |
|---|---|---|
| FP-5 | 새 시스템은 **별도 인코더**를 쓴다. V1 인코더를 재사용하거나 확장하지 않는다 | V1 인코더를 고치면 V1 해시가 바뀐다 |
| FP-6 | **영역 분리(domain separation)**: 해시 대상은 `{"fingerprint_kind": …, "schema": …, "schema_version": …, "payload": …}` 봉투의 canonical 바이트다. 같은 payload라도 V1 해시 대상과 바이트가 다르다 | V1과 새 해시의 우연한 일치·혼동 방지 |
| FP-7 | 새 fingerprint는 **접두사가 붙은 문자열**로 쓴다. 예: `lab-input/1:sha256:<64자>`. 접두사 없는 64자 16진수는 V1 형식으로만 쓴다. 새 기록의 필드 이름도 V1과 다르게 한다 (예: `input_fingerprint`) | 사람과 도구가 형식만 보고 구분 |
| FP-8 | 기록 타입에 **schema 이름 태그**를 넣는다 (Python 클래스 경로가 아닌 schema 수준 이름과 버전) | §3.2의 "필드가 같은 서로 다른 타입이 같은 해시" 문제 방지. 모듈 이동으로 해시가 바뀌지 않게 클래스 경로는 쓰지 않음 |
| FP-9 | **수치 표현**: schema가 필드마다 정수/실수를 정한다. `bool`을 정수로 받지 않는다. 비유한 실수는 거부한다. `-0.0`의 정규화 여부와 금액에 Decimal을 쓸지는 미결정 (Q11-6, P0-03) | §3.2: `1` 대 `1.0`, `-0.0` 대 `0.0`이 다른 해시 |
| FP-10 | **시각 표현**: 시각 필드는 타임존이 있는 UTC로만 받고 고정 형식(예: `YYYY-MM-DDTHH:MM:SS.ffffffZ`)으로 쓴다. naive datetime은 거부한다. 날짜만 있는 필드(거래일 라벨)는 schema가 날짜로 선언한 곳에서만 쓴다 | §3.2: naive/aware, 타임존 표기에 따라 해시가 달라짐. ADR-0007 C7-1 |
| FP-11 | **입력 / 결과 / 실행 manifest를 분리**한다 (R1). 입력 fingerprint는 계산이 실제로 본 것을 덮는다: 입력 데이터마다의 **내용 해시**(`content_hash`, FP-19), 체결 가정, 정책 프로필, 설정. 데이터셋의 논리 식별자(`dataset_id`), 저장 위치(파일 경로 등), vintage 표기는 입력 fingerprint에 넣지 않고 실행 manifest에 둔다. 결과 fingerprint는 결과만 덮는다. 코드 버전, 환경, 실행 시각도 실행 manifest에 두고 두 fingerprint에 넣지 않는다. 책임 분리는 아래 "입력 fingerprint, 실행 manifest, 데이터 vintage 기록의 책임" 표 | 데이터 내용이 바뀌면 입력 fingerprint가 바뀌어야 하고(AT-0011-9), 같은 입력에서 코드가 바뀌면 입력 fingerprint는 같고 결과 fingerprint만 달라져야 원인을 구분할 수 있다 (AT-0011-7) |
| FP-12 | **코드 버전, 데이터 식별, 데이터 내용을 구분**한다 (R1). 코드 버전 = Git 커밋 전체 해시 + 작업 트리 변경 여부 + 패키지 버전 (실행 manifest). 데이터 식별 = 데이터셋별 공급자, `dataset_id`(논리 식별자), vintage(기준 시점), 저장 위치, 파서 버전 (실행 manifest). 데이터 내용 = 실제로 쓴 레코드의 `content_hash` (입력 fingerprint). **`dataset_id`는 내용이 바뀌어도 같을 수 있으므로 데이터 변경을 감지하는 근거로 쓰지 않는다.** 수집과 해시 계산은 `lab.app`·데이터 계층이 하고 코어에 넘긴다 (코어는 I/O를 하지 않음, ADR-0010 PK-3) | GAP A-09, F-10 |
| FP-13 | **공급자 수정 이력**: 수정값은 덮어쓰지 않고 새 `data_available_at`을 가진 별도 관측으로 보관한다 (ADR-0004 §6.5). 실행은 vintage 하나에 묶이고, vintage가 고른 레코드 집합으로 `content_hash`를 계산한다. 공급자가 같은 날짜의 과거 가격을 고쳐 고른 레코드가 달라지면 `content_hash`와 입력 fingerprint가 모두 달라진다. vintage가 달라도 고른 레코드가 같으면 둘 다 같고, vintage 차이는 실행 manifest에 기록된다. 보관 방식은 ADR-0004 Q4-4 | 같은 날짜의 값이 나중에 바뀌어도 과거 실행을 재현하고, 수정을 놓치지 않음 (AT-0011-9) |
| FP-14 | **타임존 데이터 버전**: 달력·타임존 변환을 쓴 실행은 타임존 데이터 출처와 버전을 manifest에 기록한다. 검증된 환경에는 타임존 데이터가 없으므로 의존성 결정이 먼저다 (ADR-0010 Q10-7) | ADR-0007. DST 규칙 개정이 과거 시각 변환을 바꿀 수 있음 |
| FP-15 | **실행 환경**: Python 구현·버전, 플랫폼·아키텍처, pandas·numpy 버전, 패키지 버전을 manifest에 기록한다. 환경은 fingerprint에 넣지 않고 재현성 판정(§6.6)에 쓴다 | 환경 차이를 결과 차이와 구분 |
| FP-16 | **schema version 올림 규칙**: payload 모양, 필드 추가·삭제·이름 변경, 인코더 규칙, 수치·시각 표현 규칙이 바뀌면 version을 올린다. 이전 version의 기록은 다시 쓰지 않고 그대로 읽을 수 있게 둔다 | 조용한 의미 변경 방지 |
| FP-17 | **V1 재현 실행에서의 기록**: 새 엔진을 `V1_COMPAT`로 실행할 때 V1 입력이 있으면 `lab.v1_bridge`가 V1 함수로 계산한 V1 fingerprint를 별도 필드(예: `v1_input_fingerprint_sha256`)에 그대로 담는다. 새 fingerprint로 바꿔 부르지 않는다 | "기존 V1 fingerprint를 새 형식으로 조용히 교체하지 않는다" |
| FP-18 | **배열과 컬렉션의 순서**: schema가 배열마다 **순서가 의미 있는 시퀀스**(예: 일별 기록, 이벤트 기록, 체결 다리)인지 **순서가 없는 집합**(예: 상품 목록, 월물별 포지션)인지 선언한다. 집합은 선언된 키로 정렬해 직렬화하고, 같은 키가 두 번 나오면 거부한다. 시퀀스는 받은 순서를 그대로 쓰고 순서 규칙(예: 시각 오름차순)을 schema에 적는다. 매핑의 키는 V1과 같이 정렬한다 | V1은 tuple과 list를 구분하지 않고 배열 순서를 그대로 해시한다 (§3.2). 순서 의미를 정하지 않으면 같은 내용이 다른 해시를 갖거나, 순서가 중요한 기록의 재배열을 놓친다 |
| FP-19 | **`content_hash`의 정의 (제안, R1)**: 실행이 실제로 사용한 레코드(vintage와 기간으로 고른 뒤의 집합)를 새 인코더 규칙(FP-6~FP-10, FP-18: 선언된 키로 정렬)으로 직렬화한 바이트의 SHA-256이다. 레코드의 관측 시각과 `data_available_at`도 내용에 포함된다. 원본 파일 바이트의 해시는 출처 확인용으로 실행 manifest에만 둘 수 있다 (같은 내용이 다른 파일 형식으로 저장되어도 입력 fingerprint는 같게 하기 위해). 정의의 최종 선택(레코드 내용 기준 / 원본 바이트 기준)은 Q11-11 | 파일 경로나 서식이 아니라 계산에 들어간 데이터의 내용이 입력의 정체성을 정한다 |

**입력 fingerprint, 실행 manifest, 데이터 vintage 기록의 책임 (R1)**

| 기록 | 담는 것 | 담지 않는 것 | 바뀌는 경우 |
|---|---|---|---|
| 입력 fingerprint | 데이터별 `content_hash`, 체결 가정, 정책 프로필, 설정, schema 이름·버전 | `dataset_id`, 저장 위치, vintage 표기, 코드 버전, 환경, 실행 시각 | 계산에 들어간 데이터 내용이나 가정·설정이 바뀔 때 |
| 실행 manifest (`lab-run`) | 입력·결과 fingerprint, 코드 버전, 환경, 타임존 데이터 버전, 데이터별 공급자·`dataset_id`·vintage·저장 위치·파서 버전·(선택) 원본 바이트 해시, 실행 시각, 시뮬레이터 시드 | 데이터 내용 자체 | 실행마다 |
| 데이터 vintage 기록 (데이터 계층) | 관측값과 수정본(별도 `data_available_at`), vintage별로 어떤 관측이 알려져 있었는지 | 실행 정보 | 공급자 수정·새 수집 때 (ADR-0004 Q4-4) |

**새 schema가 덮는 기록 (P0-02C1 요약 §11이 D-11에 넘긴 항목 포함)**

| 기록 | schema 이름 (가칭) | 비고 |
|---|---|---|
| 새 연구 입력 | `lab-input` | 관측값·체결 가정·위험 입력 분리 (ADR-0004 §6.3), 데이터 지연 가정 (ADR-0004 Q4-3), 데이터별 `content_hash` (FP-11, FP-19) |
| 새 연구 결과 | `lab-result` | 일별 체결 기록(시각 포함, ADR-0009), 평가 상태 표시(오래된 가격, 잠정 평가, ADR-0007), 일별 NAV와 분해 (ADR-0008) |
| NAV 기록 | `lab-nav` | 평가 환율과 그 시각 포함 (ADR-0008 §6.7) |
| 주문·체결 이벤트 기록 | `lab-order-event` | Paper/Live 추가 전용 기록 (ADR-0009 §6.1). 보관 위치·형식은 ADR-0009 Q9-9 그대로 |
| 실행 manifest | `lab-run` | 코드·데이터·환경·타임존 데이터 버전, 정책 프로필, 실행 모드, 시뮬레이터 시드(있다면, ADR-0012) |
| golden 기록 | `golden-v1` | §6.3 |

필드 목록과 자료형은 P0-03에서 정한다.

### 6.6 재현성 판정 (제안)

같은 시나리오를 다시 실행하거나 기록과 비교할 때 결과를 다음 가운데 하나로 보고한다. 자동으로 "같음"으로 바꾸지 않는다.

| 판정 | 조건 | 처리 |
|---|---|---|
| `REPRODUCED` | 입력 fingerprint와 결과가 같음 | 통과. 코드 버전, 환경, vintage 표기, 저장 위치가 다르면 그 차이를 함께 기록 (R1) |
| `RESULT_CHANGED` | 입력 fingerprint와 환경이 같은데 결과가 다름 | **실패.** 코드 변경이 원인일 가능성이 큼 (AT-0011-7). 코드 버전도 같다면 비결정성 의심으로 함께 보고 |
| `ENVIRONMENT_DIFFERS` | 입력·코드·데이터는 같고 환경이 다르며 결과가 다름 | 실패로 보고하고 필드별 차이를 낸다. 허용 오차를 자동 적용하지 않음 (Q11-3) |
| `CODE_AND_ENVIRONMENT_DIFFER` | 입력·데이터는 같고 코드와 환경이 모두 다르며 결과가 다름 | 원인을 구분할 수 없으므로 실패로 보고한다. 한 요인씩 맞춰(같은 환경에서 두 코드, 또는 같은 코드에서 두 환경) 다시 실행해 원인을 가린다 |
| `INPUT_DIFFERS` | 데이터 `content_hash`는 같은데 체결 가정, 정책 프로필, 설정 때문에 입력 fingerprint가 다름 | 같은 입력이 아니다. 비교 대상이 아님을 보고하고 달라진 항목을 낸다 |
| `DATA_CONTENT_DIFFERS` | 데이터의 `content_hash`가 다름 (따라서 입력 fingerprint도 다름) | 같은 입력이 아니다. 비교 대상이 아님을 보고하고, 어느 데이터셋의 내용이 달라졌는지 낸다 (R1에서 `DATA_VERSION_DIFFERS`를 대체. vintage만 다르고 내용이 같으면 이 판정이 아니라 `REPRODUCED` + vintage 차이 기록) |
| `SCHEMA_DIFFERS` | 기록의 schema version이 다름 | 비교하지 않고 보고. 변환 규칙이 있으면 명시적으로만 적용 |

### 6.7 golden 무단 변경의 검출과 갱신 원칙

- **검출 장치 (제안)**: golden 파일마다 내용 해시를 등록한 목록을 두고, 테스트가 파일 내용 해시와 목록을 비교한다. 목록이 바뀔 때는 같은 변경에 승인 기록 항목(이유, 이전·이후 fingerprint, 승인자, 날짜)이 있어야 한다.
- **한계**: 같은 사람이 golden 파일, 해시 목록, 승인 기록을 함께 바꾸면 기술적으로는 막을 수 없다. 이 경우는 Git diff 검토로 드러난다. 검출 장치는 **실수로 인한 갱신**과 **기록 없는 갱신**을 잡는 장치다.
- **갱신 원칙**: (1) golden은 테스트 실행이 자동으로 고치지 않는다. (2) V1 결과가 바뀌는 변경은 ADR-0005에 따라 별도 승인을 받는다. (3) 갱신 커밋은 golden 변경만 담고, 코드 변경과 섞지 않는 것을 권장한다. 세부 형식은 Q11-4다.

### 6.8 golden 테스트의 구현 경계

| 항목 | 상태 |
|---|---|
| 구조 변경 전에 golden 보호 장치가 있어야 한다 | **승인됨** (ADR-0005 승인 원칙 6) |
| golden 기록의 논리 구조 (§6.3), 대표 시나리오 후보 (§6.4), fingerprint 정책 (§6.5) | 핵심 원칙은 **승인됨** (P0-02C2-FINAL, §2). 시나리오 목록과 구체 규칙은 §2 "규칙별 승인 상태"와 미승인 표를 따름 |
| 저장 형식 (권장: 별도 canonical JSON 파일) | **미결정** (Q5-4, Q11-1) |
| 시나리오 목록과 개수 | **미결정** (Q5-4, Q11-2) |
| 테스트 작성 시점과 작업 | **미결정** (Q5-9, Q11-5). 이 ADR은 테스트를 작성하지 않는다 |
| 갱신 절차의 세부 형식 | **미결정** (Q11-4) |
| 환경 간 허용 오차 | **미결정** (Q11-3) |
| 차등 비교 허용 오차 | **미결정** (Q5-6) |

### 6.9 ACCEPTED ADR과의 정합성

| ACCEPTED 결정 | 이 ADR의 대응 | 충돌 여부 |
|---|---|---|
| ADR-0005 승인 원칙 6 (구조 변경 전 golden) | §6.3~§6.7이 설계를 제안. 구현은 하지 않음 | 없음 |
| ADR-0005 AT-0005-1 (같은 경로의 실수는 정확히 같아야 함) | 같은 환경에서 정확 비교 (§6.3). 다른 환경은 별도 판정 (§6.6) | 없음. 환경 간 문제는 AT-0005-1이 다루지 않은 부분으로 Q11-3에 기록 |
| ADR-0005 Q5-4, Q5-6, Q5-9 (미결정) | 권장안만 제시, 닫지 않음 | 없음 |
| ADR-0005 §6.7 golden의 한계 | §6.2에서 세 검증을 분리 | 없음 |
| ADR-0004 P-1~P-4 (V1 타입·payload 불변, 새 입력은 별도 payload와 schema version) | FP-1~FP-4, FP-5~FP-19 | 없음 |
| ADR-0001 §8.0 (V1 fingerprint 불변), Q1-9 (보존 방법은 P0-03) | 권장 답 제시 (§6.1). Q1-9는 열린 채로 (Q11-9) | 없음 |
| ADR-0004 Q4-3 (데이터 지연 가정 표현), Q4-4 (vintage 보관) | 입력 schema와 데이터 버전에 자리만 둠 (FP-12, FP-13) | 없음 (열린 질문 유지) |
| ADR-0007 C7-1, C7-2 (UTC 저장, 타임존 DB 변환) | FP-10, FP-14 | 없음 |
| ADR-0008 §6.7 (NAV 기록에 평가 환율과 시각) | `lab-nav` schema | 없음 |
| ADR-0009 §6.1 (Paper/Live 추가 전용 기록), Q9-9 (보관 위치·형식) | `lab-order-event` schema의 버전 규칙만 제안. 위치·형식은 Q9-9 그대로 | 없음 |

## 7. Consequences / Trade-offs

**장점**
- V1을 바꾸지 않고 V1 결과 전체(일별 체결과 롤 다리 포함)를 고정할 수 있다.
- V1 fingerprint와 새 fingerprint가 형식만 보고 구분되므로, 새 시스템 도입이 V1 기준값을 조용히 대체하는 일이 없다.
- 결과 차이의 원인(코드·데이터·환경·schema)을 판정으로 나눌 수 있다.

**단점과 비용**
- 인코더가 두 개(V1, 새 시스템) 공존한다.
- golden 파일과 해시 목록, 승인 기록을 관리해야 한다.
- golden은 V1 결함을 고정한다. golden 통과를 "정확함"으로 오해하지 않도록 보고서와 문서에서 계속 구분해야 한다.
- 환경 간 실수 차이가 실제로 생기면 CI 도입 시 판단 기준(Q11-3)이 필요하다.

## 8. Compatibility with V1

이 ADR은 ADR-0001 §8.0(세 ADR 공통)의 `V1_COMPAT` 적용 범위를 그대로 따른다.

| 항목 | 영향 |
|---|---|
| V1 인코더, payload, fingerprint 함수, schema version 상수 | 변경 없음 (FP-1) |
| V1 타입 | 변경 없음 (FP-2) |
| V1 번들 필드 | 변경 없음 (FP-3) |
| 기존 306개 테스트 | 변경 없음. golden은 **새 테스트로만** 추가한다 |
| `V1_COMPAT` 재현 실행 | V1 fingerprint를 V1 함수로 계산해 별도 필드에 담는다 (FP-17) |

## 9. Financial Integrity Implications

- **조용한 결과 변화**: golden이 없으면 구조 변경이 손익을 바꿔도 306개 테스트가 통과할 수 있다 (ADR-0005 §3.3). golden이 이를 잡는다.
- **잘못된 안심**: golden은 V1 결함(체결가 mid와 평가가격 차이의 누락 F-02, 보유분 손익 누락 가능성 A-05, 환산 손익 없음)까지 고정한다. golden 통과를 금융적 정확성의 근거로 쓰면 안 된다.
- **롤일 공백**: D 경로의 롤일 결과는 지금 어떤 테스트도 고정하지 않는다 (§3.3). 롤일은 손익 왜곡이 생기기 쉬운 지점이므로(ADR-0001 C-2, P0-04 V-06) G-2를 우선 후보로 권장한다.
- **데이터 수정**: 공급자가 과거 값을 고치면 같은 "날짜"의 입력이 다른 결과를 낸다. 실행이 그 수정본을 포함하는 vintage를 쓰면 `content_hash`와 입력 fingerprint가 달라져 수정이 드러난다. `dataset_id`만 기록하면 이 변화를 놓친다 (FP-11~FP-13, FP-19, AT-0011-9).
- **타임존 규칙**: 타임존 데이터 버전이 바뀌면 과거 시각 변환이 달라질 수 있다 (FP-14).

## 10. Acceptance Criteria

인수 테스트는 **명세**다. 이번 작업에서 구현하지 않았다. 해시 값은 golden을 처음 기록할 때 정해진다.

### AT-0011-1 같은 V1 입력은 같은 fingerprint를 만든다

- **입력**: golden 시나리오 하나의 V1 입력.
- **기대 결과**:
  - 같은 프로세스에서 두 번 계산한 입력·결과 fingerprint가 같다 (기존 테스트가 이미 확인하는 성질, `tests/test_backtest_result_bundle.py:212`).
  - **새 프로세스**에서 계산한 값이 golden에 기록된 64자 문자열과 문자 단위로 같다.
  - 상품 dict 순서를 바꿔도 같다 (`tests/test_backtest_manifest.py:353`과 같은 성질).
- **새 테스트 후보**: `test_v1_golden_input_fingerprint`, `test_v1_golden_result_fingerprint_in_fresh_process`

### AT-0011-2 dataclass 필드 추가가 fingerprint에 미치는 영향을 검출한다

- **원칙 (R1)**: 서로 다른 두 payload 전체를 비교하지 않는다. **같은 입력 payload에서 한 객체만 바꿔** 차이가 그 변경 하나에서만 오는지 확인한다. V1 인코더(`to_canonical_json`)와 V1 dataclass는 바꾸지 않는다.
- **입력**: golden 시나리오의 V1 입력으로 V1 payload P를 만든다 (V1 `build_backtest_input_payload`). P 안의 `ExecutionMarketDay` 객체 하나 d를 골라 두 변형을 만든다.
  - P_renamed: d를 **클래스 이름만 다르고** 필드·순서·값이 같은 테스트 전용 dataclass 인스턴스로 바꾼 것
  - P_plus: d를 d의 필드 전부 + 기본값 `None`인 필드 하나(`observed_at`)를 가진 테스트 전용 dataclass 인스턴스로 바꾼 것 (값은 d와 같음)
  - 나머지 객체는 세 payload에서 모두 같은 객체다.
- **기대 결과**:
  - (a) 클래스 이름 성질: `to_canonical_json(P_renamed) == to_canonical_json(P)`이고 해시도 같다 (FP-8의 근거. V1은 타입 이름을 직렬화하지 않음).
  - (b) 필드 추가 성질: `to_canonical_json(P_plus) != to_canonical_json(P)`이고 해시가 다르다 (FP-2의 근거).
  - (c) 차이의 국소성: 두 JSON 문자열의 차이는 d 위치에 삽입된 `"observed_at":null,` 하나뿐이다 (키 정렬 때문에 위치는 알파벳 순서로 정해짐).
  - 참고 probe (2026-10-16, 저장소 밖, V1 `ExecutionMarketDay` 하나로 만든 작은 payload): (a) 두 해시 모두 `aeb12aa0…`, (b) `aeb12aa0…` → `fd98db44…`, (c) 삽입된 문자열은 `"observed_at":null,` 19자. 실제 테스트의 해시 값은 golden 입력으로 정해진다.
- **예외조건**: (a)에서 문자열이 다르거나 (b)에서 같으면 V1 인코더 동작이 바뀐 것이므로 실패한다. (c)에서 다른 위치도 달라지면 테스트 구성이 잘못된 것이다.
- **새 테스트 후보**: `test_v1_encoder_ignores_dataclass_name`, `test_added_dataclass_field_changes_v1_fingerprint_locally`

### AT-0011-3 새 schema는 V1 fingerprint를 덮어쓰지 않는다

- **입력**: golden 시나리오를 (i) V1 API로, (ii) 새 엔진 `V1_COMPAT` 모드로 실행한다 (ADR-0005 AT-0005-3 전제).
- **기대 결과**:
  - (ii)의 실행 기록에서 `v1_input_fingerprint_sha256`, `v1_result_fingerprint_sha256`가 golden의 V1 값과 문자 단위로 같다 (FP-17).
  - (ii)의 새 fingerprint는 `lab-…/N:sha256:` 접두사를 갖고 V1 값과 다르다 (FP-6, FP-7).
  - 새 기록 필드에 접두사 없는 64자 문자열을 넣으면 검증에서 거부된다. V1 필드에 접두사 문자열을 넣어도 거부된다.
  - V1 번들의 필드 이름과 값 형식은 그대로다 (FP-3).
- **새 테스트 후보**: `test_v1_compat_run_records_v1_fingerprints_unchanged`, `test_new_fingerprint_format_is_distinguishable_from_v1`

### AT-0011-4 롤일의 일별 결과를 고정한다

- **입력**: 시나리오 G-2. 롤일 t에 구월물에서 신월물로 전량 롤.
- **기대 결과**: golden이 롤일 t에 대해 다음을 기록하고, 다시 실행한 결과가 같다.
  - 체결 다리 2개: 구월물 청산 다리(월물, 부호 있는 수량, 체결가, 비용), 신월물 진입 다리(같은 항목)
  - 롤 전후 월물별 포지션, 활성 월물, 상품 포지션
  - 그날 상품 gross·비용·net PnL과 계좌
  - 다리별 비용의 합 = 상품 `trading_cost` (V1 집계 규칙의 회귀 확인. 금융적 정확성은 P0-04 V-06·V-07)
- **전제조건**: D 경로가 롤 이벤트 입력을 받아 실행됨 (구현 시 확인).
- **새 테스트 후보**: `test_v1_golden_roll_day_legs`, `test_v1_golden_roll_day_positions_and_pnl`

### AT-0011-5 환경이나 데이터 내용이 다를 때 재현성을 보고한다

- **입력**: 같은 시나리오에 대해 (a) 실행 manifest의 pandas 버전만 다른 기록, (b) 데이터 `content_hash`가 다른 기록, (c) schema version만 다른 기록.
- **기대 결과**: (a) 결과가 같으면 `REPRODUCED`와 환경 차이 기록, 결과가 다르면 `ENVIRONMENT_DIFFERS`와 필드별 차이. 허용 오차를 자동 적용하지 않는다. (b) `DATA_CONTENT_DIFFERS`. vintage만 다르고 내용이 같은 경우는 AT-0011-9 (b2). (c) `SCHEMA_DIFFERS` (§6.6).
- **새 테스트 후보**: `test_reproducibility_report_classifies_environment_difference`, `test_reproducibility_report_classifies_data_content_difference`

### AT-0011-6 승인 없이 golden을 바꾸면 검출한다

- **입력**: (a) golden 파일의 실수 하나를 고치고 해시 목록은 그대로 둠. (b) golden 파일과 해시 목록을 함께 고치고 승인 기록 항목은 추가하지 않음.
- **기대 결과**: (a) 내용 해시 불일치로 실패. (b) 승인 기록 누락으로 실패. 세 가지를 모두 고친 경우는 테스트로 잡지 못하며 Git 검토 대상이라는 한계를 문서에 남긴다 (§6.7).
- **새 테스트 후보**: `test_golden_files_match_registered_hashes`, `test_golden_registry_change_requires_approval_entry`

### AT-0011-7 입력은 같고 금융 공식이 바뀐 경우를 검출한다

- **입력**: golden 시나리오 G-5. 테스트 안에서 V1 비용 계산 함수를 패치해 다리당 비용에 0.01을 더한다 (공식 변경을 흉내 냄). 패치 지점은 D 경로가 실제로 찾는 이름인 `carver_quant.roll_execution.calculate_total_trading_cost`다 (`roll_execution.py:7, 88`). `carver_quant.costs.calculate_total_trading_cost`를 패치하면 효과가 없다 (ADR-0010 §3.4와 같은 이유).
- **기대 결과**: 입력 fingerprint는 golden과 같다. 결과 fingerprint와 일별 비용·net PnL·계좌가 다르며, 처음 달라진 (날짜, 상품, 필드)를 보고한다. 판정은 `RESULT_CHANGED`.
- **한계**: fixture가 지나지 않는 계산 경로의 변경은 잡지 못한다. 시나리오가 어떤 경로를 덮는지 §6.4 표로 관리한다.
- **새 테스트 후보**: `test_formula_change_detected_with_same_input_fingerprint`

### AT-0011-8 세 검증은 서로를 대신하지 못한다

- **입력**: warm-up 이후 forecast가 한 번 `None`이 되어 V1 준비 단계가 그날을 건너뛰는 입력 (GAP A-05, ADR-0005 AT-0005-4와 같은 성질).
- **기대 결과**:
  - Golden: V1 결과를 그대로 고정하므로 **통과**한다 (누락된 보유분 손익까지 고정).
  - Differential: 새 엔진 `V1_COMPAT`가 같은 날을 건너뛰어 V1을 재현하면 **통과**한다.
  - Financial Integrity: 그날 보유분 손익 `q × (V[t] − V[t−1]) × M × fx`가 독립 계산과 맞지 않으므로 **실패**한다.
  - 즉 golden과 차등 비교가 모두 통과해도 금융적 결함이 남을 수 있다. 반대로 golden 실패는 결함이 아니라 변화만 뜻할 수 있다.
- **새 테스트 후보**: `test_golden_and_differential_do_not_prove_financial_integrity` (문서화용 테스트)

### AT-0011-9 새 입력 fingerprint가 데이터 내용 변경을 감지한다 (R1 추가)

- **입력**: 새 시스템(`lab`)의 연구 입력 하나. 데이터셋 `dataset_id = "XKR-F1-daily"`(가칭), 레코드 40개. 비교 기준 실행 R0의 입력 fingerprint를 I0, 내용 해시를 H0라 한다.
- **기대 결과**:

| 경우 | 변경 | `content_hash` | 입력 fingerprint | 실행 manifest | 판정 |
|---|---|---|---|---|---|
| (a) | `dataset_id`는 같고, 공급자가 2026-01-05 종가를 101.0에서 101.5로 고친 수정본이 포함됨 (수정본은 새 `data_available_at`의 별도 관측) | H0와 **다름** | I0와 **다름** | `dataset_id` 같음, vintage 다름 | `DATA_CONTENT_DIFFERS`. 결과 비교 대상 아님 |
| (b1) | vintage만 바꿈. 두 vintage 사이에 수정본이 있어 고른 레코드가 달라짐 | 다름 | 다름 | vintage 다름 | `DATA_CONTENT_DIFFERS` |
| (b2) | vintage만 바꿈. 두 vintage 사이에 수정본이 없어 고른 레코드가 같음 | **H0와 같음** | **I0와 같음** | vintage 다름 | 결과가 같으면 `REPRODUCED` + vintage 차이 기록 |
| (c) | 같은 내용을 다른 파일 경로(또는 다른 저장 위치)에서 읽음 | 같음 | 같음 | 저장 위치 다름 | 결과가 같으면 `REPRODUCED` + 위치 차이 기록 |
| (d) | 데이터와 설정은 같고 코드 버전만 바뀜 | 같음 | **같음** | 코드 버전 다름 | 결과가 같으면 `REPRODUCED` + 코드 차이 기록. 결과가 다르면 `RESULT_CHANGED` (AT-0011-7) |

- **V1과의 관계**: V1 입력 fingerprint 규칙은 바꾸지 않는다 (FP-1). V1 payload는 가격 레코드 전체를 직렬화하므로 V1 입력으로 (a)를 재현하면 V1 fingerprint도 달라진다. 이것은 V1의 기존 동작이며 이 ADR이 만든 성질이 아니다.
- **예외조건**: `content_hash`를 계산할 수 없는 입력(레코드를 정렬할 키가 없음, 직렬화할 수 없는 값)은 실행을 거부한다. `dataset_id`만 있고 `content_hash`가 없는 입력도 거부한다.
- **새 테스트 후보**: `test_input_fingerprint_changes_when_provider_corrects_price`, `test_vintage_change_without_content_change_keeps_input_fingerprint`, `test_file_path_change_keeps_input_fingerprint`, `test_code_version_change_keeps_input_fingerprint`

## 11. Open Questions

| ID | 질문 | 결정 주체 |
|---|---|---|
| Q11-1 | golden 저장 형식: 테스트 코드 리터럴 / 별도 canonical JSON 파일(권장) / 둘의 조합 (ADR-0005 Q5-4) | 사용자 |
| Q11-2 | golden 시나리오 목록과 개수 (§6.4 G-1~G-10은 후보). 우선순위 (권장: G-2 롤, G-4 FX, G-9 가드레일을 먼저) | 사용자 (Q5-4) |
| Q11-3 | 다른 환경(아키텍처, numpy·pandas 버전)에서 실수가 다를 때의 정책: 환경별 golden / 허용 오차(근거와 함께) / 기준 환경 하나만 인정. 실제 차이가 있는지는 UNVERIFIED | 사용자 (CI 도입 시) |
| Q11-4 | golden 갱신 절차의 세부 형식 (승인 기록 형식, 갱신 명령, 커밋 규칙) | 사용자 |
| Q11-5 | golden 테스트를 언제, 어떤 작업으로 구현할 것인가 (ADR-0005 Q5-9) | 사용자 |
| Q11-6 | 새 인코더의 수치 정책: `-0.0` 정규화, 금액에 Decimal 사용 여부, 실수 직렬화 방식 | 사용자 (P0-03) |
| Q11-7 | 코드 버전 자동 수집 방식과, 작업 트리에 미커밋 변경이 있을 때 golden 기록·재현성 판정을 거부할지 | 사용자 |
| Q11-8 | 데이터 vintage 보관 방식(ADR-0004 Q4-4)과 백테스트 데이터 지연 가정의 기록 형식(ADR-0004 Q4-3) | 사용자 (P0-03, Phase 1) |
| Q11-9 | ADR-0001 Q1-9의 답으로 "V1 타입·payload 불변 + 새 입력은 별도 타입·payload·schema version"(§6.1)을 채택할 것인가 | 사용자 (P0-03) |
| Q11-10 | 주문·체결 이벤트 기록과 NAV 기록의 저장 위치·형식 (ADR-0009 Q9-9). 이 ADR은 버전 규칙만 제안 | 사용자 (Paper 설계 시) |
| Q11-11 | (R1) `content_hash`를 레코드 내용 기준(새 인코더로 직렬화, 권장)으로 정할 것인가, 원본 파일 바이트 기준으로 정할 것인가. 파서 버전이 바뀌어 같은 파일에서 다른 값이 나오는 경우의 처리 | 사용자 (P0-03) |

## 12. Related Code and Documents

- 코드: `backtest_manifest.py:30-31, 48-101, 217-301, 303-403, 405-517, 519-631, 633-676`, `backtest_result_bundle.py:18, 27-55, 57-191, 192-253`, `portfolio_backtest.py:40-65`, `contract_aware_daily_step.py:29-43`, `roll_execution.py:22-26`, `performance.py:15-34`
- 테스트: `tests/test_backtest_manifest.py:332-503`, `tests/test_backtest_result_bundle.py:147-321`, `tests/test_v1_acceptance.py:138`, `tests/test_system_backtest.py:164`, `tests/test_portfolio_system_backtest.py:95, 312, 393`, `tests/test_portfolio_backtest.py:476, 646, 737, 791`, `tests/test_contract_aware_backtest.py:119, 778, 847, 1244, 1621`, `tests/test_research_pipeline.py:60-84`
- 문서: [V1_GAP_ANALYSIS.md](../quality/V1_GAP_ANALYSIS.md) A-09, A-11, F-10; [DEVELOPMENT_BASELINE.md](../architecture/DEVELOPMENT_BASELINE.md); [TEST_BASELINE.md](../quality/TEST_BASELINE.md); [P0-02C1_DECISION_SUMMARY.md](../architecture/P0-02C1_DECISION_SUMMARY.md) §11; [P0-02C2_DECISION_SUMMARY.md](../architecture/P0-02C2_DECISION_SUMMARY.md)
- 관련 ADR: [0001](0001-execution-timing-and-valuation.md), [0004](0004-market-data-and-domain-boundaries.md), [0005](0005-backtest-paths-and-v1-compatibility.md), [0007](0007-multi-market-calendar-and-valuation.md), [0008](0008-multi-currency-fx-accounting.md), [0009](0009-order-fill-and-position-lifecycle.md), [0010](0010-physical-package-boundaries.md), [0012](0012-broker-adapter-boundaries.md)

## 13. 개정 이력

| 개정 | 날짜 | 내용 |
|---|---|---|
| R0 | 2026-10-16 | 최초 제안 (P0-02C2). 상태 PROPOSED. 작성 후 읽기 전용 독립 검토의 지적을 반영함 ([P0-02C2_DECISION_SUMMARY.md](../architecture/P0-02C2_DECISION_SUMMARY.md) §14) |
| R1 | 2026-10-16 | P0-02C2-R1. (1) 입력 fingerprint가 데이터 내용을 반영하도록 FP-11~FP-13을 고치고 `content_hash` 정의 FP-19를 추가. `dataset_id`, 저장 위치, vintage 표기, 코드 버전은 실행 manifest로 분리하고 책임 표 추가. (2) §6.6 판정: `REPRODUCED`를 "입력 fingerprint와 결과가 같음"으로 바꾸고, `DATA_VERSION_DIFFERS`를 `DATA_CONTENT_DIFFERS`로 대체. AT-0011-5 (b)를 이에 맞춤. (3) AT-0011-2를 같은 payload 안에서 객체 하나만 바꾸는 방식으로 다시 씀 (probe 값 추가). (4) AT-0011-9, Q11-11 추가. (5) R1 독립 검토 반영: §5.4·§9·AT-0011-5 제목의 남은 표현 정리, §6.6에 `INPUT_DIFFERS` 추가. 상태 PROPOSED 유지 |
| FINAL | 2026-10-16 | P0-02C2-FINAL — 사용자 핵심 원칙 승인. 상태를 PROPOSED에서 **ACCEPTED**로 변경 (범위는 §2). §2에 승인 기록, 승인된 원칙 12개, golden master의 의미, 입력 fingerprint·실행 manifest·vintage의 구분, FP 규칙별 승인 상태, 미승인 사항을 추가. §6.8 표의 상태 표기를 갱신. Q11-9와 승인 원칙의 관계를 §2에 명시. 본문의 규칙, 숫자 예제, 인수 테스트, 질문 ID는 바꾸지 않음 |
