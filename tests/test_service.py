import plistlib
import subprocess
from pathlib import Path

import pytest

from magpiary import service


class FakeLaunchd:
    def __init__(self, fail_bootstrap=False, loaded=True, busy_bootstraps=0):
        self.calls, self.fail_bootstrap, self.loaded = [], fail_bootstrap, loaded
        self.busy_bootstraps = busy_bootstraps

    def __call__(self, command):
        self.calls.append(command)
        verb = command[1]
        if verb == "bootstrap" and self.busy_bootstraps:
            self.busy_bootstraps -= 1
            return subprocess.CompletedProcess(command, 5, "", "Bootstrap failed: 5: Input/output error")
        if verb == "bootstrap" and self.fail_bootstrap:
            return subprocess.CompletedProcess(command, 5, "", "Bootstrap failed: 5: Input/output error")
        if verb == "print":
            if not self.loaded:
                return subprocess.CompletedProcess(command, 113, "", "not found")
            if any(c[1] == "bootout" for c in self.calls) and not any(c[1] == "bootstrap" for c in self.calls):
                return subprocess.CompletedProcess(command, 113, "", "not found")  # stopped
            return subprocess.CompletedProcess(command, 0, "\tstate = running\n\tpid = 4242\n\tstate = x\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def program(home):
    path = home / ".local" / "bin" / "magpiary"
    path.parent.mkdir(parents=True)
    path.write_text("#!/bin/sh\n")
    return path


def test_install_writes_a_plist_that_starts_at_login_and_restarts(home, program):
    launchd = FakeLaunchd()
    service.install(program, 8765, launchd, env={}, wait=lambda s: None)
    data = plistlib.loads(service.plist_path().read_bytes())
    assert data["Label"] == service.LABEL
    assert data["ProgramArguments"] == [str(program), "serve", "--port", "8765"]
    assert data["RunAtLoad"] is True and data["KeepAlive"] is True
    assert data["StandardOutPath"] == str(service.log_path())
    assert service.log_path().parent.is_dir()
    verbs = [c[1] for c in launchd.calls]
    assert verbs == ["bootout", "print", "bootstrap", "kickstart"]  # waits for an older copy to stop, then starts


def test_data_folders_are_passed_on_only_when_set(home, program):
    service.install(program, 8765, FakeLaunchd(), env={"MAGPIARY_HOME": "/data", "SECRET_KEY": "nope"})
    env = plistlib.loads(service.plist_path().read_bytes())["EnvironmentVariables"]
    assert env["MAGPIARY_HOME"] == "/data" and "SECRET_KEY" not in env and "MAGPIARY_CONFIG" not in env


@pytest.mark.parametrize("folder", ["Documents", "Desktop", "Downloads"])
def test_a_program_in_a_protected_folder_is_refused_with_the_fix(home, folder):
    inside = home / folder / "Magpiary" / ".venv" / "bin" / "magpiary"
    inside.parent.mkdir(parents=True)
    inside.write_text("x")
    launchd = FakeLaunchd()
    with pytest.raises(service.ServiceError, match="uv tool install"):
        service.install(inside, 8765, launchd, env={})
    assert launchd.calls == [] and not service.plist_path().exists()


def test_a_missing_program_is_refused(home):
    with pytest.raises(service.ServiceError, match="not found"):
        service.install(home / "nowhere" / "magpiary", 8765, FakeLaunchd(), env={})


def test_launchd_refusal_is_explained(home, program):
    with pytest.raises(service.ServiceError, match="launchd refused"):
        service.install(program, 8765, FakeLaunchd(fail_bootstrap=True), env={}, wait=lambda s: None)


def test_uninstall_removes_the_service_and_is_safe_to_repeat(home, program):
    service.install(program, 8765, FakeLaunchd(), env={})
    assert "removed" in service.uninstall(FakeLaunchd())
    assert not service.plist_path().exists()
    assert "not installed" in service.uninstall(FakeLaunchd())


def test_status_reports_each_situation(home, program):
    assert service.status(8765, FakeLaunchd()) == "Not installed."
    service.install(program, 8765, FakeLaunchd(), env={})
    assert "not loaded" in service.status(8765, FakeLaunchd(loaded=False))
    text = service.status(8765, FakeLaunchd(), ping=lambda port: True)
    assert "state: running, process 4242" in text and "answering on port 8765: yes" in text
    assert "answering on port 8765: no" in service.status(8765, FakeLaunchd(), ping=lambda port: False)


def test_a_busy_launchd_is_tried_again(home, program):
    launchd = FakeLaunchd(busy_bootstraps=2)
    assert "installed" in service.install(program, 8765, launchd, env={}, wait=lambda s: None)
    assert [c[1] for c in launchd.calls].count("bootstrap") == 3


def test_the_service_starts_the_hub_through_the_magpiary_launcher(home, program):
    helper = home / "config" / "Magpiary.app" / "Contents" / "MacOS" / "magpiary-hub"
    service.install(program, 8765, FakeLaunchd(), env={}, wait=lambda s: None, helper=helper)
    args = plistlib.loads(service.plist_path().read_bytes())["ProgramArguments"]
    assert args == [str(helper), str(program), "serve", "--port", "8765"]


def test_the_dmg_app_uses_its_own_launcher(tmp_path):
    exe = tmp_path / "Magpiary.app" / "Contents" / "MacOS" / "magpiary-hub"
    program = tmp_path / "Magpiary.app" / "Contents" / "Resources" / "python" / "bin" / "magpiary"
    program.parent.mkdir(parents=True)
    assert service.bundled_helper(program) is None
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert service.bundled_helper(program) == exe
    assert service.bundled_helper(tmp_path / "bin" / "magpiary") is None


def test_no_command_line_tools_means_no_launcher_and_no_apple_pop_up():
    asked = []

    def run(command):
        asked.append(command[0])
        return subprocess.CompletedProcess(command, 2, "", "no developer tools")
    assert service.build_helper(run) is None
    assert asked == ["xcode-select"]   # nothing that would open Apple's "install the tools" window


def test_the_launcher_is_built_once_named_magpiary_and_passes_the_exit_status_on():
    if subprocess.run(["xcode-select", "-p"], capture_output=True).returncode != 0:
        pytest.skip("Apple's command line tools are not installed")
    exe = service.build_helper()
    assert exe and exe.is_file()
    info = plistlib.loads((exe.parents[1] / "Info.plist").read_bytes())
    assert info["CFBundleName"] == info["CFBundleDisplayName"] == "Magpiary" and info["LSBackgroundOnly"] is True
    assert (exe.parents[1] / "Resources" / "Magpiary.icns").stat().st_size > 1000
    assert subprocess.run([str(exe), "/bin/sh", "-c", "exit 3"]).returncode == 3
    built = exe.stat().st_mtime_ns
    assert service.build_helper() == exe and exe.stat().st_mtime_ns == built   # unchanged source: not rebuilt
