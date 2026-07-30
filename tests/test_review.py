import os
import shutil
import tempfile
import unittest

from hancharacter import review


def _corpus_row(sample_id="s001"):
    return {
        "id": sample_id,
        "type_id": "fixture_type",
        "axis": "ending_transform",
        "work": "fixture work",
        "producer": "producer_p",
        "marker": "~x",
        "quote": "fixture quote",
        "notes": "fixture note",
        "source": {
            "class": "reference",
            "cite": "fixture citation",
            "consulted_via": "mirror",
            "independent_key": "src_a",
            "locator": "page one",
        },
    }


def _payload(**over):
    kwargs = dict(
        title="fixture review",
        corpus=[_corpus_row()],
        generated_at="2026-01-01T00:00:00Z",
        catalogue_version="test",
    )
    kwargs.update(over)
    return review.build_payload(**kwargs)


class DigestBindingTests(unittest.TestCase):
    def test_an_unbound_payload_is_refused_by_both_renderers(self):
        payload = _payload()
        for renderer in (review.render_text, review.render_html):
            with self.subTest(renderer=renderer.__name__):
                with self.assertRaises(review.ReviewError) as caught:
                    renderer(payload)
                self.assertIn("bind_digest", str(caught.exception))

    def test_a_mismatched_supplied_digest_is_refused(self):
        with self.assertRaises(review.ReviewError) as caught:
            review.bind_digest(_payload(), "0" * 64)
        self.assertIn("does not match", str(caught.exception))

    def test_a_correct_supplied_digest_is_accepted(self):
        payload = _payload()
        digest = review.compute_digest(payload)
        bound = review.bind_digest(payload, digest)
        self.assertEqual(digest, bound[review.DIGEST_KEY])

    def test_a_payload_edited_after_binding_is_refused(self):
        bound = review.bind_digest(_payload())
        bound["corpus"][0]["quote"] = "tampered"
        with self.assertRaises(review.ReviewError) as caught:
            review.render_text(bound)
        self.assertIn("changed after it was bound", str(caught.exception))

    def test_the_digest_excludes_itself(self):
        """Including the stored digest in its own input makes it unverifiable."""
        bound = review.bind_digest(_payload())
        self.assertEqual(bound[review.DIGEST_KEY], review.compute_digest(bound))

    def test_canonicalisation_is_key_order_independent(self):
        first = {"b": 1, "a": {"y": 2, "x": 3}}
        second = {"a": {"x": 3, "y": 2}, "b": 1}
        self.assertEqual(
            review.compute_digest(first), review.compute_digest(second)
        )

    def test_the_digest_changes_when_content_changes(self):
        one = review.compute_digest(_payload())
        two = review.compute_digest(_payload(corpus=[_corpus_row("s002")]))
        self.assertNotEqual(one, two)


class RenderTests(unittest.TestCase):
    def test_text_and_html_render_real_seeded_rows(self):
        bound = review.bind_digest(_payload())
        text = review.render_text(bound)
        html_out = review.render_html(bound)
        for body in (text, html_out):
            self.assertIn("s001", body)
            self.assertIn("fixture citation", body)
            self.assertIn("independent_key=src_a", body)
            self.assertIn(bound[review.DIGEST_KEY], body)

    def test_html_escapes_hostile_content_and_keeps_cjk(self):
        row = _corpus_row()
        row["quote"] = '<script>alert("x")</script> & 한국어 日本語'
        bound = review.bind_digest(_payload(corpus=[row]))
        out = review.render_html(bound)
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("&amp;", out)
        self.assertIn("&quot;", out)
        self.assertIn("한국어", out)
        self.assertIn("日本語", out)

    def test_repeat_renders_are_byte_identical(self):
        bound = review.bind_digest(_payload())
        self.assertEqual(review.render_html(bound), review.render_html(bound))
        self.assertEqual(review.render_text(bound), review.render_text(bound))

    def test_no_clock_reaches_the_output(self):
        """A timestamp from the clock would break both determinism and the digest."""
        source = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "hancharacter",
            "review.py",
        )
        with open(source, "r", encoding="utf-8") as fh:
            body = fh.read()
        for forbidden in ("datetime.now", "time.time", "utcnow"):
            self.assertNotIn(forbidden, body)

    def test_an_empty_section_renders_an_explicit_not_reviewed_state(self):
        bound = review.bind_digest(_payload())
        for body in (review.render_text(bound), review.render_html(bound)):
            self.assertIn("No attributed row is awaiting confirmation", body)
            self.assertIn("Nothing here has been confirmed", body)

    def test_each_section_prints_the_reviewer_action(self):
        bound = review.bind_digest(
            _payload(
                attribution=[
                    {"row_key": "r1", "speaker": "sp", "scope": "sc", "tier": "T1"}
                ],
                confirmation=[
                    {
                        "id": "c1",
                        "confirms": ["fixture_type"],
                        "scope": "types only",
                        "artifact_cite": "doc",
                        "artifact_sha256": "a" * 64,
                    }
                ],
            )
        )
        text = review.render_text(bound)
        self.assertIn("catalogue/reviews/", text)
        self.assertIn("attribution confirmation log", text)
        self.assertIn("catalogue/human_confirm.jsonl", text)
        # The confirmation lane must surface the scope, since an unscoped
        # confirmation is read as blanket approval.
        self.assertIn("SCOPE: types only", text)


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="hc-review-")
        self.addCleanup(shutil.rmtree, self.out, True)

    def test_writes_both_formats(self):
        bound = review.bind_digest(_payload())
        html_path = review.write(bound, self.out, fmt="html")
        text_path = review.write(bound, self.out, fmt="text")
        self.assertTrue(os.path.isfile(html_path))
        self.assertTrue(os.path.isfile(text_path))

    def test_an_entirely_empty_payload_is_refused(self):
        """An empty page reads as 'reviewed and clean'."""
        bound = review.bind_digest(_payload(corpus=[]))
        with self.assertRaises(review.ReviewError) as caught:
            review.write(bound, self.out)
        self.assertIn("reviewed and clean", str(caught.exception))

    def test_an_unbound_payload_is_refused_on_write(self):
        with self.assertRaises(review.ReviewError):
            review.write(_payload(), self.out)

    def test_an_unknown_format_is_refused(self):
        bound = review.bind_digest(_payload())
        with self.assertRaises(review.ReviewError):
            review.write(bound, self.out, fmt="pdf")


class ShippedDataTests(unittest.TestCase):
    def test_the_renderer_opens_with_the_real_catalogue(self):
        from hancharacter import cli, corpus, typology

        drafts = corpus.load_drafts()
        samples, _ = corpus.merge(drafts, corpus.load_reviews())
        pending = [row for row in samples if row["verdict"] != "accept"]
        self.assertTrue(pending, "no pending row; the review lane would be empty")
        bound = review.bind_digest(
            review.build_payload(
                title="shipped review",
                corpus=pending,
                confirmation=cli._load_confirms(),
                catalogue_version=typology.catalogue_version(),
                generated_at="2026-01-01T00:00:00Z",
            )
        )
        out = review.render_html(bound)
        self.assertIn(pending[0]["id"], out)
        # The human confirmation's SCOPE must be visible, not merely its existence.
        self.assertIn("SCOPE:", out)


if __name__ == "__main__":
    unittest.main()
