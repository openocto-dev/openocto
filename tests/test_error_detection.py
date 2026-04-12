"""Tests for OpenOctoApp._looks_like_error_response.

Some upstream proxies return backend errors as HTTP-200 chat content
instead of raising — those payloads must be detected so we don't read
them aloud through TTS.
"""

import pytest

from openocto.app import OpenOctoApp


@pytest.mark.parametrize("text", [
    'Failed to authenticate. API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"Invalid authentication credentials"}}',
    "API Error: 401 Unauthorized",
    '{"type":"error","error":{"message":"oops"}}',
    'API Error: 403 forbidden',
    "Failed to authenticate.",
    "Unauthorized — please re-login",
])
def test_detects_error_payloads(text):
    assert OpenOctoApp._looks_like_error_response(text) is True


@pytest.mark.parametrize("text", [
    "Привет! Как я могу помочь?",
    "The current time is 14:30",
    "Playing movie.mp4",
    "I encountered an issue understanding the request — could you rephrase?",
    "",
    "   ",
])
def test_passes_normal_responses(text):
    assert OpenOctoApp._looks_like_error_response(text) is False


def test_detects_case_insensitively():
    assert OpenOctoApp._looks_like_error_response("FAILED TO AUTHENTICATE") is True


def test_detects_when_padded_with_whitespace():
    assert OpenOctoApp._looks_like_error_response("\n\n  Failed to authenticate.") is True
