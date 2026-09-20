import requests

from collectors import common


class FakeResponse:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._content = False
        self._content_consumed = False

    def iter_content(self, chunk_size=65536):
        yield from self._chunks


def test_read_response_buffers_content():
    response = FakeResponse([b'{"a":', b"1}"])
    result = common._read_response_with_deadline(response, total_timeout=5)
    assert result._content == b'{"a":1}'
    assert result._content_consumed is True


def test_timeout_is_connect_read_tuple():
    assert isinstance(common.TIMEOUT, tuple)
    assert len(common.TIMEOUT) == 2
    assert common.TIMEOUT[0] > 0
    assert common.TIMEOUT[1] > 0


def test_retries_are_bounded():
    assert common.REQUEST_RETRIES >= 1
    assert common.REQUEST_RETRIES <= 5
