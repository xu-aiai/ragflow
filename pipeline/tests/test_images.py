from xc975_pipeline import images


def test_vector_conversion_uses_configured_soffice(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "find_soffice", lambda: "/fake/soffice")

    def fake_run(cmd, **kwargs):
        (tmp_path / "_tmp.png").write_bytes(b"png")

    monkeypatch.setattr(images.subprocess, "run", fake_run)

    name = images._convert_vector(tmp_path, "figure", ".emf", b"vector")

    assert name == "figure.png"
    assert (tmp_path / "figure.png").read_bytes() == b"png"
    assert not (tmp_path / "_tmp.emf").exists()
