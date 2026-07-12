"""
Shared pytest fixtures for the backend test suite.
"""
import pytest


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """
    Clear the in-memory login/registration rate-limit state before every
    test. Without this, the real (and intentionally strict) production rate
    limiters -- 5 failed logins/60s per email, 5 registrations/hour per IP --
    get tripped across test modules that all originate from the same test
    client "IP", causing unrelated tests later in the run to fail with 429s
    that have nothing to do with what they're actually testing.

    This resets test state only; it does not change the rate limiters'
    production behavior in any way.
    """
    import api.main as m
    m.failed_logins.clear()
    m.registration_attempts.clear()
    yield
    m.failed_logins.clear()
    m.registration_attempts.clear()
