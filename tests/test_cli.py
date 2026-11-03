from magpiary import __version__
from magpiary.cli import main


def test_version_flag_prints_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exit_:
        assert exit_.code == 0
    assert f"magpiary {__version__}" in capsys.readouterr().out


def test_no_arguments_shows_help(capsys):
    assert main([]) == 0
    assert "usage: magpiary" in capsys.readouterr().out
