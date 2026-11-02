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
        self.assertIn("OBFUSCATION_SPLIT", self._signals("reach me h.e.l.l.o"))

    def test_obfuscation_zero_width(self):
        self.assertIn("OBFUSCATION_INVISIBLE", self._signals("hel​lo there"))

    def test_obfuscation_confusable(self):
        # Cyrillic 'а' / 'е' render like Latin.
        self.assertIn("OBFUSCATION_INVISIBLE", self._signals("sаmе text"))

    def test_near_phone_digit_run(self):
        self.assertIn("NEAR_PHONE", self._signals("my id 9876543"))  # 7 digits

    def test_near_phone_wrong_prefix(self):
        # 10 digits that are NOT a valid mobile (starts 0) -> near-phone, not a block.
        self.assertIn("NEAR_PHONE", self._signals("code 0123456789"))

    def test_brand_mention(self):
        self.assertIn("BRAND_MENTION", self._signals("ping me on insta later"))

    def test_handle_soft_common_word_value(self):
        # "my insta is cool" — letters-only value Veil cannot hard-block.
        self.assertIn("HANDLE_SOFT", self._signals("my insta is cool"))

    def test_contact_soft_no_platform(self):
        self.assertIn("CONTACT_SOFT", self._signals("just find me somewhere ok"))

    def test_partial_spelled_digits(self):
        self.assertIn("PARTIAL_DIGITS", self._signals("nine four four later"))

    def test_selfname_soft_reversed_short(self):
        # "isha" (4) reversed is "ahsi"; Veil only hard-blocks reversed names >= 6.
        self.assertIn("SELFNAME_SOFT", self._signals("ahsi here", sender_name="Isha Roy"))

    def test_selfname_soft_disemvowelled(self):
        self.assertIn(
            "SELFNAME_SOFT",
            self._signals("its hrdk here", sender_name="Hardik Jumnani"),
        )

    def test_digit_drip_cadence_cross_message(self):
        signals = self._signals(
            "4", prior_messages=("9", "8", "7"),
        )
        self.assertIn("DIGIT_DRIP", signals)

    def test_romanized_indic_is_ambient_only(self):
        # Romanized Hindi fires the ambient signal but contributes 0 priority.
        v = self.g.scan("chalo yaar kaise ho")
        self.assertEqual(v.top_signal, "ROMANIZED_INDIC")

    def test_self_name_not_flagged_as_gibberish(self):
        signals = self._signals("qwrtzxc", sender_name="Qwrtzxc Lastname")
        self.assertNotIn("GIBBERISH", signals)

    def test_meeting_soft_invite_plus_venue(self):
        self.assertIn(
            "MEETING_SOFT", self._signals("lets meet at the resort tomorrow")
        )

    def test_location_soft_multiple_venues_no_invite(self):
        self.assertIn("LOCATION_SOFT", self._signals("the hostel near the station"))

    def test_single_venue_no_meeting_signal(self):
        # A lone place word (benign narrowing) must not trip a meeting/location signal.
        signals = self._signals("the canteen food is good")
        self.assertNotIn("LOCATION_SOFT", signals)
        self.assertNotIn("MEETING_SOFT", signals)

    def test_benign_noise_budget(self):
        noisy = [(t, self.g.scan(t).score) for t in BENIGN if self.g.scan(t).score]
        self.assertEqual(noisy, [], f"benign text produced signals: {noisy}")
