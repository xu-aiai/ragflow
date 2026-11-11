import pytest

from xc975_pipeline import convert
from xc975_pipeline.convert import convert_to_docx


@pytest.fixture
def fake_soffice(tmp_path, monkeypatch):
    """伪装 LibreOffice：转换 = 直接写出目标文件。"""
    monkeypatch.setattr(convert, "find_soffice", lambda: "/fake/soffice")

    def fake_run(cmd, **kwargs):
        out_dir = cmd[cmd.index("--outdir") + 1]
        from pathlib import Path
        src = Path(cmd[-1])
        (Path(out_dir) / (src.stem + ".docx")).write_bytes(fake_run.payload)
        return None

    fake_run.payload = b"PK\x03\x04 fake docx"
    monkeypatch.setattr(convert.subprocess, "run", fake_run)
    return fake_run


def test_convert_plaintext_accepted(tmp_path, fake_soffice):
    src = tmp_path / "b.doc"
    src.write_bytes(b"\xd0\xcf\x11\xe0" + b"0" * 100)
    out = convert_to_docx(src, tmp_path / "out")
    assert out.name == "b.docx"
    assert out.read_bytes().startswith(b"PK\x03\x04")
    # 重复调用复用产物
    assert convert_to_docx(src, tmp_path / "out") == out


def test_convert_ciphertext_rejected(tmp_path, fake_soffice):
    fake_soffice.payload = b"E-SafeNet ciphertext"
    src = tmp_path / "b.doc"
    src.write_bytes(b"\xd0\xcf\x11\xe0" + b"0" * 100)
    with pytest.raises(RuntimeError, match="密文"):
        convert_to_docx(src, tmp_path / "out")
    assert not (tmp_path / "out" / "b.docx").exists()  # 密文产物被清除


def test_convert_no_converter(tmp_path, monkeypatch):
    monkeypatch.setattr(convert, "find_soffice", lambda: None)
    monkeypatch.setattr(convert.sys, "platform", "linux")
    src = tmp_path / "b.doc"
    src.write_bytes(b"\xd0\xcf\x11\xe0" + b"0" * 100)
    with pytest.raises(RuntimeError, match="LibreOffice"):
        convert_to_docx(src, tmp_path / "out")
