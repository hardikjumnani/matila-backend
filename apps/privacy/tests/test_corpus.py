"""Phase-0 Veil corpus gate.

A labeled benign / malicious corpus with two hard assertions:
  * BENIGN  -> ZERO false positives (owner's absolute requirement).
  * MALICIOUS -> caught (recall), reported as a ratio so gaps are visible.

Pure scanner (no DB); fast. Extend freely — every confirmed bypass or false
positive should become a line here. See docs/VEIL_V2_2_PLAN.md.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.privacy.services.leakguard import LeakGuard, extract_digits

# (text, prior_text, sender_name)
BENIGN: list[tuple[str, str, str]] = [
    ("meet my friend tomorrow", "", ""),
    ("meet my family this weekend", "", ""),
    ("nice to meet you here", "", ""),
    ("can we meet somewhere later", "", ""),
    ("the canteen food is great today", "", ""),
    ("is the canteen open right now", "", ""),
    ("discard the old file please", "", ""),
    ("lets install the app and restart", "", ""),
    ("this is just an instance of a problem", "", ""),
    ("decaffeinated coffee is the best", "", ""),
    ("see you at the library to study", "", ""),
    ("i love instagram reels so much", "", ""),
    ("call me crazy but this was fun", "", ""),
    ("that movie from 2019 was great", "", ""),
    ("how was your day going", "", ""),
    ("are you free this evening", "", ""),
    ("that was a hundred percent amazing", "", ""),
    ("i met him at college yesterday", "", ""),
    ("the library is a nice quiet place", "", ""),
    ("lets catch the next bus together", "", ""),
    # partner's name must never be blocked for the sender (anti-de-anon rule):
    ("are you isha by any chance", "", "Hardik Jumnani"),
    ("nice talking to you today", "the canteen is nearby", ""),
    # Tally / run-length / Morse evasion must NOT false-positive on normal text:
    ("that was great ... really ... hmm ...", "", ""),
    ("wait...... are you even there", "", ""),
    ("ok. yes. no. maybe. sure.", "", ""),
    ("soooo good and niceeee work today", "", ""),
    ("noooo wayyyy that is wild", "", ""),
    ("here is a divider ---------- all done", "", ""),
    ("a b c d e f g h i j", "", ""),  # 10 pure single-char groups, all 1s -> no phone
    ("great work everyone 👍👍👍 👍👍 👍", "", ""),
    ("ooooooo ooooo o oooooo oo ooo oooo", "", ""),  # 7 pure groups but not a phone
]

# (text, prior_text, sender_name)
MALICIOUS: list[tuple[str, str, str]] = [
    ("9876543210", "", ""),
    ("my num is 98765 43210", "", ""),
    ("nine eight seven six five four three two one zero", "", ""),
    ("+1 415 555 2671", "", ""),
    ("ping me on insta @cool_guy", "", ""),
    ("add me on snapchat", "", ""),
    ("give me your number please", "", ""),
    ("whatsapp me", "", ""),
    ("foo at gmail dot com", "", ""),
    ("lets meet at the canteen tomorrow", "", ""),
    ("come to the library now", "", ""),
    ("share your location with me", "", ""),
    ("insta pe add kar", "", ""),            # hindi
    ("number bhej do", "", ""),              # hindi
    ("insta la add pannu", "", ""),          # tamil
    ("number aapo", "", ""),                 # gujarati
    ("addmeoninstagram", "", ""),            # glued
    ("instaaa add me", "", ""),              # stretch
    ("meet me at the cantin tomorrow", "", ""),  # fuzzy venue
    ("add me on іnsta", "", ""),       # confusable
    ("i am hardik", "", "Hardik Jumnani"),   # self-name (own)
    ("on insta", "add me", ""),              # cross-message steer
    ("canteen", "lets meet me at the", ""),  # cross-message meeting
    # Tally / run-length / Morse encodings of a phone (no literal digits) -> 9876543210
    ("......... ........ ....... ...... ..... .... ... .. . ..........", "", ""),  # dots
    ("ooooooooo oooooooo ooooooo oooooo ooooo oooo ooo oo o oooooooooo", "", ""),  # letters
    ("----. ---.. --... -.... ..... ....- ...-- ..--- .---- -----", "", ""),       # morse
    ("..... .... ... .. . ..........", "......... ........ ....... ......", ""),    # split across messages
]


class VeilCorpusTests(SimpleTestCase):
    def setUp(self) -> None:
        self.g = LeakGuard()

    def _scan(self, text, prior, name):
        return self.g.scan(
            text, prior_digits=extract_digits(prior), prior_text=prior, sender_name=name
        )

    def test_zero_false_positives_on_benign(self):
        fps = [
            (t, self._scan(t, p, n).top_category)
            for (t, p, n) in BENIGN
            if self._scan(t, p, n).blocked
        ]
        self.assertEqual(fps, [], f"Veil false positives (must be zero): {fps}")

    def test_malicious_recall(self):
        misses = [(t, p) for (t, p, n) in MALICIOUS if not self._scan(t, p, n).blocked]
        self.assertEqual(misses, [], f"Veil missed malicious cases: {misses}")
