"""Compression, the ticker's poll interval, and the connection pool: the three settings that
were tuned for one process and are wrong for four.

Measured 2026-10-20/21. Ten open tabs stalled the dashboard, and the fix was to stop serving
everything from one process. These are the settings that came with it:

* **gzip.** An instrument page is a few hundred kilobytes of repeated markup, and it was going
  over the LAN uncompressed. Compression is the cheapest single line in the whole change.
* **the ticker's poll.** It was every two seconds, per open tab, and each poll is a database
  round trip through the threadpool. The stream only carries a cursor, so five seconds of
  staleness on a banner nobody is watching costs nothing.
* **the pool.** Five warm connections per process, sized when one process served every page.

None of the three was the measured bottleneck -- the concurrency cliff was CPU in a single
process -- so these tests assert the configuration, not a speedup.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from starlette.middleware.gzip import GZipMiddleware

from awltux.db.session import MAX_OVERFLOW, POOL_SIZE, create_db_engine
from awltux.main import MIN_GZIP_BYTES
from awltux.web.routes import news
from tests.helpers import make_instrument

TICKER = "GZIP_US_EQ"


def _seed(session) -> None:
    session.add(make_instrument(TICKER, name="Compression Holdings", sector="Technologies"))
    session.commit()


class TestThePagesAreCompressed:
    def test_a_page_arrives_gzipped(self, client, session):
        """The reader waits for the bytes, so the bytes are what to shrink."""
        _seed(session)

        page = client.get(f"/instrument/{TICKER}")

        assert page.status_code == 200
        assert page.headers.get("content-encoding") == "gzip"
        assert "Compression Holdings" in page.text, "and decompresses to the real page"

    def test_a_client_that_does_not_ask_for_gzip_gets_the_page_whole(self, client, session):
        """Nothing may *require* gzip: the page is served as before to any client."""
        _seed(session)

        page = client.get(f"/instrument/{TICKER}", headers={"accept-encoding": "identity"})

        assert page.status_code == 200
        assert "content-encoding" not in page.headers
        assert "Compression Holdings" in page.text

    def test_a_small_answer_is_left_alone(self, client):
        """Below the threshold, compression loses: framing costs more than it saves."""
        health = client.get("/healthz")

        assert health.status_code == 200
        assert len(health.content) < MIN_GZIP_BYTES, "this test is about a small body"
        assert "content-encoding" not in health.headers

    def test_an_event_stream_is_never_compressed(self):
        """A compressed stream cannot be flushed frame by frame, so the ticker must not get it.

        Asserted against the middleware itself rather than against the live route, because the
        live route is an endless stream: what is being checked is that `GZipMiddleware`'s
        exclusion covers the content type the ticker declares.
        """
        app = FastAPI()
        app.add_middleware(GZipMiddleware, minimum_size=100)

        @app.get("/stream")
        async def stream() -> StreamingResponse:
            async def frames():
                for index in range(200):
                    yield f"data: {index}\n\n".encode()

            return StreamingResponse(frames(), media_type="text/event-stream")

        with TestClient(app) as mini:
            response = mini.get("/stream")

        assert "content-encoding" not in response.headers
        assert response.text.startswith("data: 0")


class TestTheTickerPollsLessOften:
    def test_the_interval_is_seconds_not_milliseconds(self):
        """A poll is a database round trip; the banner only needs to know it went stale."""
        assert news.POLL_SECONDS >= 5.0

    def test_the_keepalive_still_fits_inside_the_idle_limit(self):
        """The poll rate is also the keepalive rate, so it cannot approach the idle limit."""
        assert news.MAX_IDLE_SECONDS / news.POLL_SECONDS >= 60, (
            "an abandoned stream would close almost immediately"
        )


class TestThePoolIsSizedForTheWebTier:
    def test_the_engine_uses_the_configured_pool(self, settings):
        """Five warm connections is one page load's concurrency, not four workers' worth."""
        engine = create_db_engine(settings)
        try:
            assert engine.pool.size() == POOL_SIZE
            # QueuePool keeps the ceiling private and exposes only the *current* overflow, so
            # this is the one place the configured value can be read back.
            assert engine.pool._max_overflow == MAX_OVERFLOW
        finally:
            engine.dispose()

    def test_the_pool_is_larger_than_the_old_default(self):
        """The SQLAlchemy default was 5 + 10; the point of the change is that it is not that."""
        assert POOL_SIZE > 5
        assert POOL_SIZE + MAX_OVERFLOW >= 10
