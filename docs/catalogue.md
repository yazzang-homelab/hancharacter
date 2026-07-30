# Catalogue reference

The catalogue is a closed, versioned evidence set under `catalogue/`, currently version `2026.07`. Source types live in `catalogue/types/`; Korean realisations live in `catalogue/realisations/ko/`; probe rows, drafts, reviews, precedents, human confirmations, and dialect decisions are sibling artifacts. A type being listed is not a claim that it is canonical or sealable.

## Axes

`schemas.AXES` is the closed axis vocabulary. These are the 11 accepted axis names:

- `speech_level`
- `pronouns`
- `ending_transform`
- `interjection_laugh`
- `lexical_register`
- `sentence_habit`
- `dialect_policy`
- `orthographic_distortion`
- `punctuation_policy`
- `utterance_frame`
- `phoneme_substitution`

A source type's axis and a target realisation's mechanism may differ. A target realisation may declare `target_axis`; otherwise it is measured on its source type's axis. An axis that a language plugin marks `not_applicable` may remain catalogued, but it cannot seal because its density is constant and cannot support an enforcement gate.

## Reproduce this reference

The tables below were generated from the resolved catalogue rather than transcribed from prose. Re-run this checkout-only standard-library snippet after changing catalogue artifacts; it follows preset derivations through the same loader the commands use.

```sh
python3 - <<'PY'
from hancharacter import typology

for type_id, row in sorted(typology.load_types().items()):
    print(type_id, row["source_lang"], row["axis"], row["source_marker"], sep="\t")
for realisation_id, row in sorted(typology.load_realisations("ko").items()):
    print(realisation_id, row["type_id"], row["target_realisation"], sep="\t")
PY
```

The `types --lint --target ko` command additionally checks the source/target pattern sets against authored probes, catalogue distinctness, precedent joins, claimed edition channels, and plugin axis measurability.

## Source types

| ID | Source | Axis | Source marker | Description |
| --- | --- | --- | --- | --- |
| `en_eye_dialect_fleur` | en | `orthographic_distortion` | French-accented eye dialect (zis / zat / 'Arry) | French-accented English eye dialect. |
| `ja_chuunibyou_frame` | ja | `utterance_frame` | grandiose self-naming / archaic address frame | Chuunibyou grandiose utterance frame. |
| `ja_danakka_dearimasu` | ja | `speech_level` | ~であります | Military-report copula. |
| `ja_elder_lexicon` | ja | `lexical_register` | わし / のじゃ elder lexicon | Elder role lexicon. |
| `ja_hakata_zura` | ja | `dialect_policy` | ~ずら | Auxiliary regional-dialect precedent carrier. |
| `ja_hao_gozaru` | ja | `speech_level` | ~ござる | Archaic samurai copula. |
| `ja_monne_ending` | ja | `ending_transform` | ~もんね | Auxiliary edition-variant carrier. |
| `ja_nagoya_ben` | ja | `dialect_policy` | ~だがや / みゃー (Nagoya) | Auxiliary regional LOSS carrier. |
| `ja_nanoda` | ja | `ending_transform` | ~なのだ | Auxiliary assertive-ending edition-variant carrier. |
| `ja_nanodesu` | ja | `ending_transform` | ~なのです | Softening explanatory ending; intermittent by nature. |
| `ja_nyan_copula` | ja | `ending_transform` | ~にゃ / ~にゃあ | Feline sentence-final copula substitution. |
| `ja_otaku_copula` | ja | `ending_transform` | ~だお / ~ですお (net-otaku copula) | Marked otaku copula rendered in Korean as ~다능. |
| `ja_seumda_ssu` | ja | `speech_level` | ~っス / ~ッス | Clipped deferential copula. |
| `ja_zerozaki_cha` | ja | `ending_transform` | ~ちゃ | Auxiliary ending-to-regional precedent carrier. |

## Resolved Korean realisations

These rows are the resolved form returned by `typology.load_realisations("ko")`; a preset row is therefore shown with the fields it inherits rather than as an incomplete raw JSON file.

| Realisation ID | Source type | Target realisation | Target axis |
| --- | --- | --- | --- |
| `ko_chuunibyou` | `ja_chuunibyou_frame` | archaic frame: 내 이름은 / 그대 / 어둠의 | source `utterance_frame` |
| `ko_danakka_jimalimnida` | `ja_danakka_dearimasu` | ~지 말입니다 | `ending_transform` |
| `ko_elder` | `ja_elder_lexicon` | elder lexicon: ~구먼 / ~이로다 / ~노라 | `ending_transform` |
| `ko_fleur_ieung` | `en_eye_dialect_fleur` | ㅇ-받침 orthographic distortion (~니당 / ~예용) | `phoneme_substitution` |
| `ko_hao_io` | `ja_hao_gozaru` | ~이오 / 하오체 | `ending_transform` |
| `ko_nanodesu` | `ja_nanodesu` | ~인 것입니다 / ~인 거예요 | source `ending_transform` |
| `ko_nyan` | `ja_nyan_copula` | ~냥 sentence-final substitution | source `ending_transform` |
| `ko_otaku_daneung` | `ja_otaku_copula` | ~다능 / ~이라능 | source `ending_transform` |
| `ko_seumda_jimalimnida` | `ja_seumda_ssu` | ~지 말입니다 | `ending_transform` |

## Reading catalogue status correctly

A probe match is only a check that a pattern is measurable on authored controls and exemplars. It is not proof that a published translation used that realisation. A precedent marked adopted is evidence that an edition shipped a rendering; a corpus reviewer verdict is a separate claim that one quoted row was transcribed correctly. Neither one substitutes for the other.

The shipped `ja_chuunibyou_frame` remains in the reference because it is an honest type claim, but its source axis is not measurable by the Japanese plugin, so it is catalogued and unsealable. The current catalogue has **no canonical type**. `ja_hao_gozaru` and `ja_elder_lexicon` are `provisional`; `ja_hao_gozaru` meets every canonical criterion except one, having no adopted precedent after the only candidate was corrected down to `contested` for consistency with its siblings. See `docs/evidence.md` and `docs/review-protocol.md` for the unmet evidence floors.
