# ShipMail

독립적인 오프라인 조선 전장설계 메일 도우미. 상위 폴더의 GoldWatch 문서(CLAUDE.md/AGENTS.md)는 이 프로젝트에 적용하지 않는다.

- Python 표준 라이브러리 + SQLite + 로컬 정적 UI만 사용. pip 의존성·CDN·외부 폰트 추가 금지.
- 로컬 런타임: Ollama(기본) 또는 LM Studio(OpenAI 호환) — 숫자 루프백 주소만 허용, 리디렉션 미추종.
- 기본 모델을 강제하지 않는다(설정에서 설치된 모델 선택). 1차 후보 qwen3:4b-instruct-2507-q4_K_M, 비교 gemma3:4b. gpt-oss:20b는 선택 비교 후보.
- 금지: 업무자료 외부 전송, 자동 모델 다운로드, 클라우드 대체, 암묵적 메일 저장, 메일/프롬프트 로깅, 모델에 도구 제공.
- 모의 테스트와 실제 모델 평가(evaluate.py)를 구분하고, 검증하지 않은 항목은 docs/VERIFICATION.md에 미검증으로 기록한다.
- 테스트: `py -3 -m unittest discover -s tests`
