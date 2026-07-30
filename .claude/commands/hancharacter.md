---
description: 번역에서 캐릭터 말투(役割語)가 뭉개졌는지 기계적으로 검사·집행한다. LOSS(표지 삭제)와 INVENTION(없던 개성 발명)을 모두 거부.
argument-hint: "[작업 설명 또는 파일 경로] [--format srt|po|ass|xliff|csv|epub]"
---

# /hancharacter

`hancharacter` 스킬을 트리거합니다. 원문 캐릭터의 말투 표지를 측정해 계약으로 봉인하고, 번역이 그 목소리를 지웠거나 없던 걸 만들어냈으면 거부합니다.

전체 규칙과 금지 사항은 `skills/hancharacter/SKILL.md`를 **끝까지 읽고** 따르십시오. 특히 다음은 절대 위반하지 마십시오.

- canonical 단계를 조작하지 말 것 (출하 카탈로그는 canonical 0/10 이며 그것이 정직한 상태)
- 동결 상수를 넓혀 통과시키지 말 것
- 인용을 만들어내지 말 것 (검색 스니펫은 읽은 것이 아님)
- 보고(report)를 통과로 취급하지 말 것

## 사용

```
/hancharacter 이 자막 파일에서 화자별 말투 일관성 검사해줘
/hancharacter your.srt 평탄화된 대사 찾아줘
/hancharacter 하오체 계약을 translator_declared 로 봉인해서 LOSS 잡아줘
```
