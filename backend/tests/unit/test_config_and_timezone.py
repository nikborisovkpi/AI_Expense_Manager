from zoneinfo import ZoneInfo

import pytest

from app.core.config import Settings
from app.core.timezone import detect_local_timezone, validate_timezone


def test_settings_defaults_enforce_strict_zdr_and_localhost() -> None:
    settings = Settings(_env_file=None)
    assert settings.backend_host == "127.0.0.1"
    assert settings.openrouter_provider_zdr is True
    assert settings.openrouter_data_collection == "deny"
    assert settings.openrouter_require_parameters is True
    assert settings.default_currency == "RON"
    assert "http://localhost:3000" in settings.cors_origins_list


def test_settings_parses_ordered_fallback_models() -> None:
    settings = Settings(
        _env_file=None,
        OPENROUTER_FALLBACK_MODELS=" anthropic/claude-haiku-4.5 , openai/gpt-4.1-mini ,, ",
    )
    assert settings.fallback_models_list == [
        "anthropic/claude-haiku-4.5",
        "openai/gpt-4.1-mini",
    ]


def test_settings_rejects_relaxed_zdr_configuration() -> None:
    with pytest.raises(ValueError, match="Zero Data Retention"):
        Settings(_env_file=None, OPENROUTER_PROVIDER_ZDR=False)

    with pytest.raises(ValueError, match="data_collection"):
        Settings(_env_file=None, OPENROUTER_DATA_COLLECTION="allow")

    with pytest.raises(ValueError, match="require_parameters"):
        Settings(_env_file=None, OPENROUTER_REQUIRE_PARAMETERS=False)


def test_detect_local_timezone_returns_valid_iana_zone() -> None:
    tz_name = detect_local_timezone()
    tz = ZoneInfo(tz_name)
    assert tz.key == tz_name


def test_validate_timezone_accepts_iana_and_rejects_invalid() -> None:
    assert validate_timezone("Europe/Bucharest") == "Europe/Bucharest"
    assert validate_timezone("Europe/Kyiv") == "Europe/Kyiv"
    with pytest.raises(ValueError, match="Invalid IANA timezone"):
        validate_timezone("Mars/Olympus_Mons")
