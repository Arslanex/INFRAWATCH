"""Regression: read() must forward keyword arguments (see _thread.read)."""
import asyncio
import threading

from iw_agent.core._thread import read


def _sample(a, b, *, c=0, d=0):
    return a, b, c, d


def test_read_forwards_positional_args():
    assert asyncio.run(read(_sample, 1, 2)) == (1, 2, 0, 0)


def test_read_forwards_keyword_args():
    assert asyncio.run(read(_sample, 1, 2, c=3, d=4)) == (1, 2, 3, 4)


def test_read_accepts_keyword_only_call():
    assert asyncio.run(read(lambda *, x: x * 2, x=21)) == 42


def test_read_runs_off_the_event_loop_on_one_thread():
    names = {asyncio.run(read(lambda: threading.current_thread().name)) for _ in range(3)}
    assert len(names) == 1
    assert threading.current_thread().name not in names
