"""تست‌های واحد برای کیبورد و هندلرهای لغو ترجمه در ربات تلگرام."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.bot.keyboards import get_cancel_keyboard
from app.bot.handlers import (
    handle_cancel_callback,
    handle_cancel_command,
    _ACTIVE_TASKS,
    _USER_ACTIVE_JOBS,
)


def test_get_cancel_keyboard():
    kb = get_cancel_keyboard("job_123")
    assert len(kb.inline_keyboard) == 1
    button = kb.inline_keyboard[0][0]
    assert "لغو" in button.text
    assert button.callback_data == "cancel:job_123"


@pytest.mark.asyncio
async def test_handle_cancel_callback_active_task():
    # Setup dummy task
    async def dummy_coro():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy_coro())
    job_id = "test_job_1"
    _ACTIVE_TASKS[job_id] = task

    callback = MagicMock()
    callback.data = f"cancel:{job_id}"
    callback.answer = AsyncMock()

    try:
        await handle_cancel_callback(callback)
        assert task.cancelling() > 0 or task.cancelled()
        callback.answer.assert_called_once_with("فرآیند ترجمه متوقف شد.", show_alert=True)
    finally:
        _ACTIVE_TASKS.pop(job_id, None)
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_handle_cancel_callback_inactive_task():
    callback = MagicMock()
    callback.data = "cancel:non_existent_job"
    callback.answer = AsyncMock()

    await handle_cancel_callback(callback)
    callback.answer.assert_called_once_with("این فرآیند قبلاً به پایان رسیده یا لغو شده است.", show_alert=False)


@pytest.mark.asyncio
async def test_handle_cancel_command_active_task():
    async def dummy_coro():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy_coro())
    user_id = 99999
    job_id = "user_job_99999"

    _ACTIVE_TASKS[job_id] = task
    _USER_ACTIVE_JOBS[user_id] = job_id

    message = MagicMock()
    message.from_user.id = user_id
    message.reply = AsyncMock()

    try:
        await handle_cancel_command(message)
        assert task.cancelling() > 0 or task.cancelled()
        message.reply.assert_called_once()
        assert "لغو" in message.reply.call_args[0][0]
    finally:
        _ACTIVE_TASKS.pop(job_id, None)
        _USER_ACTIVE_JOBS.pop(user_id, None)
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_handle_cancel_command_no_active_job():
    message = MagicMock()
    message.from_user.id = 88888
    message.reply = AsyncMock()

    await handle_cancel_command(message)
    message.reply.assert_called_once()
    assert "هیچ فرآیند ترجمه فعالی" in message.reply.call_args[0][0]
