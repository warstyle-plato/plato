import developaid_monitor as monitor
import developaid_monitor_manager as manager


def test_manager_install_is_idempotent_and_keeps_gantt_patch():
    manager.install()
    first_build = monitor.build
    first_gantt = monitor.gantt
    manager.install()
    assert monitor.build is first_build
    assert monitor.gantt is first_gantt
    # The dashboard layer may legitimately wrap manager._build afterwards.
    # Gantt itself remains the manager hierarchy, and manager is installed once.
    assert manager._INSTALLED is True
    assert manager._ORIGINAL_BUILD is not None
    assert monitor.gantt is manager._gantt
