---
name: hancharacter
description: 번역에서 캐릭터 말투(役割語/말투 어미)가 뭉개지는 것을 기계적으로 잡는다. 원문 캐릭터의 말투 표지를 측정해 계약으로 봉인하고, 번역이 그 목소리를 지웠거나(LOSS) 없던 걸 만들어냈으면(INVENTION) 거부한다. 자막·PO·XLIFF·CSV·EPUB·ASS 등 실제 파일을 읽는다. 게임/만화/웹툰/자막/소설 번역의 캐릭터 목소리 보존을 검사·집행할 때, 또는 기존 번역의 말투 일관성을 감사할 때 사용.
argument-hint: "<작업 설명> (예: 이 자막 파일에서 화자별 말투 일관성 검사 / 하오체 계약 봉인해서 평탄화 잡아줘)"
---

# hancharacter — 말투 보존 집행

번역이 캐릭터의 **목소리**를 지웠는지 기계적으로 판정한다. 의미가 맞아도 하토리가 다른 캐릭터와 구별되지 않게 되면 결함이다.

- 저장소: `/root/tmp/hancharacter` (공개: https://github.com/yazzang-homelab/hancharacter)
- 실행: 체크아웃에서 `./bin/hancharacter <명령>` — 설치·네트워크 없음, Python 3.9+ 표준 라이브러리만
- 한국어 가이드: `GUIDE.ko.md` · 영어 개요와 선언된 한계: `README.md`

이름이 비슷한 `hanpatch` 스킬과는 별개다. `hanpatch`는 ROM 한글패치 파이프라인이고, 이쪽은 **말투 보존 측정·집행**이다.

## 먼저 해야 할 일

작업을 시작하기 전에 반드시 현재 증거 상태를 읽는다. 이 도구는 게이트가 닫혀 있을 때 닫혀 있다고 보고하는 것이 정상 동작이다.

```sh
cd /root/tmp/hancharacter
./bin/hancharacter corpus          # 유형별 승격 상태와 미달 기준
```

## 명령

```sh
./bin/hancharacter version | profile | schema --kind K --file F
./bin/hancharacter measure                       # 플러그인 골든 다이제스트 검증
./bin/hancharacter segment --profile P --rows F   # 화자 구획·귀속·적격성·커버리지
./bin/hancharacter budget  --profile P --rows F   # 자막 CPL/CPS·말풍선 용량
./bin/hancharacter types --lint | corpus --lint | precedents --lint | dialect --lint
./bin/hancharacter review --out DIR --format html
./bin/hancharacter e2e --profile P --rows F --out DIR
./bin/hancharacter e2e --scenario seeded-loss --out DIR          # exit 1 이어야 정상
./bin/hancharacter e2e --scenario faithful-intermittent --out D  # exit 0 이어야 정상
```

입력 포맷 10종: `plain_text json csv po xliff srt vtt ass epub host_json`. 확장자로 판별하고 `--format`으로 강제한다. **선언되지 않은 확장자는 조용히 JSON으로 읽지 않고 큰 소리로 실패한다.**

## 개념 네 가지

**밀도, 100%가 아니다.** 계약은 모든 대사를 지배하지만 표지가 100% 문장에 나온다는 뜻이 아니다. 충실한 번역은 원문에서 **측정된 밀도**를 재현한다. 모든 문장에 밀어넣는 과포화는 그 자체로 결함(INVENTION)이다.

**두 가지 권위.** 계약은 무엇을 근거로 집행하는지 반드시 선언한다. 기본값 없음 — 선언 없으면 거부.
- `precedent_backed` — canonical 유형 필요(출판 선례 포함). "이 렌더링이 확립된 관례다"를 주장.
- `translator_declared` — 원문쪽 증거만 필요. **어느 렌더링이 옳은지 주장하지 않는다.** 역자가 선언한 렌더링이 원문 밀도대로·일관되게·배타적으로 적용됐는지만 집행. 첫 번역·신작·오리지널 캐릭터에 쓴다.

약한 경로도 `rejected` 선례 거부는 유지한다. 이미 평탄화로 판명된 렌더링은 선언할 수 없다. 권위는 봉인 해시에 결박되고 게이트 요약에 각인된다.

**축 비대칭.** 원문축과 타깃축이 다르다. 예: `ja_hao_gozaru`의 원문축은 `speech_level`(JA)이지만 한국어 플러그인은 그 축을 `not_applicable`로 선언하고 실현의 `target_axis`(`ending_transform`)로 측정한다. **타깃을 원문축으로 측정하면 조용히 False가 된다.** 실현 파일의 `target_axis`를 반드시 확인하라.

**어댑터 표면.** 측정은 원문 그대로가 아니라 정규화된 표면에 대해 한다. 말풍선 구분자·태그·ASS `\N`·루비가 표지와 문장 끝 사이에 끼면 `$` 앵커가 죽는다. 이 계열 결함이 이 저장소에서 일곱 번 나왔다.

## 절대 하지 말 것

- **canonical 단계를 조작하지 말 것.** 출하 카탈로그는 현재 canonical 0/10이다. 그러므로 `precedent_backed` 계약은 봉인되지 않는다. 이건 버그가 아니라 정직한 보고다.
- **경계값을 넓혀 통과시키지 말 것.** `COVERAGE_FLOOR_X=0.70`, `KAPPA_FLOOR=0.60`, 인용 상한 120자/1000자, 승격 하한 3/2 및 8/3/1/1/1은 동결이다.
- **인용을 만들어내지 말 것.** 모든 출처는 실제로 가져와 읽은 것이어야 한다. 검색 스니펫은 읽은 게 아니다. 확인 못 한 출처는 `catalogue/SOURCES.md`의 `Unverified and excluded`에 적고 인용하지 않는다.
- **선례 판정을 대신하지 말 것.** `ja_danakka_dearimasu`의 모순은 아티팩트가 인간 운영자에게 유보해 뒀다.
- **보고(report)를 통과로 취급하지 말 것.** 건너뛴 필수 게이트는 빈 결과가 아니라 hard 결과다.
- 대본 원문을 저장소에 넣지 말 것. 코퍼스는 표지 패턴·인용·최소 인용문만 싣고 기계적으로 강제된다.

## 검증

작업 후 반드시 전부 통과해야 한다.

```sh
cd /root/tmp/hancharacter
python3 -W error::ResourceWarning -m unittest discover -s tests -t .
for c in "types --lint" "corpus --lint" "precedents --lint" "dialect --lint" measure; do
  ./bin/hancharacter $c >/dev/null || echo "FAIL $c"
done
```

기준: 고정 픽스처가 있으면 **522 tests, 0 skips, 0 warnings**. 픽스처가 없으면 516 OK + 7 declared skips(정상). 다섯 lint 전부 rc 0. 외부 픽스처 경로는 `HANCHARACTER_FIXTURE` 환경변수로 바꾼다.

`tests/test_docs.py`가 못박힌 문장을 글자 그대로, 모든 CLI 하위명령과 축, `docs/gates.md`의 모든 게이트 코드를 실제 코드와 대조한다. 사실이 바뀌면 문서가 깨진다 — 그때는 문서를 새 사실로 고치되 **약화시키지 말 것.**

## 현재 한계

`README.md`의 declared limitations 절이 정본이다. 요약: JA/EN → KO 전용(원문 플러그인 `ja`/`en`, 타깃 실현 `ko`). 카탈로그 14유형 중 13개가 일본어 역할어. `prose_fidelity` 모드에서 밀도는 보고만 한다. 엔진이 감싸는 행은 길이 상한을 증명할 수 없다. 방언 의미 충실도는 측정 불가. 검토자 신원이 인증되지 않으므로 카파는 **인간 평가자 간 신뢰도가 아니라 코딩 스킴 명확성**으로 읽어야 한다.

`ja_hao_gozaru`는 검증된 출판 렌더링 기록 하나면 canonical이 된다. 어디를 찾아봤고 왜 부족했는지는 `catalogue/SOURCES.md`에 있다.
