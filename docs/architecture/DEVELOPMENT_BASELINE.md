# Development Baseline

- 최초 작성: 2026-10-15 (P0-00, 조사·기록)
- 갱신: 2026-10-15 (P0-00A, 패키징·개발 환경 정비)
- 기준 커밋: `258e5641440b64d9b054733960605d2cc170c086` (`master`, "quant engine v1")와 P0-00A의 미커밋 변경
- 목적: 개발 환경, 의존성, 설치 방법을 재현 가능한 기준선으로 고정한다.

테스트 결과의 상세 내용은 [`docs/quality/TEST_BASELINE.md`](../quality/TEST_BASELINE.md)에 있다.

---

## 1. 표준 (요약)

| 항목 | 표준 |
|---|---|
| Python | 3.14 (`requires-python = ">=3.14"`, 변경하지 않음) |
| 가상환경 위치 | 저장소 루트의 `.venv/` (`.gitignore` 대상) |
| 개발 설치 | `python -m pip install -e ".[test]"` |
| 테스트 실행 | `python -m pytest -q` (가상환경을 활성화하고 프로젝트를 설치한 상태) |
| 엄격 실행 | `python -m pytest -q -W error` |
| 기대 결과 | `306 passed`, 경고 0 |

## 2. 의존성 선언 (`pyproject.toml`)

```toml
[project]
requires-python = ">=3.14"
dependencies = [
    "pandas>=3.0,<4",
]

[project.optional-dependencies]
test = [
    "pytest>=9.1,<10",
]
```

### 2.1 근거

| 패키지 | 실제 사용처 | 선언 | 범위 근거 |
|---|---|---|---|
| pandas | `src/carver_quant/volatility.py`, `src/carver_quant/forecast.py`에서 `import pandas as pd`. 사용 API는 `pd.Series`, `.ewm(...)`, `.rolling(...)`, `.iloc`, `pd.isna` | `dependencies` | 하한 3.0: 실제 검증한 버전은 3.0.6뿐이다. pandas 2.x는 검증하지 않았고 3.0에서 기본 동작(Copy-on-Write 등)이 바뀌었으므로 하한을 3.0으로 둔다. 상한 <4: 다음 메이저 버전의 API·수치 변경을 막는다 |
| numpy | `src/`와 `tests/` 어디에서도 직접 import하지 않음 (pandas를 통한 간접 의존) | **선언하지 않음** | 직접 사용하지 않는 패키지는 pandas의 의존성 해석에 맡긴다. 앞으로 `import numpy`를 추가하면 그때 선언한다 |
| pytest | `tests/` 전체 | `optional-dependencies.test` | 하한 9.1: 검증 버전은 9.1.1. 상한 <10: 메이저 변경을 막는다. 테스트는 기본 기능(`pytest.approx` 316회, `pytest.raises` 98회, `pytest.mark.parametrize` 2회)만 쓰지만, 검증하지 않은 하위 버전까지 넓히지 않는다 |
| setuptools | 빌드 백엔드 | `build-system.requires = ["setuptools>=68"]` (기존 그대로) | 변경하지 않음 |

나머지 import는 모두 표준 라이브러리다. 네트워크, 파일 I/O, 브로커 API 호출 코드는 없다.

### 2.2 실제 검증된 버전 (2026-10-15, Termux)

| 패키지 | 버전 | 설치 경로 |
|---|---|---|
| Python | 3.14.6 | Termux 패키지 `python 3.14.6-1` |
| pip | 26.2.1 (Termux) / 26.1.2 (venv 내부) | |
| setuptools | 빌드 격리 환경에서 자동 설치 (`>=68`) | |
| pandas | 3.0.6 | Termux 패키지 `python-pandas` (시스템 site-packages) |
| numpy | 2.5.4 | Termux 패키지 `python-numpy` (시스템 site-packages) |
| python-dateutil | 2.9.0.post0 | `python-pandas` 설치 시 시스템 site-packages에 pip로 설치됨 |
| pytest | 9.1.1 | venv에 pip로 설치 |
| pluggy / iniconfig / packaging | 1.6.0 / 2.3.1 / 26.3 | venv에 pip로 설치 (pytest 의존성) |

## 3. 설치 방법

### 3.1 일반 Linux (x86_64 / aarch64, PyPI wheel 사용 가능) — 미검증

```sh
git clone https://github.com/Jwavascript/carver-quant-lab.git
cd carver-quant-lab
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m pytest -q
```

pandas와 numpy를 PyPI wheel로 설치하는 일반적인 절차다. **이 기기에 일반 Linux 환경이 없어서 검증하지 않았다.**
PyPI JSON API로 pandas 3.0.6의 cp314 wheel(manylinux x86_64/aarch64, musllinux, macOS, Windows)이 있다는 것만 확인했다.

### 3.2 Android Termux — 검증됨

PyPI에는 Android용 pandas/numpy wheel이 없다. 따라서 Termux 패키지로 설치하고, 가상환경이 시스템 site-packages를 볼 수 있도록 만든다.

```sh
pkg install python python-pandas            # python 3.14.x, pandas 3.0.x, numpy 2.5.x
cd carver-quant-lab                          # Git 저장소 루트
python -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -e ".[test]"           # pandas 요구는 시스템 패키지로 충족되어 다운로드하지 않음
python -m pytest -q
```

- `--system-site-packages`가 **필수**다. 이 옵션이 없으면 pip가 pandas sdist를 받아 소스 빌드를 시도한다. 실제 검증에서는 빌드 의존성(ninja, numpy, Cython, meson) 컴파일 단계에서 900초 타임아웃으로 실패했다 (TEST_BASELINE 시나리오 T2).
- 시스템 pandas 버전이 선언 범위(`>=3.0,<4`)를 벗어나면 pip가 소스 빌드를 시도하므로 실패할 수 있다. `pkg upgrade`를 실행한 뒤에는 2.2절의 버전을 다시 확인한다.

### 3.3 설치 확인

```sh
python -c "import sys, carver_quant, pandas, numpy, pytest; print(sys.version, carver_quant.__file__, pandas.__version__, numpy.__version__, pytest.__version__)"
python -m pip check          # "No broken requirements found." 이어야 함
```

editable 설치에서 `carver_quant.__file__`은 `<저장소>/src/carver_quant/__init__.py`를 가리켜야 한다.

## 4. 가상환경

| 위치 | 상태 | 비고 |
|---|---|---|
| `<저장소>/.venv/` | **표준. P0-00A에서 새로 생성** | Termux: `python -m venv --system-site-packages .venv` (Python 3.14.6). `.gitignore` 대상 |
| `<저장소 상위 폴더>/.venv/` (저장소 바깥) | 손상됨, 사용 금지 | Python 3.12.12로 생성됐는데 `bin/python`이 시스템 3.14를 가리키고, pip/pytest/pandas가 없음. 지시에 따라 **삭제하지 않았다**. 정리 여부는 사용자가 결정한다 |

## 5. 빌드 산출물 관리

- `.gitignore`에 `build/`와 `*.egg-info/`를 추가했다.
- 그동안 Git이 추적하던 `src/carver_quant_lab.egg-info/`(파일 4개)는 `git rm --cached`로 **추적만 해제**했다. 파일은 디스크에 남아 있다.
- 이후 `pip install -e .`를 실행하면 setuptools가 이 디렉터리를 다시 생성하지만, 무시 대상이므로 Git 상태에 영향이 없다.

## 6. 저장소 구조

```
<상위 폴더>/                     ← Git 저장소 아님
├── .venv/                       ← 손상된 기존 가상환경 (보존)
└── carver-quant-lab/            ← Git 저장소 루트
    ├── .gitignore
    ├── .venv/                   ← 표준 개발 가상환경 (무시 대상)
    ├── pyproject.toml
    ├── docs/
    │   ├── architecture/DEVELOPMENT_BASELINE.md
    │   └── quality/TEST_BASELINE.md
    ├── src/
    │   ├── carver_quant/        ← 패키지 (35개 모듈)
    │   └── carver_quant_lab.egg-info/   ← 빌드 산출물 (추적 해제, 무시 대상)
    └── tests/                   ← 39개 파일, 306개 테스트, conftest.py 없음
```

## 7. 환경 재현을 위해 기록할 정보

문제를 보고하거나 기준선을 갱신할 때는 다음 정보를 함께 기록한다.

```sh
git rev-parse HEAD && git status --short
uname -a                                   # OS / 아키텍처
python -c "import sys; print(sys.version); print(sys.executable); print(sys.prefix)"
python -m pip --version
python -m pip list                         # 또는 pip freeze
python -m pip check
python -c "import pandas; pandas.show_versions()"   # pandas·numpy·의존성 세부 버전
pkg list-installed | grep -E '^python'     # Termux만 해당
python -m pytest -q -W error               # 통과 수와 실행 시간
```

추가로 확인할 것: 가상환경 생성 옵션(`--system-site-packages` 사용 여부), 설치 방식(editable 여부).

## 8. 알려진 문제 및 제약

| # | 내용 | 상태 |
|---|---|---|
| K1 | pandas가 의존성으로 선언되지 않음 | ✅ P0-00A에서 해결 (`pandas>=3.0,<4`) |
| K2 | pytest가 테스트 의존성으로 선언되지 않음 | ✅ P0-00A에서 해결 (`.[test]`) |
| K3 | 설치나 PYTHONPATH 없이는 pytest 수집이 실패함 | ✅ "설치 후 실행"을 표준으로 정해 해결. `pythonpath` 설정은 추가하지 않음 |
| K4 | egg-info가 Git에 추적됨 | ✅ 추적 해제 (`git rm --cached`), 파일은 보존 |
| K5 | `.gitignore`에 `build/`, `*.egg-info/` 없음 | ✅ 추가 |
| K6 | 저장소 바깥 `.venv/` 손상 | ⚠ 보존 (삭제 여부는 사용자가 결정). 저장소 내부 `.venv/`를 표준으로 사용 |
| K7 | 의존성 lock 없음. 범위 선언만 있음 | ⚠ 미해결. 범위 안의 다른 pandas 버전(예: 3.1)에서는 `ewm`/`rolling` 수치 결과를 검증하지 않음 |
| K8 | Android에서는 pandas를 PyPI로 설치할 수 없음 | ⚠ 환경 제약. Termux 패키지 + `--system-site-packages`로 우회. Termux가 제공하는 버전 하나만 쓸 수 있음 |
| K9 | Termux의 `python-pandas` 설치 과정에서 python-dateutil이 시스템 site-packages에 pip로 설치됨 | ℹ Termux 패키징 방식. 기록만 함 |

## 9. 미검증 항목

- 일반 Linux (x86_64 / aarch64), macOS, Windows에서의 설치와 테스트
- Python 3.15 이상 (3.13 이하는 `requires-python`에 의해 설치가 거부됨)
- pandas 3.0.6 이외 버전, pytest 9.1.1 이외 버전
- CI 환경 (CI 설정 파일 없음)
