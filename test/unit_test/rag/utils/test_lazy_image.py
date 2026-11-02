from io import BytesIO

from PIL import Image

from rag.utils.lazy_image import LazyImage, flatten_to_rgb, stack_images_vertically


def _png_bytes(image):
    with BytesIO() as buffer:
        image.save(buffer, format="PNG")
        return buffer.getvalue()


def test_flatten_to_rgb_composites_rgba_transparency_onto_white():
    image = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
    image.putpixel((1, 0), (255, 0, 0, 255))

    flattened = flatten_to_rgb(image)

    assert flattened.mode == "RGB"
    assert flattened.getpixel((0, 0)) == (255, 255, 255)
    assert flattened.getpixel((1, 0)) == (255, 0, 0)


def test_flatten_to_rgb_composites_la_transparency_onto_white():
    image = Image.new("LA", (1, 1), (0, 0))

    flattened = flatten_to_rgb(image)

    assert flattened.mode == "RGB"
    assert flattened.getpixel((0, 0)) == (255, 255, 255)


def test_flatten_to_rgb_composites_palette_transparency_onto_white():
    image = Image.new("P", (1, 1), 0)
    image.putpalette([0, 0, 0] * 256)
    image.info["transparency"] = 0

    flattened = flatten_to_rgb(image)

    assert flattened.mode == "RGB"
    assert flattened.getpixel((0, 0)) == (255, 255, 255)


def test_lazy_image_uses_white_for_transparent_pixels():
    image = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    lazy_image = LazyImage([_png_bytes(image)])

    flattened = lazy_image.to_pil()

    assert flattened.mode == "RGB"
    assert flattened.getpixel((0, 0)) == (255, 255, 255)


def test_vertical_stack_uses_white_for_transparent_pixels():
    transparent = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    opaque = Image.new("RGB", (1, 1), (255, 0, 0))

    stacked = stack_images_vertically(transparent, opaque)

    assert stacked.mode == "RGB"
    assert stacked.getpixel((0, 0)) == (255, 255, 255)
    assert stacked.getpixel((0, 1)) == (255, 0, 0)
