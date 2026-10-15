# Test Baseline

- 최초 작성: 2026-10-15 (P0-00)
- 갱신: 2026-10-15 (P0-00A, 의존성 선언과 표준 설치 방식 확정 후 재검증)
- 기준 커밋: `258e5641440b64d9b054733960605d2cc170c086` (`master`)와 P0-00A의 미커밋 변경 (`pyproject.toml`, `.gitignore`, egg-info 추적 해제)
- 환경: Android 13 / Termux / aarch64, **Python 3.14.6**
- 관련 문서: [`docs/architecture/DEVELOPMENT_BASELINE.md`](../architecture/DEVELOPMENT_BASELINE.md)

## 1. 표준 실행 명령

```sh
. .venv/bin/activate                  # 저장소 루트의 표준 가상환경
python -m pip install -e ".[test]"    # 최초 1회 (Termux는 DEVELOPMENT_BASELINE 3.2의 사전 절차 필요)
python -m pytest -q                   # 기대 결과: 306 passed
python -m pytest -q -W error          # 기대 결과: 306 passed (경고를 에러로 처리)
```

`PYTHONPATH=src` 방식은 더 이상 표준이 아니다. 프로젝트를 설치한 상태에서 실행한다.

## 2. 요약 (P0-00A 인수 테스트)

| 항목 | 값 |
|---|---|
| Python | 3.14.6 (`<저장소>/.venv/bin/python`, `--system-site-packages`) |
| 설치 | `python -m pip install -e ".[test]"` 성공, `pip check` 통과 |
| 테스트 파일 수 | 39 |
| 수집된 테스트 수 | **306** |
| `python -m pytest -q` | ✅ **306 passed** (약 1.4초) |
| `python -m pytest -q -W error` | ✅ **306 passed** |
| 실패 / 에러 / 스킵 / xfail / 경고 | 0 / 0 / 0 / 0 / 0 |
| 기존 기준(306개)과의 차이 | 없음 |
| `src/carver_quant/`, `tests/` 변경 | 없음 (작업 전후 추적 파일 sha256 합계 `7764c576…6272` 동일) |

사용한 패키지 버전은 pandas 3.0.6, numpy 2.5.4, python-dateutil 2.9.0.post0, pytest 9.1.1, pluggy 1.6.0, iniconfig 2.3.1, packaging 26.3이다.

## 3. 실행 시나리오

### 3.1 P0-00A (의존성 선언 이후)

| # | 환경 / 명령 | 결과 | 비고 |
|---|---|---|---|
| T1 | Termux, `python -m venv --system-site-packages .venv` → `pip install -e ".[test]"` → `python -m pytest -q` | ✅ 306 passed | pandas 요구(`>=3.0,<4`)는 시스템 패키지 3.0.6으로 충족되어 다운로드 없음. venv에는 pytest와 그 의존성만 설치됨 |
| T1′ | T1과 같은 환경에서 `python -m pytest -q -W error` | ✅ 306 passed | |
| T3 | Termux, `--system-site-packages` venv에서 비-editable `pip install ".[test]"` 실행 후 `python -m pytest -q -W error` (복제본, `src/`를 숨기고 실행) | ✅ 306 passed | site-packages에 설치된 패키지를 import함. 메타데이터 `Requires: pandas` 확인 |
| T2 | Termux, `python -m venv .venv` (시스템 패키지 미연동) → `pip install -e ".[test]"` | ❌ 실패 (900초 타임아웃, exit 124) | PyPI에 Android wheel이 없어 pip가 `pandas-3.0.6.tar.gz`(sdist)를 받고, 빌드 의존성(meson-python, meson, ninja, Cython, numpy)을 소스 빌드하는 "Installing build dependencies" 단계에서 15분 넘게 진행되지 않음. 프로젝트 문제가 아니라 플랫폼 제약이다. 대안은 T1 (Termux 패키지 + `--system-site-packages`) |

### 3.2 P0-00 (의존성 선언 이전, 참고용 이력)

| # | 명령 | 결과 | 원인 |
|---|---|---|---|
| A | 시스템 Python에서 `python -m pytest -q` | ❌ | pytest 미설치 |
| A′ | 저장소 바깥 `.venv`에서 실행 | ❌ | venv 손상 (3.12로 생성, 현재 3.14 실행) |
| B | pytest와 pandas는 있지만 프로젝트 미설치 상태에서 `python -m pytest -q` | ❌ 38 collection errors | src 레이아웃이라 `carver_quant` import 불가 |
| C | `PYTHONPATH=src python -m pytest -q` | ✅ 306 passed | |
| D | `pip install .` 후 실행 (복제본) | ✅ 306 passed | |
| E | `pip install -e .` 후 실행 (복제본) | ✅ 306 passed | |

시나리오 B의 상황(프로젝트 미설치 상태에서 실행)은 표준 절차를 따르면 생기지 않는다. 표준 절차는 설치 후 실행이다.

## 4. 파일별 테스트 수

| 파일 | 수 | 파일 | 수 |
|---|---:|---|---:|
| test_account_ledger.py | 6 | test_futures_data.py | 9 |
| test_backtest.py | 3 | test_fx.py | 6 |
| test_backtest_config.py | 6 | test_instrument.py | 12 |
| test_backtest_manifest.py | 10 | test_performance.py | 9 |
| test_backtest_result_bundle.py | 4 | test_pnl.py | 16 |
| test_buffering.py | 4 | test_portfolio.py | 4 |
| test_combined_forecast.py | 6 | test_portfolio_backtest.py | 9 |
| test_combined_forecast_integration.py | 1 | test_portfolio_system_backtest.py | 8 |
| test_combined_system_backtest.py | 1 | test_position.py | 14 |
| test_contract_aware_backtest.py | 12 | test_position_ledger.py | 4 |
| test_contract_aware_daily_step.py | 14 | test_research_pipeline.py | 10 |
| test_contract_aware_daily_step_buffering.py | 3 | test_risk_guardrail.py | 6 |
| test_contract_ledger.py | 8 | test_risk_target.py | 4 |
| test_costs.py | 18 | test_roll.py | 10 |
| test_daily_step.py | 4 | test_roll_aware_daily_step.py | 7 |
| test_data_quality.py | 6 | test_roll_execution.py | 12 |
| test_environment.py | 1 | test_system_backtest.py | 4 |
| test_execution.py | 27 | test_trade.py | 6 |
| test_forecast.py | 9 | test_v1_acceptance.py | 1 |
| | | test_volatility.py | 12 |
| | | **합계** | **306** |

## 5. 테스트 구조

- `pyproject.toml`의 `[tool.pytest.ini_options] testpaths = ["tests"]` 설정을 따른다. `pythonpath` 설정은 없다(설치 후 실행이 전제).
- `conftest.py`, 공유 fixture, 사용자 정의 마커, 커버리지 설정은 없다.
- 사용하는 pytest 기능: `pytest.approx` 316회, `pytest.raises` 98회, `pytest.mark.parametrize` 2회.
- 외부 데이터 파일이나 네트워크에 의존하지 않는다. 모든 입력이 코드 안에 정의되어 있다.

## 6. 알려진 문제

- 의존성 버전이 범위로만 선언되어 있고 lock이 없다. 범위 안의 다른 pandas 버전에서는 `ewm`/`rolling` 기반 수치 테스트(`test_volatility.py`, `test_forecast.py` 및 이를 사용하는 백테스트 테스트)의 결과가 달라질 수 있다.
- Termux에서는 `--system-site-packages` 없이 표준 설치를 할 수 없다 (T2).

## 7. 미검증 항목

- 일반 Linux / macOS / Windows에서의 T1에 해당하는 절차
- pandas 3.0.6 이외 버전, pytest 9.1.1 이외 버전
- Python 3.15 이상
- 커버리지 측정, 테스트 순서 무작위화, 병렬 실행
