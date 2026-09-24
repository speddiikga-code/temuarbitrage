import io

import pytest

from arbitrage.images import ImageHasher, dhash, hamming

from conftest import FakeResponse, FakeSession

Image = pytest.importorskip("PIL.Image")


def png(width, height, pixel):
    img = Image.new("L", (width, height))
    img.putdata([pixel(x, y) for y in range(height) for x in range(width)])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def gradient(w, h):
    return png(w, h, lambda x, y: (x * 255) // w)


def checker(w, h):
    return png(w, h, lambda x, y: 255 if (x // (w // 4) + y // (h // 4)) % 2 else 0)


def test_resized_copy_hashes_the_same():
    assert hamming(dhash(gradient(400, 400)), dhash(gradient(123, 123))) <= 2


def test_different_images_are_far_apart():
    assert hamming(dhash(gradient(200, 200)), dhash(checker(200, 200))) > 10


def test_hasher_caches_and_tolerates_failures():
    session = FakeSession(FakeResponse(content=gradient(64, 64)), FakeResponse(status_code=404))
    hasher = ImageHasher(session=session)
    assert hasher.distance("a.png", "a.png") == 0
    assert hasher.distance("a.png", "missing.png") is None
    assert len(session.calls) == 2
