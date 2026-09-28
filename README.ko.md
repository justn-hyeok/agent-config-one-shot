# agent-config-one-shot

[English](README.md) | 한국어

한 번의 명령으로 여러 코딩 에이전트의 공통 스킬과 설정 경로를 연결합니다.

원하는 하네스에 자신의 스킬을 연결하고, 각 하네스의 원래 설정을 한곳에서
확인·수정할 수 있게 합니다. 연결 상태를 진단하거나 설치 전 상태로 복구하는
기능도 제공합니다. 인증, 세션, 프로바이더별 형식, 모델 선택, 플러그인 캐시는
각 하네스가 계속 관리합니다.

**v0.2는 Python 3.11 이상의 macOS·Linux 환경을 지원합니다.**
Windows 설치는 아직 지원하지 않습니다. 이 도구는 에이전트 바이너리를
실행하거나 유료 모델 요청을 보내지 않습니다.

## 릴리스 설치

```sh
uv tool install --upgrade https://github.com/justn-hyeok/agent-config-one-shot/releases/download/v0.2.1/agent_config_one_shot-0.2.1-py3-none-any.whl
agent-config-one-shot install
agent-config-one-shot doctor
```

릴리스에는 소스 압축 파일과 SHA256 체크섬도 포함되어 있습니다.
wheel을 설치하면 CLI를 바로 사용할 수 있습니다. 아래 예시는 소스 저장소를
내려받은 상태를 기준으로 합니다.

## 소스에서 사용하기

```sh
uv tool install .
agent-config-one-shot list
agent-config-one-shot plan --harness claude,copilot --skills-source ./examples/skills
agent-config-one-shot install --harness claude,copilot --skills-source ./examples/skills
agent-config-one-shot doctor
```

이미 `~/.agents/skills`에 스킬을 관리하고 있다면 다음 명령으로 연결할 수 있습니다.

```sh
./setup.sh --harness claude,cursor-cli,copilot,amp
```

터미널에서 `--harness`를 생략하면 아래 선택 화면이 열립니다.
터미널이 없는 환경에서는 기존처럼 실행 파일이 감지된 하네스를 선택합니다.
`--harness all`은 CLI 설치 여부와 관계없이 11개 어댑터를 모두 선택합니다.
이 선택은 설정 경로를 연결하는 작업입니다. 각 CLI의 설치·로그인은 별도로
진행해야 합니다.

소스 저장소의 `setup.sh`는 `uv`가 필요하며, 잠금 파일에 지정된 의존성으로
동일한 CLI를 실행합니다. CLI를 설치한 뒤에는 `agent-config-one-shot install`을
직접 사용하면 됩니다.

아직 패키지 레지스트리에는 게시하지 않았습니다. 소스 저장소나 검증된 wheel로
설치하세요. `uv` 외에도 `pipx install .` 또는 `python -m pip install .`로
CLI를 설치할 수 있습니다.

## TUI에서 하네스 선택하기

```sh
agent-config-one-shot install
```

11개 하네스와 각 CLI의 감지 여부를 체크 목록으로 보여줍니다.
감지된 CLI는 미리 선택되어 있으며, 원하는 항목을 추가하거나 해제할 수 있습니다.
방향키로 이동하고 Space로 체크한 뒤 Enter로 선택한 대상의 설정을 연결합니다.
`a`는 전체 선택, `n`은 선택 해제, `d`는 감지된 CLI만 선택합니다.
Esc·`q`·Ctrl-C로 취소하면 설정이나 관리 파일을 만들지 않습니다.
아무것도 선택하지 않고 Enter를 누르면 선택 화면을 유지합니다.

`plan`과 `install --dry-run`에서도 같은 화면으로 읽기 전용 계획을 확인할 수 있습니다.
Enter로 대상을 확정하기 전에는 설정을 변경하지 않습니다.
감지되지 않은 CLI를 선택해도 연결하는 것은 설정 경로이며, CLI 설치·로그인은 별도입니다.

스크립트에서는 `--harness`로 대상을 지정하거나 `--non-interactive`를 사용하세요.

```sh
agent-config-one-shot install --harness claude,copilot
agent-config-one-shot install --non-interactive
agent-config-one-shot plan --interactive --harness claude
```

`--interactive`는 선택 화면을 강제로 열고, 지정한 ID를 초기 선택으로 사용합니다.
터미널 입출력이 필요하며, `--json`과 함께 사용할 수 없습니다.
`--json`은 화면 없이 실행합니다. 터미널이 44열 × 10행보다 작으면 창 크기를
늘리거나 취소할 수 있으며, 충분한 공간이 생기기 전에는 선택을 진행하지 않습니다.

## 명령어

| 명령어 | 기능 |
| --- | --- |
| `list` | 지원 하네스와 실행 파일 감지 결과 표시 |
| `plan` | 파일을 생성하지 않고 변경 계획 확인 |
| `install --dry-run` | 설치 명령에서 변경 계획만 확인 |
| `install` | 참조와 스킬 어댑터를 생성하고 작업 기록 저장 |
| `doctor` | 관리 중인 연결, 링크 대상, 중단된 작업 진단 |
| `restore` | 변경 여부를 확인한 뒤 이 도구가 만든 연결 복구 |
| `recover` | 중단된 설치를 되돌리거나 중단된 복구를 완료 |

`--json`은 상태와 경로를 JSON으로 출력합니다.
`--home /path`와 `--root /path`는 별도의 홈 디렉터리와 관리 디렉터리를 지정합니다.
이 옵션은 명령어 앞뒤 모두 사용할 수 있으며, 셸의 `HOME` 환경변수는 바꾸지 않습니다.

## 지원 하네스

| ID | 하네스의 개인 스킬 경로 | 공통 스킬 탐색 방식 |
| --- | --- | --- |
| `codex` | `~/.codex/skills` | `~/.agents/skills` 직접 탐색 |
| `claude` | `~/.claude/skills` | 스킬별 참조 연결 |
| `cursor-cli` | `~/.cursor/skills` | 공통 경로 직접 탐색 |
| `copilot` | `~/.copilot/skills` | 공통 경로 탐색, 필요 시 메타데이터 어댑터 사용 |
| `amp` | `~/.config/amp/skills` | 공통 경로 직접 탐색 |
| `cline` | `~/.cline/skills` | 공통 경로 직접 탐색 |
| `opencode` | `~/.config/opencode/skills` | 스킬별 참조 연결 |
| `devin` | `~/.config/devin/skills` | 스킬별 참조 연결 |
| `omp` | `~/.omp/agent/skills` | 스킬별 참조 연결 |
| `gjc` | 원래 스킬 경로를 실제 디렉터리로 유지 | 별도의 관리 스킬 경로 등록 |
| `command-code` | `~/.commandcode/skills` | 스킬별 참조 연결 |

`--skills-source`로 `~/.agents/skills` 외의 경로를 지정하면 선택한 하네스의
개인 스킬 경로에 연결합니다. 공통 전역 경로를 다른 곳으로 바꾸지 않으므로,
이 설치 작업을 통해 선택하지 않은 하네스에 해당 소스가 추가되지는 않습니다.
다만 각 하네스가 자체적으로 다른 도구의 스킬을 탐색하는 규칙은 적용될 수 있습니다.

소스는 `SKILL.md`가 들어 있는 단일 스킬 디렉터리이거나, 바로 아래에 스킬
디렉터리들이 있는 상위 디렉터리여야 합니다. 같은 이름의 기존 내용은 보존합니다.
대상이 다른 링크나 실제 디렉터리가 이미 있으면 덮어쓰지 않고 충돌로 처리합니다.

## 설정 소유권과 폴더 구조

기본 관리 디렉터리는 `~/.agents/agent-config-one-shot`입니다.
이 디렉터리는 사용자만 접근할 수 있도록 만듭니다.

```text
agent-config-one-shot/
├── harnesses/<id>/     # 하네스의 원래 설정·사용자 파일에 대한 참조
├── compat/copilot/    # 원본 절차를 참조하는 메타데이터 어댑터
├── state.json         # 이 도구가 만든 변경과 설치 범위
├── journals/          # 중단 후 재개할 수 있는 작업 기록
└── backups/           # 필요한 원본 설정 변경을 위한 비공개 백업
```

각 하네스의 원래 설정 파일이 계속 기준이 됩니다. 중앙 참조는 기존 파일을
직접 수정하는 저장 방식과 파일을 교체하는 저장 방식 모두에서 원래 파일을
따라갑니다. 설정값을 이 소프트웨어 패키지에 복사하지 않습니다.
존재하는 설정 파일만 참조하며, 아직 없는 선택적 파일은 표시합니다.
CLI가 해당 파일을 생성한 뒤 다시 실행하면 연결할 수 있습니다.

인증 저장소, 세션, 캐시, 계정 정보, 권한 데이터베이스, 설치된 플러그인은
가져오지 않습니다. **배포 파일을 만들 때 중앙 심볼릭 링크의 실제 대상 파일을
따라가서 복사하면 안 됩니다.** 비공개 백업은 로컬 복구 자료이며 배포 대상이
아닙니다. 배포 패키지에는 이 도구, 예제, 테스트만 포함됩니다.
개인 설정이나 제삼자의 스킬 묶음은 함께 배포하지 않습니다.

### 하네스별 예외 처리

- **GJC:** 원래 사용자 스킬 경로가 다른 곳을 가리키면 거부하므로 실제
  디렉터리로 유지합니다. 대신 `skills.customDirectories`에 관리 경로를 추가합니다.
  YAML을 다시 저장할 때 관련 없는 설정과 주석을 보존하고, 원본 파일은 비공개로
  백업합니다. 설치 후 사용자가 원본 파일을 수정했다면 복구 시 교체를 거부합니다.
  다른 설정과 공유하는 YAML 맵·리스트는 변경 전에 분리합니다. 중복 YAML 앵커나
  관리 대상 스킬 맵 내부의 병합 키는 설정값을 출력하지 않고 거부합니다.
  이것이 이 도구가 하네스의 원래 환경설정을 직접 수정하는 유일한 경우입니다.
- **Copilot:** 배열 형태의 `argument-hint`를 거부하므로, 작은 어댑터가 메타데이터를
  호환되는 형태로 바꿉니다. 어댑터는 원래 스킬 절차와 리소스를 참조하며,
  공통 스킬 본문은 복사하거나 다시 작성하지 않습니다.

## 재실행과 복구

같은 설치를 다시 실행해도 일치하는 링크와 파일은 중복 생성하지 않습니다.
잠금으로 동시에 실행되는 변경 작업을 순서대로 처리하고, 원래 파일을 바꾸기
전에 충돌을 확인합니다. 각 변경의 원래 상태와 예상 상태를 기록하며,
실제 변경 전에 작업 기록을 저장합니다.

설치 중 오류가 발생하면 해당 작업을 되돌립니다. 프로세스가 강제로 종료되면
`doctor`가 미완료 기록을 알려주고, `recover`가 실제 파일 상태와 기록을 확인해
설치를 되돌리거나 중단된 복구를 완료합니다. 다른 프로그램이 수정한 내용은
덮어쓰지 않고 작업을 거부합니다. 로컬 작업 기록은 복구를 위한 자료입니다.
관리 파일을 직접 수정할 수 있는 사람에 대한 보안 경계는 아닙니다.

GJC 설정 파일은 변경 전 파일을 설정 옆의 비공개
`.agent-config-one-shot-<transaction>-<operation>` 디렉터리에 보존합니다.
새 파일은 원래 경로가 비어 있을 때만 연결하므로, 동시에 저장된 파일을
덮어쓰지 않습니다. 이 과정에서 설정 경로가 잠깐 비어 있을 수 있으며,
이동 중 종료되면 보존 파일로 복구합니다. 다른 프로그램이 이미 열어둔 파일에
뒤늦게 저장한 내용도 보존 파일에 남고, `doctor`가 수동 확인 대상으로 알립니다.
이 복구 자료는 `restore` 후에도 남으며 외부로 내보내면 안 됩니다.
설정 링크의 대상 폴더는 미리 존재해야 하고 원래 설정은 관리 루트 밖에 있어야 합니다.
작업 기록과 백업 폴더는
심볼릭 링크가 아닌 실제 디렉터리여야 합니다.

Copilot 원본 스킬의 메타데이터가 바뀌면 설치를 다시 실행해 생성 어댑터를
갱신할 수 있습니다. 생성 어댑터를 직접 수정한 경우에는 덮어쓰지 않습니다.
`doctor`는 갱신되지 않은 메타데이터도 알려줍니다.
갱신은 같은 원본 경로를 유지합니다. 이름이 같지만 원본 경로가 다른 스킬은
충돌로 처리하므로, 다른 이름을 쓰거나 기존 연결을 먼저 복원해야 합니다.

`restore`는 모든 복구 대상을 먼저 확인합니다. 생성한 링크와 어댑터를 제거하고,
설치 후 변경되지 않은 원래 설정을 복구합니다. 새로 추가한 사용자 파일과
디렉터리는 보존하며, 백업과 작업 기록도 남깁니다.
원래 설정이 변경됐거나 링크 대상이 바뀌었다면 복구를 시작하기 전에 중단합니다.

## 검증 범위

`doctor`는 파일 시스템의 연결만 확인합니다. 로그인, 모델 접근 권한,
각 스킬의 실제 호출, 모든 MCP 연결이 성공한다는 뜻은 아닙니다.
하네스 버전에 따라 달라지는 어댑터는 동작이 바뀔 때 해당 CLI의 탐색·저장
방식도 다시 검증해야 합니다.

개발 및 격리된 CLI 테스트는 다음과 같이 실행합니다.

```sh
uv sync
uv run python -m unittest discover -s tests -v
uv build
```

테스트는 임시 홈 디렉터리를 사용하며 개발자의 실제 에이전트 설정에는 적용하지
않습니다. 공개 패키지 배포와 GitHub CI의 성공 여부는 별도의 증거로 확인해야 합니다.

## 참고 자료

- [Agent Skills 형식](https://agentskills.io/specification)
- [Codex 스킬](https://learn.chatgpt.com/docs/build-skills)
- [Claude 스킬](https://code.claude.com/docs/en/skills)
- [Cursor 스킬](https://cursor.com/docs/skills)
- [Copilot 설정](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference)
- [Amp 스킬](https://ampcode.com/docs/customize/skills)

GJC·OMP·Command Code·Devin 포크의 경로는 이 프로젝트의 기반이 된 로컬 검증
어댑터를 따릅니다. 해당 하네스의 프로바이더 인증 정보나 스키마를 하나의 공통
설정 형식으로 일반화하지 않습니다.
