# hancharacter 한국어 가이드

번역에서 **캐릭터의 말투가 뭉개지는 것**을 기계적으로 잡아내는 도구입니다.

원문 캐릭터가 쓰는 말투 표지(役割語 / 말투 어미)를 측정해서 계약으로 봉인하고, 번역이 그 목소리를 **지웠거나**(LOSS) **없던 걸 만들어냈으면**(INVENTION) 거부합니다.

Python 3.9+ 표준 라이브러리만 사용합니다. 설치도, 네트워크 접속도 없습니다.

---

## 1. 왜 필요한가

일본어 원문:

```
ハットリ: これは主命でござる。
ハットリ: わかった。
```

`でござる`는 하토리가 쓰는 고유한 말투입니다. 두 문장 중 한 문장에만 나옵니다 — 밀도 0.5.

번역이 이렇게 나오면:

```
하토리: 이것이 주인의 명입니다.
하토리: 알았습니다.
```

문장 의미는 맞습니다. 그런데 하토리가 **다른 캐릭터와 구별되지 않게** 됐습니다. 말투 밀도 0.0. 이게 LOSS입니다.

반대로 이렇게 나오면:

```
하토리: 이것이 주인의 명이오.
하토리: 알았소.
```

원문은 2문 중 1문에만 표지가 있는데 번역은 2문 모두에 넣었습니다. 밀도 1.0. **과포화도 결함입니다** — 원문에 없던 개성을 발명한 것이고, 캐릭터가 기계적으로 들리게 됩니다.

`hancharacter`는 이 둘을 모두 거부합니다.

## 2. 30초 사용법

```sh
git clone https://github.com/yazzang-homelab/hancharacter.git
cd hancharacter

# 카탈로그 상태 확인
./bin/hancharacter corpus

# 자막/PO/CSV 등 실제 파일 읽어서 화자별 구획 보기
./bin/hancharacter segment --profile profiles/crimson_fixture.json --rows your.srt

# 자막 길이 예산 검사
./bin/hancharacter budget --profile profiles/crimson_fixture.json --rows your.srt

# 합성 픽스처로 집행 동작 확인 (평탄화는 실패, 충실한 번역은 통과)
./bin/hancharacter e2e --scenario seeded-loss --out /tmp/hc-loss           # exit 1
./bin/hancharacter e2e --scenario faithful-intermittent --out /tmp/hc-ok   # exit 0
```

지원 입력 포맷: 일반 텍스트, JSON, CSV, PO(gettext), XLIFF, SRT, VTT, ASS, EPUB, 그리고 읽기 전용 호스트 JSON. 확장자로 자동 판별하고 `--format`으로 강제할 수 있습니다. **선언되지 않은 확장자는 조용히 JSON으로 읽지 않고 큰 소리로 실패합니다** — 조용한 폴백이 어댑터 하나가 통째로 죽어 있는 걸 두 단계나 숨겼던 적이 있습니다.

## 슬래시 명령으로 쓰기 (GJC / Claude Code / Codex)

세 도구 모두 `name` + `description` 프론트매터를 가진 `SKILL.md`를 읽습니다. 정본은
`skills/hancharacter/SKILL.md` 하나이고, 설치 스크립트가 각 도구의 스킬 루트에
심볼릭 링크를 겁니다 — 레포를 pull 하면 세 도구에 동시에 반영됩니다.

```sh
./bin/install-skill            # 설치돼 있는 도구에만 설치
./bin/install-skill --check    # 무엇이 설치됐는지만 보고
./bin/install-skill --copy     # 심볼릭 링크 대신 복사
./bin/install-skill --project  # 현재 프로젝트의 ./.gjc ./.claude ./.codex 에 설치
./bin/install-skill --uninstall
```

설치 위치:

| 도구 | 경로 |
|---|---|
| GJC (가재코드) | `~/.gjc/skills/hancharacter/SKILL.md` |
| Claude Code | `~/.claude/skills/hancharacter/SKILL.md` + `~/.claude/commands/hancharacter.md` |
| Codex | `~/.codex/skills/hancharacter/SKILL.md` |

`GJC_HOME` / `CODEX_HOME` 환경변수를 설정했으면 그쪽을 따릅니다. 설치되지 않은 도구는
건너뛰며, 없는 도구의 설정 트리를 새로 만들지 않습니다.

설치 후:

```
/hancharacter 이 자막 파일에서 화자별 말투 일관성 검사해줘
/hancharacter your.srt 평탄화된 대사 찾아줘
/hancharacter 하오체 계약을 translator_declared 로 봉인해서 LOSS 잡아줘
```

## 3. 핵심 개념 네 가지

### 밀도(density), 100%가 아니라

가장 흔한 오해입니다. 계약은 **모든 대사**를 지배하지만, 그게 "표지가 100% 문장에 나온다"는 뜻이 **아닙니다.**

충실한 번역은 원문에서 **실제로 측정된 밀도**를 재현합니다. 원문 캐릭터가 표지를 간헐적으로 쓰면 번역도 간헐적이어야 합니다. 모든 문장에 밀어넣는 건 그 자체로 결함입니다.

### 두 가지 권위(authority)

계약은 무엇을 근거로 렌더링을 집행하는지 **반드시 선언**해야 합니다. 기본값은 없습니다 — 선언하지 않은 계약은 거부됩니다.

| | `precedent_backed` | `translator_declared` |
|---|---|---|
| 요구 증거 | canonical 유형 (출판 선례 포함) | 원문쪽 증거만 |
| 주장하는 것 | "이 렌더링이 확립된 관례다" | "역자가 선언한 렌더링이 충실히 적용됐다" |
| 쓰는 경우 | 이미 번역 관례가 있는 작품 | **첫 번역, 신작, 오리지널 캐릭터** |

두 번째 경로가 있는 이유: 출판 선례를 요구하면 **처음 번역되는 작품의 새 말투를 원리상 관리할 수 없습니다.** 그런데 그게 실무에서 가장 흔한 경우입니다. 그리고 표지가 삭제됐는지 감지하는 데는 "올바른 대체물이 무엇인가"를 알 필요가 전혀 없습니다.

약한 경로를 정직하게 유지하는 두 가지 장치:

- **adopted 선례 요건은 뺐지만 rejected 선례 거부는 남겼습니다.** 출판 선례가 이미 "이건 평탄화다"라고 보여준 렌더링을 역자가 선언할 수는 없습니다.
- 권위는 **봉인 해시에 결박**되고 모든 게이트 요약에 각인됩니다. 약한 주장을 강한 주장으로 고쳐 쓰거나 오독할 수 없습니다.

집행 자체는 권위로 분기하지 않습니다. LOSS·INVENTION·일관성·배타성은 두 경로에서 **구조적으로 동일**하며, `gates.py`의 어떤 조건문도 권위를 읽지 않는다는 것을 AST로 검증합니다.

### 증거 사다리

유형은 `observed` → `provisional` → `canonical` 순서로 올라갑니다. canonical이 되려면 유형당:

- 용례 8개 이상, 독립 출처 3개 이상
- 1차/2차 출처 1개 이상
- 채택된 선례 1개 이상
- 검토자 2인 간 카파 ≥ 0.60, **그리고 판정이 안정적**
- 인간 확인 1개 이상, 미해결 선례 모순 없음

카파에는 안정성 요건이 붙어 있습니다: 판정 하나를 뒤집었을 때 floor를 넘나들면 인정하지 않습니다. `KAPPA_FLOOR`만으로는 **동의하기 쉬운 행을 덧붙여서** 넘을 수 있기 때문입니다(실제로 이 저장소에서 그렇게 넘어간 적이 있고, 그 사실이 README에 공표돼 있습니다).

### 어댑터 표면(surface)

측정은 원문 그대로가 아니라 **정규화된 표면**에 대해 수행됩니다. 말풍선 구분자, 태그, ASS의 `\N` 줄바꿈, 루비(후리가나)가 표지와 문장 끝 사이에 끼면 `$` 앵커가 죽습니다. 이 계열 결함이 이 저장소에서 **일곱 번** 발견됐습니다. 하나라도 놓치면 평탄화 게이트가 조용히 발화하지 못하거나, 반대로 충실한 번역을 오탐합니다.

## 4. 현재 상태를 정직하게

**출하 카탈로그로는 `precedent_backed` 계약을 봉인할 수 없습니다. canonical 유형이 0/10입니다.**

이건 버그가 아니라 게이트가 닫혀 있다는 정직한 보고입니다. `./bin/hancharacter corpus`가 유형별로 무엇이 부족한지 정확히 출력합니다.

가장 가까운 유형은 `ja_hao_gozaru`입니다:

```
ja_hao_gozaru  provisional  용례 12  출처 4  1·2차 1  선례 0  카파 0.600
    미달: adopted precedents 0 < 1
    미달: 카파가 floor 를 만족하지만 판정이 불안정 (56개 뒤집기가 floor 를 넘김)
```

선례를 찾으려 했고 **실패했습니다.** 시도한 것과 왜 부족했는지는 `catalogue/SOURCES.md`에 전부 기록돼 있습니다. 있을 법한 인용을 만들어내는 것보다 못 찾았다고 적는 게 이 도구의 존재 이유에 부합합니다.

그래서 지금 쓸 수 있는 건 `translator_declared` 경로입니다. 역자가 렌더링을 선언하면, 도구가 그것이 원문 밀도대로·일관되게·배타적으로 적용됐는지 집행합니다.

## 5. 설계 원칙

이 저장소는 다음을 위반하지 않습니다. 개발 중 실제로 이 원칙들 때문에 여러 번 결과를 되돌렸습니다.

- **모든 판정은 산출물에서 재도출 가능해야 한다.** 모델 출력이 게이트를 승인하지 않습니다.
- **건너뛸 수 있는 게이트는 게이트가 아니다. 충실한 작업에 발화하는 게이트도 똑같이 망가진 것이다.**
- **꺼진 상태가 기본값인 가드는 가드가 아니다.** 주입을 잊으면 통과가 아니라 실패합니다.
- **통과시키려고 경계값을 넓히지 않는다.** 실제로 승격 하나를 스스로 되돌렸습니다 — 승격을 받치던 선례가 형제 선례들보다 느슨한 기준을 쓰고 있었고, 기준을 일관 적용하니 canonical이 사라졌습니다.
- **LOSS와 INVENTION 둘 다 결함이다.**
- **자동화할 수 없는 주장은 한계로 기록하고, 커버리지로 주장하지 않는다.**

## 6. 아직 안 되는 것

README의 선언된 한계 절에 전부 있습니다. 요약하면:

- **JA/EN → KO 전용.** 원문 측정 플러그인은 `ja`/`en`, 타깃 실현은 `ko`만 있습니다. 타깃 언어 추가는 언어마다 별도 작업입니다.
- 카탈로그 유형 14개 중 13개가 일본어 역할어입니다 — 범용 유형론이 아니라 JA 유형론입니다.
- `prose_fidelity` 모드에서 밀도는 보고만 하고 강제하지 않습니다.
- 엔진이 감싸는 행이나 자유형식 행은 길이 상한을 증명할 수 없습니다.
- 방언의 의미 충실도는 측정 불가입니다.
- 검토자 신원이 인증되지 않고 산출물에 서명이 없습니다. 카파는 여기서 **인간 평가자 간 신뢰도가 아니라 코딩 스킴의 명확성**을 재는 값으로 읽어야 합니다.

## 7. 문서 지도

| 파일 | 내용 |
|---|---|
| `README.md` | 영어 개요, 선언된 한계(테스트로 못박힘) |
| `docs/quickstart.md` | 명령별 사용법 |
| `docs/evidence.md` | 증거 규칙과 현재 증거 상태 |
| `docs/review-protocol.md` | 증거를 제출하는 절차 |
| `docs/catalogue.md` | 유형·실현을 추가·수정하기 전에 읽을 것 |
| `docs/gates.md` | 게이트 코드와 그 의미 |
| `catalogue/SOURCES.md` | 인용된 출처, **그리고 확인 실패해 제외된 출처** |
| `docs/spine.md` | 내부 구조 |

문서가 거짓이 되는 것을 막기 위해 `tests/test_docs.py`가 못박힌 문장을 글자 그대로 검증하고, 모든 CLI 하위명령과 모든 축, `docs/gates.md`의 모든 게이트 코드를 실제 코드와 대조합니다. 사실이 바뀌면 문서가 **깨집니다.**

## 8. 기여할 때

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -t .   # 522 tests, 0 skips, 0 warnings
./bin/hancharacter types --lint
./bin/hancharacter corpus --lint
./bin/hancharacter precedents --lint
./bin/hancharacter dialect --lint
./bin/hancharacter measure
```

전부 통과해야 합니다. 그리고:

- 동결 상수(`COVERAGE_FLOOR_X=0.70`, `KAPPA_FLOOR=0.60`, 인용 상한 120자/1000자 등)를 바꾸지 마십시오.
- 코퍼스에는 표지 패턴·인용·최소 인용문만 넣습니다. 대본 원문을 대량으로 넣지 마십시오. 기계적으로 강제됩니다(행당 120자, 작품당 1000자, 덤프 감지).
- 게이트를 통과시키려고 픽스처를 면제하지 말고, 픽스처가 강화된 규칙을 **실제로 충족**하게 올리십시오.

## 라이선스

`LICENSE` 참조.
