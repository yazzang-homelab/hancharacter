# Evidence provenance ledger

This file is the human-auditable record behind the machine-checked provenance
columns in `samples.draft.jsonl`. Every row in that file carries `source.class`,
`source.consulted_via`, `source.independent_key` and `source.locator`; this file says
what each key actually is and what could not be verified.

`precedents.jsonl` carries **no** provenance columns — a `precedent` has `citation`
and `edition_channel` and nothing else, and the closed schema rejects a `source`
object as an unknown key. So a precedent's provenance is *not* machine-checked, only
its verdict vocabulary and its cross-references are. Reading a precedent's `citation`
is the only way to judge its provenance, which is a real gap and is listed below.

The schema enforces the part that can be enforced: `class: primary` requires
`consulted_via` in (`direct_read`, `fixture_file`), and `class: secondary` requires
it in (`direct_read`, `mirror`, `search_snippet`, `fixture_file`). A source reached
only through someone else's citation is `cited_by`, which can never back a
primary or secondary claim, because hearsay that counts toward a graduation floor
is a fabricated floor.

## Independent sources

`independent_key` is what the canonical rule counts. Mirrors and separate articles
of one publication share one key.

| key | what it is | class | consulted via | date |
|---|---|---|---|---|
| `namuwiki_special_endings` | 나무위키 articles 「특수한 어미」, 「특수한 어미/일람」, 「하오체」, 「~지 말입니다」, 「플뢰르 들라쿠르」, 「해리 포터와 불의 잔」 | reference | mirror | 2026-07-29 |
| `leiden_yakuwarigo_2018` | Leiden University MA thesis, "Yakuwarigo Lost in Translation" (2018) | secondary | search_snippet | 2026-07-29 |
| `daum_cafe_ilbonuh_doum` | Daum cafe 「≫일본어도움」 post glossing 「~でござる」 as Korean ~이오 / ~하오 | reference | search_snippet | 2026-07-29 |
| `daum_cafe_hyoryoung_m30` | Daum cafe 「[생]바람의검신」 post glossing 「ござる」 as ~하였소 / ~하오 | reference | search_snippet | 2026-07-29 |
| `naver_blog_japansisa_yakuwarigo` | blog.naver.com/japansisa, 「인물에 따라 다른 표현 '일본에 존재하는 역할어(役割語)'」 | reference | search_snippet | 2026-07-29 |
| `google_books_goblet_of_fire_ko` | Google Books record for 『해리 포터와 불의 잔』 Korean edition | reference | search_snippet | 2026-07-29 |

### Mirrors deliberately collapsed into one key

`namu.moe`, `thewiki.kr` and `tcatmon.com` (우만위키) all carry the same Korean wiki
text lineage as `namu.wiki`. They are **not** independent sources. Counting them
separately would turn one publication into three or four and would clear the
canonical independent-source floor on a single body of text. All of them map to
`namuwiki_special_endings`.

This concentration was the single biggest weakness of the original corpus: 19 of 42
draft rows come from that one key. See *Limitations* below.

## What the sources actually establish

**Verified mappings.** 나무위키 「특수한 어미/일람」 records `~ござる` rendered as Korean
`~이오` for named characters (토우마 린, 소라카게), and `~であります` rendered as
`~지 말입니다` for named characters in two separate works (용자경찰 제이데커 덤프슨,
황금용자 골드란 드릴 실버). Two independent Daum authors gloss `ござる` as the Korean
하오체 register (`~하오`, `~하였소`), and the 「하오체」 article states the Japanese-side
correspondence directly.

**A verified LOSS case.** 나무위키 「~지 말입니다」 records that characters using
`~であります` are rendered as plain `~입니다` in Korean, which deletes the marker. This
directly contradicts the adopted rendering above, and the two precedent rows point
at each other via `contradicts` with **no** resolution recorded. That unresolved
contradiction correctly blocks canonical status for `ja_danakka_dearimasu`.

**The general LOSS claim.** 나무위키 「특수한 어미」 states that a large share of special
endings are deleted in Korean releases. This is recorded as a rejected precedent so
that a realisation reproducing it fails at seal time.

## Unverified and excluded

Recorded here rather than quietly omitted, because a gap that is not written down
becomes an implicit claim of coverage.

- **`~다능` (Korean rendering of the otaku copula).** Not documented in the
  retrieved 「특수한 어미/일람」 text. The realisation `ko_otaku_daneung` therefore
  cites a **contested** precedent, not an adopted one, and `ja_otaku_copula`
  cannot reach canonical.
- **Fleur Delacour's Korean ending inventory.** Reference sources confirm the
  character is written as a French speaker whose English is imperfect, and confirm
  that Korean editions exist (2000, plus a later retranslation). The specific
  Korean endings used to render the accent were **not** directly verified, so
  `prec_fleur_ieung_ko` is `contested` and the ㅇ-받침 pattern set in
  `ko_fleur_ieung` is this project's proposal rather than an observed rendering.
- **`~っス` Korean rendering.** The retrieved text describes the form only as a
  variant of `です`. The Korean side is unverified; `prec_akunomusume_ssu_ko` is
  contested.
- **`~にゃ`, `~なのです` Korean renderings.** Only the umbrella taxonomy was
  retrieved. Both are contested.
- **The Chinese-accent rendering of the `~Death` suffix.** Recorded as a
  **rejected** precedent with a target pattern set, so the seal-time matcher can
  actually fire on any realisation that reproduces it.
- **Regional attribution of `~ずら`.** Recorded as reported by the reference
  source and flagged in the type's own provenance notes as not independently
  confirmed.
- **The 관서/오사카 → 경상/부산 dialect pair.** No adopted
  source-region-to-target-region precedent was verified, so
  `dialect_decisions.jsonl` ships **empty** and the `dialect_pair_undecided` gate
  fires for any work declaring that pair. An invented ruling would be worse than
  no ruling.
- **Primary editions.** No row claims `class: primary`, because no published
  edition was opened directly. Every mapping above is recorded at the provenance
  level actually achieved.

## Limitations

1. **One publication is still the largest single contributor.** 19 of 42 draft rows share
   `namuwiki_special_endings`. Independent-source floors are therefore hard to
   clear honestly, and only `ja_hao_gozaru` reaches three independent sources.
2. **No accepted primary or secondary evidence.** The one secondary source
   (Leiden) establishes that character language is lost in translation, not any
   specific Korean rendering, so both of its rows resolve to `needs_review` and
   the `e1e2_sources` count is 0 for every type. This alone blocks canonical
   status across the board.
3. **Inter-rater agreement only just clears the floor.** Two reviewers applying one rubric
   reach overall kappa 87/143 against a 0.60 floor. The corpus is only just reliable enough
   to graduate anything, and this is reported rather than tuned away.
4. **Reviewer identity is unauthenticated.** Reviewer ids are declarations in a
   filename and a field. Nothing cryptographically binds a verdict to a person,
   and the artifacts are unsigned.
5. **Provenance depends on honest self-report for `consulted_via`.** The schema
   can check that a claimed class is *consistent* with a claimed provenance; it
   cannot check that the provenance itself is true.
6. **Precedent provenance is unchecked by machine.** `precedents.jsonl` has no
   `source` object, so nothing cross-checks a precedent's citation against what was
   actually consulted. Two rows are marked `adopted` on the strength of a Daum-cafe
   gloss and a blog explainer rather than a publication record: `prec_gozaru_io_ko`
   rests on the wiki list, `prec_gozaru_haoche_ko` on an independent forum author,
   and `prec_elder_lexicon_kr` on a blog explainer plus this project's synthesis of
   the Korean ending inventory. `adopted` is a canonical criterion, so these are the
   rows most worth challenging first.
7. **The secondary citation is imprecise.** The Leiden thesis is cited by title and
   year with no author, repository handle or page. `secondary` is the only class that
   can satisfy the E1/E2 floor, and this citation is not precise enough to re-find
   reliably. It does not currently matter because both of its rows resolve to
   `needs_review`, but the gate held on a reviewer's judgement rather than on the
   provenance rules.
8. **The general LOSS precedent is filed where nothing reaches it.**
   `prec_special_endings_deleted_ko` is attached to `ja_monne_ending`, which has no
   realisation, so the seal-time matcher never evaluates it and not even its recorded
   gap is emitted. The claim that a reproducing realisation "fails at seal time" is
   true of the mechanism, not of this row as filed.

## T1 round: academic and encyclopaedic sources (added 2026-07)

These were fetched and read directly (`consulted_via: direct_read`), not taken from a search snippet.

### Verified and cited

- **小林亜希子「キャラ語尾「ござる」の文法：記述編」**, 島根大学学術情報リポジトリ, `https://ir.lib.shimane-u.ac.jp/55187/files/13091` — `secondary`, `independent_key: shimane_kobayashi_gozaru`. A departmental bulletin paper (紀要論文, non-refereed) presenting a syntactic study building a corpus from 『忍者ハットリくん』全4巻 (645 sentences) and 『新忍者ハットリくん』全8巻 (1,502 sentences). It supplies counted occurrences (ござる>否定 26, 否定>ござる 17, ござる>過去 29, 存在動詞 9) rather than isolated anecdotes, an independent cross-check from 『るろうに剣心』6巻, and separately documents ＜博士語＞ (`ja_elder_lexicon`), 獅子丸's ~ワン (`ja_nyan_copula`) and 体育会系後輩's ~っす (`ja_seumda_ssu`). **This is the first `primary`/`secondary` provenance row in the catalogue**; every type previously sat at `e1e2_sources = 0`, which alone blocked canonical regardless of any other criterion.
- **ウィキペディア日本語版「役割語」**, `https://ja.wikipedia.org/wiki/役割語` — `reference`, `independent_key: jawiki_yakuwarigo`. Supplies 老人語 (わし / じゃ / 〜ぬ / おる) with its 上方語 origin, the キャラ語尾 roster (バカボンのパパ「〜なのだ」, コロ助「〜ナリ」, ラム「〜だっちゃ」, 「〜ワン」「〜ニャ」), 視覚方言 for the English eye-dialect axis, and a 朝鮮語 section noting that Korean expresses these distinctions through 敬語 rather than through a comparable 役割語 inventory — which is load-bearing for the v1 Korean realisation strategy.

### Sought but not verified, and therefore not cited

- **「ござる」の言語学**, `https://shokei.repo.nii.ac.jp/record/282/files/KJ00009950079.pdf`. The endpoint returned raw PDF bytes that did not convert to text, so the body was never actually read. A search-result snippet describing it exists, but a snippet is not a reading: citing it would assert provenance we do not have. Excluded until it can be fetched and read.
- **小林亜希子「キャラ語尾「ござる」の文法：分析編」**, `https://ir.lib.shimane-u.ac.jp/55352/files/13541`. Same author and same journal as the 記述編 above, so it would share `independent_key: shimane_kobayashi_gozaru` and add no independence. Not cited separately.

### Open operator decision

- `ja_danakka_dearimasu` carries an unresolved contradiction between `prec_dearimasu_jimalimnida_ko` (adopted, ~지 말입니다) and `prec_dearimasu_flattened_ko` (rejected, marker deleted to ~입니다). The rejected precedent's own notes reserve the ruling for a human operator. It is deliberately left unruled: an agent self-ruling it would manufacture the graduation the gate exists to prevent. That type therefore stays below canonical by design, not by oversight.

### Precedent standard applied consistently (2026-07)

`prec_gozaru_io_ko` was corrected from `adopted`/`official` to `contested`/`unpublished`.
Its own notes recorded that it came from a wiki list "not from the broadcast itself",
which is the same standing that had already caused `prec_fleur_ieung_ko` and
`prec_gozaru_haoche_ko` to be corrected downward — the former with the explicit
reasoning that recording an unverified ending inventory as adopted "would assert a
rendering nobody checked". This row was nonetheless left adopted while it served as
the adopted-precedent leg of the project's only canonical type. A search for an
independent broadcast or publication record returned only the same wiki lineage.

The correction costs `ja_hao_gozaru` its canonical status and returns the catalogue
to 0 of 10 canonical. `catalogue/realisations/ko/ko_hao_io.json` was moved to
`unpublished` for the same reason, which the `types --lint` channel check caught
automatically. The evidence gains of the round survive: occurrences 4 to 12,
independent sources 3 to 4, `e1e2_sources` 0 to 1, kappa 0.500 to 0.600. Only the
precedent leg failed, and it failed to a standard the project already applied
elsewhere.

### Path B attempted: no adopted precedent could be verified (2026-07)

The `precedent_backed` route needs one type to reach canonical, and `ja_hao_gozaru` is
one criterion away: it lacks an adopted precedent. An adopted precedent requires
evidence that a published edition actually shipped a specific Korean rendering, which
Japanese source-side scholarship cannot supply.

Searched, in this order:

1. Korean-language web search for 역할어 / 캐릭터 말투 번역 scholarship. Returned only the
   namuwiki lineage already in this catalogue — including the 하오체 article naming
   키테레츠 대백과's 코로스케 as a representative 하오체 adoption — plus commercial
   machine-translation blogs. The namuwiki claim is the same standing that caused
   `prec_gozaru_io_ko` to be corrected from `adopted` to `contested`, so re-adopting on
   it would reverse that correction on no new evidence.
2. Korean-language search for a broadcast or publication record of 용자 시리즈's
   ~이오 rendering. Returned the same wiki lineage; no broadcast log, script, or
   subtitle record surfaced.
3. KCI (한국학술지인용색인) article search. The portal requires a session-bound POST for
   article queries and the direct URL resolved to the journal index instead of results,
   so no article was retrieved and therefore none is cited.

Not attempted and recorded as the concrete next step: RISS and DBpia article search,
and officially licensed Korean subtitles for a work whose character uses ~ござる
(『るろうに剣心』 is the strongest candidate, since the Shimane paper already cites
Kenshin's でござる in the source). Both need either an authenticated session or a
licensed viewing, neither of which was available here.

**Outcome: `ja_hao_gozaru` stays `provisional`.** No precedent was recorded, because a
precedent recorded on the evidence available would be exactly the manufactured
graduation the ladder exists to prevent. The `translator_declared` route added in the
same round is what makes the tool usable meanwhile, and it deliberately claims nothing
about which Korean rendering is correct.
