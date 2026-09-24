"""Perceptual image hashing (dHash) to spot listings that reuse the same product photo."""

from __future__ import annotations

import io

import requests

try:
    from PIL import Image
except ImportError:  # image matching is optional
    Image = None

HASH_SIZE = 8


def dhash(image_bytes: bytes, size: int = HASH_SIZE) -> int:
    """64-bit difference hash: survives resizing, recompression and small edits."""
    if Image is None:
        raise RuntimeError("Pillow is not installed (pip install 'arbitrage[images]')")
    img = Image.open(io.BytesIO(image_bytes)).convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = img.tobytes()
    bits = 0
    for row in range(size):
        for col in range(size):
            left = px[row * (size + 1) + col]
            right = px[row * (size + 1) + col + 1]
            bits = (bits << 1) | (left > right)
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class ImageHasher:
    """Downloads and hashes images once per URL. Failures count as "no image signal", not errors."""

    def __init__(self, session=None, timeout: float = 10):
        self.session = session or requests.Session()
        self.timeout = timeout
        self._cache: dict[str, int | None] = {}

    @staticmethod
    def available() -> bool:
        return Image is not None

    def hash(self, url: str) -> int | None:
        if url not in self._cache:
            try:
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                self._cache[url] = dhash(resp.content)
            except (requests.RequestException, OSError, ValueError, RuntimeError):
                self._cache[url] = None
        return self._cache[url]

    def distance(self, url_a: str, url_b: str) -> int | None:
        ha, hb = self.hash(url_a), self.hash(url_b)
        if ha is None or hb is None:
            return None
        return hamming(ha, hb)
