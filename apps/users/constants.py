"""Constants owned by the users domain."""

from __future__ import annotations

# Age bounds (years). MIN_AGE is the hard floor enforced at onboarding (a DOB
# implying an age below this is rejected) and the lowest value an age preference
# may use. MAX_AGE is the top of the age-preference range picker only; there is
# intentionally NO upper cap on signup age (a user older than MAX_AGE can still
# onboard, they simply fall outside any age filter's range). Surfaced to clients
# via GET /config -> age.{min_age,max_age}.
MIN_AGE = 17
MAX_AGE = 30
