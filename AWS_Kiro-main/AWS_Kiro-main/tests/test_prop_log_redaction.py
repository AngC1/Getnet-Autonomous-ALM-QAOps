"""Property 22: Redaccion en logs. Solo valores ficticios generados."""
import logging

from hypothesis import assume, given, settings, strategies as st

from brand_verifier import secrets as sec

_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
secret_st = st.text(alphabet=_ALPHABET, min_size=8, max_size=40)
context_st = st.text(alphabet="abc xyz:=,", max_size=20)


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


# Feature: atm-card-incident-video-simulation, Property 22: Redacción en logs
# Validates: Requirements 10.7
@settings(max_examples=100, deadline=None)
@given(secret=secret_st, prefix=context_st, suffix=context_st, use_args=st.booleans())
def test_logged_secret_is_redacted(secret, prefix, suffix, use_args):
    assume(secret not in sec.REDACTED)
    sec.clear_registered_secrets()
    logger = logging.getLogger("test_prop_log_redaction")
    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        sec.register_secret(secret)
        if use_args:
            logger.info(prefix + "%s" + suffix, secret)
        else:
            logger.info(prefix + secret + suffix)
        assert len(handler.messages) == 1
        message = handler.messages[0]
        assert secret not in message
        assert sec.REDACTED in message
    finally:
        logger.removeHandler(handler)
        sec.clear_registered_secrets()
