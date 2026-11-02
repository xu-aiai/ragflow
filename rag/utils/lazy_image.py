import logging
from io import BytesIO

from PIL import Image


def flatten_to_rgb(img):
    """Convert a PIL image to RGB, compositing transparency onto white."""
    if not isinstance(img, Image.Image) or img.mode == "RGB":
        return img

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        rgba.close()
        return background

    return img.convert("RGB")


def stack_images_vertically(img1, img2):
    """Stack two PIL images on a white RGB canvas without black transparency."""
    flat1 = flatten_to_rgb(img1)
    flat2 = flatten_to_rgb(img2)
    width1, height1 = flat1.size
    width2, height2 = flat2.size
    canvas = Image.new("RGB", (max(width1, width2), height1 + height2), (255, 255, 255))
    canvas.paste(flat1, (0, 0))
    canvas.paste(flat2, (0, height1))
    if flat1 is not img1:
        flat1.close()
    if flat2 is not img2:
        flat2.close()
    return canvas


class LazyImage:
    def __init__(self, blobs, source=None):
        self._blobs = [b for b in (blobs or []) if b]
        self.source = source
        self._pil = None

    def __bool__(self):
        return bool(self._blobs)

    def to_pil(self):
        if self._pil is not None:
            try:
                self._pil.load()
                return self._pil
            except Exception:
                try:
                    self._pil.close()
                except Exception:
                    pass
                self._pil = None
        res_img = None
        for blob in self._blobs:
            try:
                image = flatten_to_rgb(Image.open(BytesIO(blob)))
            except Exception as e:
                logging.info(f"LazyImage: skip bad image blob: {e}")
                continue

            if res_img is None:
                res_img = image
                continue

            from rag.nlp import concat_img

            new_img = concat_img(res_img, image)
            if new_img is not res_img:
                try:
                    res_img.close()
                except Exception:
                    pass
            try:
                image.close()
            except Exception:
                pass
            res_img = new_img

        self._pil = res_img
        return self._pil

    def to_pil_detached(self):
        pil = self.to_pil()
        self._pil = None
        return pil

    def close(self):
        if self._pil is not None:
            try:
                self._pil.close()
            except Exception:
                pass
            self._pil = None
        return None

    def __getattr__(self, name):
        pil = self.to_pil()
        if pil is None:
            raise AttributeError(name)
        return getattr(pil, name)

    def __array__(self, dtype=None):
        import numpy as np

        pil = self.to_pil()
        if pil is None:
            return np.array([], dtype=dtype)
        return np.array(pil, dtype=dtype)

    def __enter__(self):
        return self.to_pil()

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    @staticmethod
    def merge(a, b):
        """
        Merge two LazyImage instances by combining their blob lists.
        """
        a_blobs = a._blobs if isinstance(a, LazyImage) else []
        b_blobs = b._blobs if isinstance(b, LazyImage) else []
        combined = a_blobs + b_blobs
        if not combined:
            return None
        merged = LazyImage(combined)
        return merged


LazyDocxImage = LazyImage


def ensure_pil_image(img):
    if isinstance(img, Image.Image):
        return img
    if isinstance(img, LazyImage):
        return img.to_pil()
    return None


def is_image_like(img):
    return isinstance(img, Image.Image) or isinstance(img, LazyImage)


def open_image_for_processing(img, *, allow_bytes=False):
    if isinstance(img, Image.Image):
        return img, False
    if isinstance(img, LazyImage):
        return img.to_pil_detached(), True
    if allow_bytes and isinstance(img, (bytes, bytearray)):
        try:
            pil = flatten_to_rgb(Image.open(BytesIO(img)))
            return pil, True
        except Exception as e:
            logging.info(f"open_image_for_processing: bad bytes: {e}")
            return None, False
    return img, False
