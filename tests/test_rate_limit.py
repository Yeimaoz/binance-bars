from unittest.mock import MagicMock, patch
import pytest

from binance_bars.rate_limit import get_with_backoff, RateLimitedError, IpBannedError


def test_get_normal_response_returns_immediately():
    resp_ok = MagicMock(status_code=200, headers={"X-MBX-USED-WEIGHT-1M": "5"})
    resp_ok.raise_for_status = MagicMock()
    with patch("binance_bars.rate_limit.httpx.Client.get", return_value=resp_ok):
        out = get_with_backoff("https://api.binance.com/x", {})
    assert out is resp_ok


def test_get_429_with_retry_after_sleeps_and_retries():
    resp_429 = MagicMock(status_code=429, headers={"Retry-After": "1"})
    resp_ok = MagicMock(status_code=200, headers={"X-MBX-USED-WEIGHT-1M": "5"})
    with patch("binance_bars.rate_limit.httpx.Client.get",
               side_effect=[resp_429, resp_ok]), \
         patch("binance_bars.rate_limit.time.sleep") as sleep_mock:
        out = get_with_backoff("https://api.binance.com/x", {})
    assert out is resp_ok
    assert sleep_mock.call_args[0][0] == 1


def test_get_429_twice_raises():
    resp_429 = MagicMock(status_code=429, headers={"Retry-After": "1"})
    with patch("binance_bars.rate_limit.httpx.Client.get", return_value=resp_429), \
         patch("binance_bars.rate_limit.time.sleep"):
        with pytest.raises(RateLimitedError):
            get_with_backoff("https://api.binance.com/x", {})


def test_get_418_ip_banned_raises_immediately():
    resp_418 = MagicMock(status_code=418, headers={})
    with patch("binance_bars.rate_limit.httpx.Client.get", return_value=resp_418):
        with pytest.raises(IpBannedError):
            get_with_backoff("https://api.binance.com/x", {})


def test_get_429_retry_after_http_date_falls_back_to_one_second():
    """Retry-After value in HTTP-date format must not raise ValueError; fall back to 1s."""
    resp_429 = MagicMock(
        status_code=429,
        headers={"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"},
    )
    resp_ok = MagicMock(status_code=200, headers={})
    with patch("binance_bars.rate_limit.httpx.Client.get",
               side_effect=[resp_429, resp_ok]), \
         patch("binance_bars.rate_limit.time.sleep") as sleep_mock:
        out = get_with_backoff("https://api.binance.com/x", {})
    assert out is resp_ok
    # Must not crash, and must sleep a sensible default (1s)
    assert sleep_mock.call_args[0][0] == 1


def test_get_429_retry_after_large_value_is_capped():
    """Retry-After value larger than _MAX_RETRY_AFTER must be clamped to the cap."""
    resp_429 = MagicMock(status_code=429, headers={"Retry-After": "86400"})
    resp_ok = MagicMock(status_code=200, headers={})
    with patch("binance_bars.rate_limit.httpx.Client.get",
               side_effect=[resp_429, resp_ok]), \
         patch("binance_bars.rate_limit.time.sleep") as sleep_mock:
        out = get_with_backoff("https://api.binance.com/x", {})
    assert out is resp_ok
    slept = sleep_mock.call_args[0][0]
    assert slept <= 300, f"sleep was not capped: slept {slept}s"
