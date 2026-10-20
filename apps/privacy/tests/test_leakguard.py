"""Red-team corpus for the pure LeakGuard scanner (no DB, no cache)."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.privacy.enums import LeakCategory
from apps.privacy.services.leakguard import LeakGuard, extract_digits, looks_like_phone

PHONE = LeakCategory.PHONE.value


class ScanBlockTests(SimpleTestCase):
    def setUp(self) -> None:
        self.g = LeakGuard()

    def _blocked(self, text, category=None, prior=""):
        v = self.g.scan(text, prior_digits=prior)
        self.assertTrue(v.blocked, f"expected BLOCK for {text!r} (hits={v.hits})")
        if category:
            self.assertEqual(v.top_category, category, f"{text!r} -> {v.hits}")
        return v

    # --- phone, plain + spaced + prefixed --------------------------------
    def test_plain_phone(self):
        self._blocked("9876543210", PHONE)

    def test_spaced_phone(self):
        self._blocked("my num is 98765 43210", PHONE)

    def test_prefixed_phone(self):
        self._blocked("call +91 98765-43210", PHONE)

    # --- spelled-out + double --------------------------------------------
    def test_spelled_phone(self):
        self._blocked(
            "nine eight seven six five four three two one zero", PHONE
        )

    def test_double_expansion_phone(self):
        # double nine -> 99, then 8765 4 3 2 1 = 9987654321
        self._blocked(
            "double nine eight seven six five four three two one", PHONE
        )

    def test_hinglish_spelled_phone(self):
        # Hinglish digit words (no '2'/"do" — see ruleset note on excluded
        # English-colliding tokens): 9 8 7 6 5 4 3 1 0 9.
        self._blocked("nau aath saat chhe paanch char teen ek shunya nau", PHONE)

    # --- hex / octal / binary encoding -----------------------------------
    def test_hex_encoded_phone(self):
        self._blocked(f"my num {hex(9876543210)}", PHONE)

    def test_octal_encoded_phone(self):
        self._blocked(f"here {oct(9876543210)}", PHONE)

    def test_binary_encoded_phone(self):
        self._blocked(f"code {bin(9876543210)}", PHONE)

    # --- scattered-in-prose reassembly (single message) ------------------
    def test_scattered_prose_phone(self):
        self._blocked(
            "i saw nine sheep, eight legs, seven trees, six cats, five dogs, "
            "four cows, three pigs, two ants, one bee, zero owls",
            PHONE,
        )

    # --- reassembly across messages (via prior_digits) -------------------
    def test_cross_message_reassembly(self):
        first = self.g.scan("my number is nine eight seven six")
        self.assertFalse(first.blocked)
        self._blocked(
            "five four three two one zero", PHONE, prior=first.combined_digits
        )

    # --- email / upi / url ------------------------------------------------
    def test_plain_email(self):
        self._blocked("reach me foo.bar@gmail.com", LeakCategory.EMAIL.value)

    def test_verbose_email(self):
        self._blocked("foo at gmail dot com", LeakCategory.EMAIL.value)

    def test_upi(self):
        self._blocked("pay me rahul-99@oksbi", LeakCategory.UPI.value)

    def test_url(self):
        self._blocked("here linktr.ee/rahul", LeakCategory.URL.value)

    def test_url_with_scheme(self):
        self._blocked("http://instagram.com/rahul", LeakCategory.URL.value)

    # --- social handles ---------------------------------------------------
    def test_at_handle(self):
        self._blocked("find me @rahul_99", LeakCategory.SOCIAL_HANDLE.value)

    def test_platform_plus_handle(self):
        self._blocked("my insta is rahul_123", LeakCategory.SOCIAL_HANDLE.value)

    # --- steering / solicitation -----------------------------------------
    def test_solicitation(self):
        self._blocked("give me your ig", LeakCategory.SOLICITATION.value)

    def test_solicitation_number(self):
        self._blocked("whats your number?", LeakCategory.SOLICITATION.value)

    def test_steering_move(self):
        self._blocked("let's move to whatsapp", LeakCategory.STEERING.value)

    def test_steering_add(self):
        self._blocked("add me on snap", LeakCategory.STEERING.value)

    def test_meet_up(self):
        self._blocked("lets meet up tomorrow")

    # --- leet obfuscation -------------------------------------------------
    def test_leet_platform_handle(self):
        self._blocked("my 1nsta is cool_guy7", LeakCategory.SOCIAL_HANDLE.value)


class ScanAllowTests(SimpleTestCase):
    def setUp(self) -> None:
        self.g = LeakGuard()

    def _allowed(self, text):
        v = self.g.scan(text)
        self.assertFalse(v.blocked, f"expected ALLOW for {text!r} (hits={v.hits})")

    def test_greeting(self):
        self._allowed("hey how are you doing today")

    def test_small_numbers(self):
        self._allowed("i have 2 classes and 3 exams this week")

    def test_time_reference(self):
        self._allowed("see you at 7 pm")

    def test_lone_platform_mention(self):
        self._allowed("i love instagram so much")

    def test_call_idiom(self):
        self._allowed("call me crazy but this was fun")

    def test_year_reference(self):
        self._allowed("that movie from 2019 was great")


class CrossMessageTextTests(SimpleTestCase):
    """A steer/solicitation split across messages (via prior_text)."""

    def setUp(self) -> None:
        self.g = LeakGuard()

    def test_add_me_on_insta_split(self):
        # Neither half trips alone; the joined window does -> block the completer.
        self.assertFalse(self.g.scan("add me").blocked)
        self.assertFalse(self.g.scan("on insta").blocked)
        v = self.g.scan("on insta", prior_text="add me")
        self.assertTrue(v.blocked)
        self.assertEqual(v.top_category, LeakCategory.STEERING.value)

    def test_lets_meet_split(self):
        self.assertFalse(self.g.scan("meet at the lib").blocked)
        self.assertTrue(self.g.scan("meet at the lib", prior_text="lets").blocked)

    def test_innocent_pair_not_blocked(self):
        # "i love my" + "instagram feed" must not combine into a block.
        v = self.g.scan("instagram feed", prior_text="i love my")
        self.assertFalse(v.blocked)


class MultilingualAndEvasionTests(SimpleTestCase):
    """New v2 capabilities: multilingual keyword dictionaries, cross-script
    confusables, international phone validation, meeting signals, self-name."""

    def setUp(self) -> None:
        self.g = LeakGuard()

    def _blocked(self, text, category=None, **kw):
        v = self.g.scan(text, **kw)
        self.assertTrue(v.blocked, f"expected BLOCK for {text!r} (hits={v.hits})")
        if category:
            self.assertEqual(v.top_category, category, f"{text!r} -> {v.hits}")
        return v

    def test_hindi_steer(self):
        self._blocked("insta pe add kar", LeakCategory.STEERING.value)

    def test_hindi_solicitation(self):
        self._blocked("number bhej do", LeakCategory.SOLICITATION.value)

    def test_tamil_steer(self):
        self._blocked("insta la add pannu", LeakCategory.STEERING.value)

    def test_gujarati_solicitation(self):
        self._blocked("number aapo", LeakCategory.SOLICITATION.value)

    def test_bengali_spelled_phone(self):
        # Bengali number words feed the reassembler.
        self._blocked("noy aat saat chhoy paanch char tin dui ek shunno",
                      LeakCategory.PHONE.value)

    def test_confusable_platform_steer(self):
        # Cyrillic 'і' inside "insta" folds to ASCII, so the steer still trips.
        self._blocked("add me on іnsta", LeakCategory.STEERING.value)

    def test_international_phone(self):
        self._blocked("+1 415 555 2671", LeakCategory.PHONE.value)

    def test_meeting_combination(self):
        self._blocked("lets meet at the canteen tomorrow", LeakCategory.MEETING.value)

    def test_lone_venue_allowed(self):
        self.assertFalse(self.g.scan("is the canteen open right now").blocked)

    def test_self_name_blocked_own_only(self):
        self._blocked("hey i am hardik", LeakCategory.SELF_NAME.value,
                      sender_name="Hardik Jumnani")
        # The partner's name is never checked against this sender.
        self.assertFalse(self.g.scan("are you isha", sender_name="Hardik Jumnani").blocked)


class EvasionV21Tests(SimpleTestCase):
    """v2.1: space-stripping, misspelling/stretch, and split-across-messages,
    with Scunthorpe false-positive guards."""

    def setUp(self) -> None:
        self.g = LeakGuard()

    def test_particle_deglue_destination(self):
        # "thecafe" -> "the cafe" (de-glue) so the venue is seen.
        v = self.g.scan("lets meet at thecafe")
        self.assertTrue(v.blocked)
        self.assertEqual(v.top_category, LeakCategory.MEETING.value)

    def test_stretch_steer(self):
        self.assertTrue(self.g.scan("instaaa add me").blocked)

    def test_glued_steer(self):
        self.assertTrue(self.g.scan("addmeoninstagram").blocked)

    def test_misspelling_doubling_meeting(self):
        # "mee" squeezes to "me" so "meet mee" forms the invite.
        self.assertTrue(self.g.scan("meet mee at the cafe").blocked)

    def test_owner_split_evasion(self):
        # The exact reported evasion: "meet mee at" then "Thecafe".
        self.assertFalse(self.g.scan("meet mee at").blocked)
        v = self.g.scan("Thecafe", prior_text="meet mee at")
        self.assertTrue(v.blocked)
        self.assertEqual(v.top_category, LeakCategory.MEETING.value)

    def test_fp_instance(self):
        self.assertFalse(self.g.scan("this is just an instance of a problem").blocked)

    def test_fp_install(self):
        self.assertFalse(self.g.scan("lets install the app and restart").blocked)

    def test_fp_decaf(self):
        self.assertFalse(self.g.scan("decaffeinated coffee is the best").blocked)


class HelperTests(SimpleTestCase):
    def test_extract_digits_mixed(self):
        self.assertEqual(extract_digits("two cats 3 dogs nine"), "239")

    def test_looks_like_phone(self):
        self.assertTrue(looks_like_phone("ab9876543210cd"))
        self.assertFalse(looks_like_phone("12345"))
