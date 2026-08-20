import developaid_monitor as monitor
import developaid_monitor_manager as manager


def test_manager_install_is_idempotent_and_patches_server_functions():
    manager.install()
    first_build = monitor.build
    first_gantt = monitor.gantt
    manager.install()
    assert monitor.build is first_build
    assert monitor.gantt is first_gantt
    assert monitor.build is manager._build
    assert monitor.gantt is manager._gantt
