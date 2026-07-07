from src.adapters.funnel import CommandResult, FunnelController


class FakeRunner:
    def __init__(self, result: CommandResult):
        self.result = result
        self.calls: list[list[str]] = []

    def run(self, args):
        self.calls.append(args)
        return self.result


def test_enable_runs_funnel_bg_and_returns_true():
    runner = FakeRunner(CommandResult(0, "Funnel started", ""))
    ctrl = FunnelController(port=8096, runner=runner)
    assert ctrl.enable() is True
    assert runner.calls[0] == ["tailscale", "funnel", "--bg", "8096"]


def test_enable_returns_false_on_failure():
    runner = FakeRunner(CommandResult(1, "", "not enabled"))
    ctrl = FunnelController(port=8096, runner=runner)
    assert ctrl.enable() is False


def test_disable_runs_off():
    runner = FakeRunner(CommandResult(0, "", ""))
    ctrl = FunnelController(port=8096, runner=runner)
    assert ctrl.disable() is True
    assert runner.calls[0] == ["tailscale", "funnel", "--https=443", "off"]


def test_is_on_parses_status():
    runner = FakeRunner(CommandResult(0, "# Funnel on:\n#  - https://x", ""))
    ctrl = FunnelController(port=8096, runner=runner)
    assert ctrl.is_on() is True


def test_is_on_false_when_no_config():
    runner = FakeRunner(CommandResult(0, "No serve config", ""))
    ctrl = FunnelController(port=8096, runner=runner)
    assert ctrl.is_on() is False
