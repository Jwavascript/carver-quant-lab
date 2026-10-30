"""Data Boundary 코어 (ADR-0004 §6.2, ADR-0010 §6.2 PLANNED `marketdata`. 패키지 이름은 P1-01 한정 선택, Q10-1).

입력 검증, 정규화된 시장 관측값의 PIT 뷰, 품질 판정을 순수 함수로 둔다. `lab.domain`과 표준 라이브러리만 import한다. I/O, 현재 시각
조회, Adapter import가 없다 (ADR-0004 R-3, ADR-0010 PK-2·PK-3). 이 파일은 하위 모듈을 import하지 않는다.
"""
