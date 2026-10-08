"""Settings parsing. _env_file=None keeps the developer's real .env out of it."""
import pytest

from src.config import Settings


@pytest.mark.parametrize("raw, expected", [
    ("1,2", [1, 2]),
    (" 1 , 2 ,3 ", [1, 2, 3]),
    ("42", [42]),
    ("", []),
    ("   ", []),
    ("1,abc", []),     # malformed -> nobody is admin, never a crash
])
def test_vk_admin_ids_parsing(raw, expected):
    assert Settings(_env_file=None, VK_ADMIN_IDS=raw).VK_ADMIN_IDS == expected


def test_vk_admin_ids_default_is_empty():
    assert Settings(_env_file=None).VK_ADMIN_IDS == []


def test_invite_limits_default_to_vk_safe_values():
    s = Settings(_env_file=None)

    assert s.VK_INVITE_DAILY_LIMIT == 40
    assert s.VK_INVITE_DELAY_SECONDS == 3
