"""Red-team corpus for the pure MuffleGuard scanner/masker (no DB)."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.privacy.enums import ProfanityTier
from apps.privacy.services.muffle_guard import MuffleGuard, sparse_mask


class MaskTests(SimpleTestCase):
    def setUp(self) -> None:
        self.g = MuffleGuard()

    def _masked(self, text, tier=None):
        r = self.g.scan(text)
        self.assertTrue(r.changed, f"expected masking for {text!r}")
        if tier:
            self.assertEqual(r.top_tier, tier)
        return r

    def _untouched(self, text):
        r = self.g.scan(text)
        self.assertFalse(r.changed, f"expected NO change for {text!r} -> {r.masked_text!r}")
        self.assertEqual(r.masked_text, text)

    # --- T0 casual: left alone -------------------------------------------
    def test_casual_fuck_untouched(self):
        self._untouched("this is fucking great honestly")

    def test_casual_shit_untouched(self):
        self._untouched("oh shit that's wild")

    def test_casual_with_leet_untouched(self):
        # "sh1t" -> "shit" (T0) stays untouched
        self._untouched("sh1t happens")

    # --- T1 harsh: masked, readable --------------------------------------
    def test_motherfucker_masked(self):
        r = self._masked("you motherfucker", ProfanityTier.T1_HARSH.value)
        masked = r.masked_text.split()[-1]
        self.assertIn("*", masked)
        self.assertTrue(masked.startswith("mo"))
        self.assertTrue(masked.endswith("er"))
        self.assertNotIn("motherfucker", r.masked_text)

    def test_hinglish_masked(self):
        self._masked("tu chutiya hai", ProfanityTier.T1_HARSH.value)

    def test_preserves_surrounding_text(self):
        r = self.g.scan("hey motherfucker ok")
        self.assertTrue(r.masked_text.startswith("hey "))
        self.assertTrue(r.masked_text.endswith(" ok"))

    # --- obfuscation ------------------------------------------------------
    def test_stretched_masked(self):
        self._masked("motherfuuucker", ProfanityTier.T1_HARSH.value)

    def test_leet_masked(self):
        # m0therfucker -> motherfucker
        self._masked("m0therfucker", ProfanityTier.T1_HARSH.value)

    # --- T2 slur ----------------------------------------------------------
    def test_slur_masked_and_flagged_tier(self):
        self._masked("you retard", ProfanityTier.T2_SLUR.value)

    # --- Scunthorpe guard: clean words untouched -------------------------
    def test_scunthorpe_class(self):
        self._untouched("our class assignment is due")

    def test_scunthorpe_assassin(self):
        self._untouched("the assassin escaped")

    def test_scunthorpe_cockpit(self):
        self._untouched("he sat in the cockpit")

    def test_scunthorpe_town(self):
        self._untouched("she is from Scunthorpe")


class PhraseTests(SimpleTestCase):
    def setUp(self) -> None:
        self.g = MuffleGuard()

    def test_son_of_a_bitch_sparse_masked(self):
        r = self.g.scan("you are a son of a bitch")
        self.assertTrue(r.changed)
        self.assertIn("so* o* a bi*ch", r.masked_text)
        self.assertEqual(r.hits[0].kind, "phrase")
        self.assertEqual(r.top_tier, ProfanityTier.T1_HARSH.value)

    def test_fuck_you_phrase_masked_even_though_fuck_is_casual(self):
        # "fuck" alone is T0, but "fuck you" is a targeted phrase -> masked.
        r = self.g.scan("fuck you")
        self.assertTrue(r.changed)
        self.assertIn("*", r.masked_text)

    def test_phrase_tolerates_separator(self):
        r = self.g.scan("fuck, you")
        self.assertTrue(r.changed)

    def test_phrase_leet_and_stretch(self):
        self.assertTrue(self.g.scan("fuuuck you").changed)       # stretched
        self.assertTrue(self.g.scan("piece of sh1t").changed)    # leet 1->i

    def test_hinglish_phrase(self):
        self.assertTrue(self.g.scan("abe teri maa ki").changed)

    def test_allowed_idiom_untouched(self):
        # Not in any phrase list -> left alone.
        r = self.g.scan("he is a son of a gun")
        self.assertFalse(r.changed)
        self.assertEqual(r.masked_text, "he is a son of a gun")

    def test_preserves_surrounding_text(self):
        r = self.g.scan("ok son of a bitch bye")
        self.assertTrue(r.masked_text.startswith("ok "))
        self.assertTrue(r.masked_text.endswith(" bye"))


class SparseMaskTests(SimpleTestCase):
    def test_example_from_spec(self):
        self.assertEqual(sparse_mask("motherfucker"), "mo*he*fu*ker")

    def test_keeps_first_and_last(self):
        out = sparse_mask("cocksucker")
        self.assertEqual(out[0], "c")
        self.assertEqual(out[-1], "r")
        self.assertIn("*", out)

    def test_short_word_unchanged(self):
        self.assertEqual(sparse_mask("ass"), "ass")  # < MIN_MASK_LEN
