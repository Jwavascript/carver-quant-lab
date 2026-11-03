"""Research 코어 (ADR-0004 §6.2·§6.4, ADR-0010 §6.2 PLANNED `research`. 패키지 이름은 P1-02 한정 선택, Q10-1).

연구용 조정 시계열을 만든다 (조정 가격은 Research 계층만 만든다, ADR-0004 §6.4). `lab.domain`과 표준 라이브러리만 import한다. I/O, 현재
시각 조회, Adapter·다른 코어 import가 없다 (ADR-0010 PK-2·PK-3). 이 파일은 하위 모듈을 import하지 않는다.
"""
