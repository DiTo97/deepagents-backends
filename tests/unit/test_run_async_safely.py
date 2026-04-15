import asyncio
from unittest.mock import MagicMock, patch

import pytest

import deepagents_backends


async def _return_value(value=42):
    return value


async def _sleep_then_return(delay=0.1, value=42):
    await asyncio.sleep(delay)
    return value


async def _raise_error(message="boom"):
    raise RuntimeError(message)


def test_run_async_safely_without_running_loop_returns_result():
    assert deepagents_backends.run_async_safely(_return_value()) == 42


def test_run_async_safely_without_running_loop_times_out():
    with pytest.raises(TimeoutError):
        deepagents_backends.run_async_safely(_sleep_then_return(), timeout=0.01)


def test_run_async_safely_without_running_loop_reraises_exception():
    with pytest.raises(RuntimeError, match="boom"):
        deepagents_backends.run_async_safely(_raise_error())


@pytest.mark.asyncio
async def test_run_async_safely_with_running_loop_uses_async_thread_result():
    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = False
    fake_thread.result = 42
    fake_thread.exception = None

    with patch.object(deepagents_backends, "_AsyncThread", return_value=fake_thread) as mock_thread:
        result = deepagents_backends.run_async_safely(_return_value())

    assert result == 42
    fake_thread.start.assert_called_once_with()
    fake_thread.join.assert_called_once_with(timeout=None)

    coroutine = mock_thread.call_args.args[0]
    try:
        assert coroutine.cr_code.co_name == "_return_value"
    finally:
        coroutine.close()


@pytest.mark.asyncio
async def test_run_async_safely_with_running_loop_times_out():
    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = True

    with patch.object(deepagents_backends, "_AsyncThread", return_value=fake_thread) as mock_thread:
        with pytest.raises(TimeoutError, match="timed out"):
            deepagents_backends.run_async_safely(_return_value(), timeout=0.01)

    fake_thread.start.assert_called_once_with()
    fake_thread.join.assert_called_once_with(timeout=0.01)

    coroutine = mock_thread.call_args.args[0]
    coroutine.close()


@pytest.mark.asyncio
async def test_run_async_safely_with_running_loop_reraises_thread_exception():
    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = False
    fake_thread.result = None
    fake_thread.exception = RuntimeError("thread boom")

    with patch.object(deepagents_backends, "_AsyncThread", return_value=fake_thread) as mock_thread:
        with pytest.raises(RuntimeError, match="thread boom"):
            deepagents_backends.run_async_safely(_return_value())

    fake_thread.start.assert_called_once_with()
    fake_thread.join.assert_called_once_with(timeout=None)

    coroutine = mock_thread.call_args.args[0]
    coroutine.close()
