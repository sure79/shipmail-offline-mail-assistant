# 새 PC 설치 지시서 (Claude Code용)

> 새 PC에서 이 저장소를 받은 폴더를 Claude Code로 열고
> **"docs/CLAUDE_CODE_SETUP.md 대로 ShipMail을 설치해 줘"** 라고 말하세요.
> 다운로드·설치처럼 되돌리기 어려운 단계는 Claude Code가 사용자에게 먼저 허락을 받습니다.

## 0. 먼저 이해할 것
- **ShipMail**: 조선 전장설계 영어메일을 PC 안에서만 해석·영작하는 오프라인 도우미. 코드는 이 저장소에 **완성본**으로 있으므로 새로 만들 필요 없음.
- **보안 원칙 (반드시 지킬 것)**
  - 업무 메일은 PC 밖으로 나가면 안 됨. 클라우드 AI API(OpenAI·Claude·Gemini 등)를 연결하거나 대체 경로로 쓰지 말 것.
  - 앱(127.0.0.1:8765)과 Ollama(127.0.0.1:11434)는 루프백에서만 동작. `0.0.0.0` 바인딩 금지.
  - 인터넷은 설치(Ollama·모델 다운로드) 때만 사용. 회사 PC라면 보안정책·설치 권한을 우회하지 말고, 막히면 사용자에게 알리고 멈출 것.
- 구성: Python 표준 라이브러리만(pip 불필요) + SQLite + 로컬 HTML + Ollama.

## 1. 설치 순서
1. **사양 확인(읽기만)**: CPU, RAM, GPU(`nvidia-smi`), `py -3 --version` → 사용자에게 요약.
2. **Python 3.11+**: 없으면 사용자 허락 후 python.org 공식 설치 파일(“Add python.exe to PATH” 체크).
3. **설치 스크립트 실행** (저장소 폴더에서):
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
   ```
   - Ollama가 없으면 “설치할까요?”를 묻고, 공식 GitHub 릴리스에서 받아 **SHA256 확인 후** 사용자 폴더에 설치(관리자 권한 불필요, 로그인 불필요).
   - `%USERPROFILE%\.ollama\server.json`에 `disable_ollama_cloud: true`.
   - Ollama를 로컬 전용으로 켜고, 모델이 없으면 “받을까요?”를 물은 뒤 `ollama pull`.
   - 앱 설정(모델·대기 600초), 자동 테스트, 바탕화면 **ShipMail** 바로가기(`start-all.bat`).
   - Claude Code가 대신 실행할 때는 사용자에게 허락을 받은 뒤 `-Yes`를 붙인다(대화형 질문 생략).
4. **모델 선택 기준**
   | 새 PC | `-Model` |
   |---|---|
   | RAM 16GB 이상 | `qwen3:8b` (기본, 정확도 우선) |
   | RAM 8GB | `qwen3:4b-instruct-2507-q4_K_M` (빠르지만 부정문·요일 오역이 잦음 → ⚠ 표시 확인) |
   | NVIDIA VRAM 8GB+ & 드라이버 550+ | `qwen3:8b` (GPU 가속으로 더 빠를 가능성). 더 큰 모델은 `evaluate.bat`로 비교 후 선택 |
   드라이버 업데이트는 사용자 판단·회사 정책 — 임의로 바꾸지 말 것.
5. **학습 자료 옮기기(선택)**: 원래 PC에서 ⚙ 설정 → [전체 백업]으로 받은 JSON이 있으면
   `.\setup.ps1 -Restore <백업.json>` (업무 문장이 들어 있으므로 GitHub에 올리지 말 것).
6. **동작 확인**: 바탕화면 ShipMail → 상단 “모델명 · 로컬 연결됨” → 짧은 메일로 해석·영작.
   선택: `evaluate.bat --model <모델>`(품질), 인터넷을 끊고 `offline-check.bat`(10/10 기대).
7. 실제로 확인한 것과 확인하지 못한 것을 구분해서 사용자에게 보고.

## 2. 인터넷이 막힌 PC
원래 PC의 Ollama 설치 파일과 `%USERPROFILE%\.ollama\models` 폴더를 옮긴 뒤 `setup.ps1`을 실행(모델이 이미 있으면 다운로드하지 않음). 자세한 내용: [OFFLINE_INSTALL.md](OFFLINE_INSTALL.md)

## 3. 과거에 겪은 문제와 해결 (코드에 반영됨)
| 증상 | 원인 → 해결 |
|---|---|
| 화면 오류 후 멈춤 | 앱 2개가 같은 포트 사용 → 포트 독점, 두 번 실행 시 “이미 실행 중” 안내 |
| “모델 출력 검증 실패”, 70초 이상 | 모델이 문장 번호를 `-4`처럼 출력 → 번호 대신 개수·순서로 검증 |
| 요일·부정문 오역 | 4B 한계 → 8B 사용 + 요일 규칙 비교 + 문장 옆 ⚠ 주의 표시 |
| 이름 음역, “최고의 인사로” | 인사말·맺음말·서명은 규칙 처리(AI 미전송) |
| 회신에 원문 문장이 섞이고 “확인 중”이 확정으로 바뀜 | 영작은 한국어만 보고, 미답변 확인은 별도 단계 |
| 한 문장씩 번역하면 영어가 남음 | 메일 전체를 함께 번역하고 스트리밍으로 문장별 표시 |
| 느림 | NVIDIA 드라이버 550 미만이면 CUDA 미사용(Vulkan) → flash attention·KV q8, 모델 미리 로드, 재사용 캐시 |

## 4. 작업 규칙
- `AGENTS.md`/`CLAUDE.md` 규칙 준수. 수정 후 `py -3 -m unittest discover -s tests`.
- 번역 품질은 모의 테스트가 아니라 `evaluate.py`로 실제 모델을 돌려 사람이 판단.
- Windows에서 셸 heredoc으로 파이썬을 패치하면 `\b`, `\n` 같은 백슬래시가 깨진 적이 있음 → 편집 도구나 패치 파일 사용.
