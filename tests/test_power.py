from magpiary.power import KeepAwake


class FakeProcess:
    def __init__(self):
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self):
        pass


def test_it_starts_and_stops_the_macos_tool():
    spawned = []
    awake = KeepAwake(spawn=lambda: spawned.append(FakeProcess()) or spawned[-1])
    assert not awake.running
    assert awake.start() and awake.running
    assert awake.start() and len(spawned) == 1   # already on: no second process
    awake.stop()
    assert not awake.running and not spawned[0].alive


def test_it_reports_failure_when_the_tool_is_missing():
    def missing():
        raise FileNotFoundError("caffeinate")
    awake = KeepAwake(spawn=missing)
    assert awake.start() is False and not awake.running


def test_a_tool_that_exited_on_its_own_counts_as_off():
    proc = FakeProcess()
    awake = KeepAwake(spawn=lambda: proc)
    awake.start()
    proc.alive = False
    assert not awake.running
