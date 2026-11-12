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


def test_image_dimensions_are_collected_from_extracted_files(tmp_path):
    from PIL import Image

    Image.new("RGB", (20, 10)).save(tmp_path / "figure.png")

    assert images.image_dimensions(tmp_path, {"r1": "figure.png"}) == {
        "figure.png": {"width": 20, "height": 10}
    }


def test_white_canvas_is_trimmed_with_safe_padding():
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(image).rectangle((40, 20, 60, 40), fill="black")

    trimmed = images._trim_white_border(image)

    assert trimmed.size == (45, 45)


def test_converted_vector_image_is_trimmed_too(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw

    from xc975_pipeline.audit import AuditLog

    image = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(image).rectangle((40, 20, 60, 40), fill="black")
    image.save(tmp_path / "source.png")

    def fake_convert(img_dir, stem, ext, blob):
        target = img_dir / f"{stem}.png"
        target.write_bytes((tmp_path / "source.png").read_bytes())
        return target.name

    monkeypatch.setattr(images, "_convert_vector", fake_convert)

    name = images._save(tmp_path, "figure", ".emf", b"vector", 800, AuditLog())

    with Image.open(tmp_path / name) as converted:
        assert converted.size == (45, 45)
