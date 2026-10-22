"""Unit tests for the pure SuspicionGuard scanner (no DB)."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.privacy.services.suspicion_guard import SuspicionGuard

# Ordinary chat that must NOT trip suspicion (the "noise budget"): each of these
# should score 0 so the admin feed stays usable.
BENIGN = [
    "hey how are you doing today",
    "lets catch the next bus together",
    "the library is a nice quiet place",
    "see you at the library to study",
    "that movie was great lol",
    "i love this song so much",
    "haha yeah that was so funny",
    "are you free this evening",
    "nice to meet you here",
    "what are your plans for the weekend",
]


class SuspicionGuardTests(SimpleTestCase):
    def setUp(self) -> None:
        self.g = SuspicionGuard()

    def _signals(self, text, **kw):
        return {h.signal for h in self.g.scan(text, **kw).signals}

    def test_non_latin_script(self):
        self.assertIn("NON_LATIN_SCRIPT", self._signals("नमस्ते friend"))  # Devanagari
        self.assertIn("NON_LATIN_SCRIPT", self._signals("హాయ్"))  # Telugu

    def test_romanized_indic(self):
        self.assertIn("ROMANIZED_INDIC", self._signals("chalo yaar kaise ho"))
        self.assertIn("ROMANIZED_INDIC", self._signals("mujhe pata nahi"))

    def test_gibberish(self):
        self.assertIn("GIBBERISH", self._signals("asdfghjkl"))  # no vowels, long
        self.assertIn("GIBBERISH", self._signals("ytjkacvzwq here"))  # implausible

    def test_obfuscation_split_word(self):
        self.assertIn("OBFUSCATION", self._signals("reach me h.e.l.l.o"))

    def test_obfuscation_zero_width(self):
        self.assertIn("OBFUSCATION", self._signals("hel​lo there"))

    def test_obfuscation_confusable(self):
        # Cyrillic 'а' / 'е' render like Latin.
        self.assertIn("OBFUSCATION", self._signals("sаmе text"))

    def test_near_miss_digit_run(self):
        self.assertIn("NEAR_MISS", self._signals("my id 9876543"))  # 7 digits

    def test_near_miss_brand(self):
        self.assertIn("NEAR_MISS", self._signals("ping me on insta later"))

    def test_self_name_not_flagged_as_gibberish(self):
        # An unusual own-name token must not be scored as gibberish.
        signals = self._signals("qwrtzxc", sender_name="Qwrtzxc Lastname")
        self.assertNotIn("GIBBERISH", signals)

    def test_benign_noise_budget(self):
        noisy = [(t, self.g.scan(t).score) for t in BENIGN if self.g.scan(t).score]
        self.assertEqual(noisy, [], f"benign text produced signals: {noisy}")
