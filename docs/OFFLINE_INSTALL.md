# 오프라인 설치 · 파일 반입 안내

원칙: **인터넷이 되는 승인된 PC에서 공개 파일만 준비**하고, 회사 절차에 따라 업무 PC로 반입합니다. 업무 PC에서는 업무자료 처리 중 인터넷이 필요 없습니다. 회사의 설치 권한·반입 정책을 우회하지 마세요.

## 1. 반입 파일 목록

| 파일 | 출처(공식) | 크기(대략) | 필수 |
|---|---|---|---|
| `ShipMail-1.1.zip` | `make-package.ps1`로 생성 | 100KB 미만(런타임 제외) | 필수 |
| Python 3.11+ 설치 파일 **또는** Windows embeddable zip | python.org | 25MB / 10MB | 둘 중 하나 |
| Ollama Windows 설치 파일 `OllamaSetup.exe` | ollama.com/download (개발 시점 최신 v0.34.3) | 약 1GB 이상 | Ollama 사용 시 |
| 모델 파일 (아래 3절) | ollama.com/library 또는 Hugging Face | 2.5~3.3GB | 필수(1개 이상) |
| LM Studio 설치 파일 | lmstudio.ai | 약 500MB+ | Ollama 대신 쓸 때만 |

반입 전 각 파일의 SHA256을 기록해 두면 반입 후 동일성 확인에 쓸 수 있습니다: `Get-FileHash 파일명`.

## 2. Python 준비
- **설치형**: python.org 설치 파일로 설치(“py launcher” 포함). `start.bat`이 `py -3`로 실행합니다.
- **휴대용(설치 권한이 없을 때)**: python.org의 *Windows embeddable package (64-bit)* zip을 ShipMail 폴더 안 `runtime\`에 풀면 `start.bat`이 `runtime\python.exe`를 우선 사용합니다. 이 방식에서 앱이 쓰는 표준 모듈(sqlite3, http.server)은 embeddable 패키지에 포함되어 있으나, **이 조합은 개발 중 실제 실행 검증을 하지 않았습니다** — 반입 후 `run-tests.bat`으로 확인하세요.
- 앱은 pip 패키지를 쓰지 않으므로 `pip install`이 필요 없습니다.

## 3. 모델 반입 (Ollama)

### 방법 A — 인터넷 PC에서 받아 모델 폴더 복사
1. 인터넷 PC에 같은 버전의 Ollama 설치 → `ollama pull qwen3:4b-instruct-2507-q4_K_M`
2. `%USERPROFILE%\.ollama\models` 폴더 전체(`blobs`, `manifests`)를 업무 PC의 같은 위치로 복사
   (다른 위치를 쓰려면 환경 변수 `OLLAMA_MODELS`로 지정 — Ollama 공식 FAQ에 있는 설정)
3. 업무 PC에서 `ollama list`로 확인
> 폴더 복사 방식은 널리 쓰이지만 Ollama 공식 문서에 반입 절차로 명시된 것은 아닙니다. 반입 후 반드시 `ollama list`와 앱 상태 표시로 확인하세요.

### 방법 B — GGUF 파일로 가져오기 (공식 import 기능)
1. 승인된 경로(Hugging Face 공식 저장소 등)에서 GGUF 파일(예: Q4_K_M) 다운로드, 라이선스 확인
2. 같은 폴더에 `Modelfile` 작성: `FROM ./모델파일.gguf`
3. `ollama create 원하는이름 -f Modelfile`
> 이 경우 채팅 템플릿이 자동으로 맞지 않을 수 있습니다. 가능하면 방법 A를 권장합니다.

## 4. Ollama 로컬 전용 실행
`start-ollama-local.bat`이 다음을 설정하고 `ollama serve`를 실행합니다(모델 다운로드는 하지 않음):

| 설정 | 의미 |
|---|---|
| `OLLAMA_HOST=127.0.0.1:11434` | 이 PC에서만 접속 (기본값도 127.0.0.1) |
| `OLLAMA_NO_CLOUD=1` | 클라우드 모델·웹검색 기능 끔 (공식 FAQ). `~/.ollama/server.json`의 `disable_ollama_cloud`로도 설정 가능 |
| `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1` | 메모리 절약, 순차 처리 |

- 트레이의 Ollama 앱이 이미 실행 중이면 포트가 겹칩니다. 트레이 앱을 종료하고 이 스크립트를 쓰거나, 트레이 앱 설정에서 네트워크 노출을 끈 상태로 사용하세요.
- **자동 업데이트**: Ollama Windows 앱은 업데이트를 자동 다운로드합니다(공식 FAQ). 공식 문서에서 끄는 옵션은 확인하지 못했습니다. 업무 PC에서는 회사 방화벽/정책으로 외부 접속을 차단하는 방식을 IT 담당자와 협의하세요. ShipMail 자체는 업데이트 확인을 하지 않습니다.

## 5. 반입 후 로컬 동작 확인 (네트워크 차단 상태에서)
1. 랜선/와이파이를 끊습니다.
2. `start-ollama-local.bat` → `start.bat`
3. 상단에 `모델명 · 로컬 연결됨`이 나오는지 확인
4. 짧은 메일로 해석 → 영작 → 복사, 자료실 추가/검색, 백업 → 복원까지 해 봅니다.
5. `evaluate.bat --model 모델명` 실행 후 `evals\results\` 보고서의 사람 판정 칸 작성
6. `run-tests.bat` 실행
