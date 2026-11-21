"""Hypothesis profiles for gmake -C pbt check PROFILE=...

default: quick local run.  ci: the release gate (RELEASING.org).
Both print the seed so a failure can be replayed with --hypothesis-seed.
"""

from hypothesis import HealthCheck, settings

settings.register_profile(
    "default", max_examples=100, deadline=None, print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "ci", max_examples=1000, deadline=None, print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
