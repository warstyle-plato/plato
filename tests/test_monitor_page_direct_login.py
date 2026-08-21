from developaid_monitor_page import MONITOR_PAGE


def test_monitor_has_direct_telegram_login():
    assert "Войти через Telegram" in MONITOR_PAGE
    assert "/auth/telegram/start" in MONITOR_PAGE
    assert "/auth/telegram/claim" in MONITOR_PAGE
    assert "method:'POST'" in MONITOR_PAGE


def test_monitor_uses_the_shared_developaid_session():
    assert "developaid_web_session" in MONITOR_PAGE
    assert "plato_projects_key" in MONITOR_PAGE


def test_monitor_does_not_query_private_data_before_login():
    assert "if(!hasAuth())" in MONITOR_PAGE
    assert "Войдите через Telegram" in MONITOR_PAGE
