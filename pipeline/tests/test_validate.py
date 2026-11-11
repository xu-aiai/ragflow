import pytest

from xc975_pipeline.validate import ValidationError, validate_source


def test_docx_accepted(tmp_path):
    p = tmp_path / "a.docx"
    p.write_bytes(b"PK\x03\x04" + b"0" * 100)
    assert validate_source(p) == "docx"


def test_doc_detected_for_conversion(tmp_path):
    p = tmp_path / "b.doc"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 100)
    assert validate_source(p) == "doc"


def test_esafenet_ciphertext_rejected(tmp_path):
    p = tmp_path / "c.docx"
    p.write_bytes(b"E-SafeNet XXXX LOCK" + b"0" * 100)
    with pytest.raises(ValidationError, match="密文"):
        validate_source(p)


def test_unknown_header_rejected(tmp_path):
    p = tmp_path / "d.docx"
    p.write_bytes(b"garbage!" * 10)
    with pytest.raises(ValidationError, match="无法识别"):
        validate_source(p)
