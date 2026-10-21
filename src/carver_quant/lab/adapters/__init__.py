"""Adapter 계층 (ADR-0010 §6.2 PLANNED, PK-5. 패키지 이름은 Slice 4 한정 선택, Q10-1).

저장소 같은 외부 자원과의 경계다. `lab.domain`, 이 패키지의 모듈, 표준 라이브러리만 import한다. 금융 계산 코어(`accounting`)와 엔진을
import하지 않고 (PK-5), 금융 계산 코어도 이 패키지를 import하지 않는다 (PK-3). 이 파일은 하위 모듈을 import하지 않는다.
"""
