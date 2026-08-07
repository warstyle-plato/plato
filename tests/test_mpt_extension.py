from mpt_extension import _MENU_TEXT, _append_query, _main_menu_with_mpt, inject_mpt_panel


def test_query_keeps_existing_session_and_adds_mpt_section():
    url = _append_query("https://example.test/app?session=abc", section="mpt")
    assert "session=abc" in url
    assert "section=mpt" in url


def test_mpt_is_added_only_to_main_reply_keyboard():
    main = {"keyboard": [[{"text": "Посчитать ВРИ и ТЭП"}]], "resize_keyboard": True}
    updated = _main_menu_with_mpt(main)
    assert updated is not main
    assert updated["keyboard"][-1][0]["text"] == _MENU_TEXT
    assert _MENU_TEXT not in str(main)

    temporary = {"keyboard": [[{"text": "Да"}], [{"text": "Нет"}]]}
    assert _main_menu_with_mpt(temporary) is temporary


def test_mpt_menu_is_not_duplicated():
    markup = {"keyboard": [[{"text": "Посчитать ВРИ и ТЭП"}], [{"text": _MENU_TEXT}]]}
    assert _main_menu_with_mpt(markup) is markup


def test_page_injection_is_idempotent():
    source = "<html><body><main>ВРИ</main></body></html>"
    once = inject_mpt_panel(source)
    twice = inject_mpt_panel(once)
    assert 'id="mpt-benefit-template"' in once
    assert once == twice
