import pytest

from swarm.output import UnsafePathError, safe_src_path, write_code_files


@pytest.fixture
def src(tmp_path):
    root = tmp_path / "run" / "src"
    root.mkdir(parents=True)
    return root


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("app.py", "app.py"),
        ("pkg/mod.py", "pkg/mod.py"),
        ("./pkg/./mod.py", "pkg/mod.py"),
        ("src/app.py", "app.py"),  # a leading src/ is stripped
        ("tests\\test_app.py", "tests/test_app.py"),  # Windows separators
    ],
)
def test_safe_paths_stay_inside_src(src, raw, expected):
    assert safe_src_path(src, raw) == (src / expected).resolve()


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "../evil.py",
        "pkg/../../evil.py",
        "..\\..\\evil.py",
        "/etc/passwd",
        "C:\\Windows\\evil.py",
        "c:evil.py",
        "src",
        "bad\x00name.py",
    ],
)
def test_unsafe_paths_are_rejected(src, raw):
    with pytest.raises(UnsafePathError):
        safe_src_path(src, raw)


def test_symlink_out_of_src_is_rejected(src, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (src / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePathError):
        safe_src_path(src, "link/evil.py")


def test_write_code_files_writes_safe_and_reports_unsafe(tmp_path):
    run_dir = tmp_path / "run"
    written, rejected = write_code_files(
        str(run_dir), {"src/app.py": "print('hi')\n", "../escape.py": "boom"}
    )
    assert written == {"app.py": "print('hi')\n"}
    assert (run_dir / "src" / "app.py").read_text() == "print('hi')\n"
    assert len(rejected) == 1 and rejected[0].startswith("../escape.py")
    assert not (run_dir / "escape.py").exists()
    assert not (tmp_path / "escape.py").exists()
