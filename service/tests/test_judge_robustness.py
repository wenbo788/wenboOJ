import pytest
from unittest.mock import AsyncMock, patch
import httpx

from app.core.config import settings
from app.services import judge
from app.services.judge import (
    JudgeError,
    _build_compile_cmd,
    _run_cmd,
    try_run,
)


@pytest.mark.asyncio
async def test_run_cmd_connection_error_no_attribute_error():
    """沙箱连接失败（如 ConnectError）时，不应抛出 AttributeError，而应抛出 JudgeError。"""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")

    with pytest.raises(JudgeError) as exc_info:
        await _run_cmd(mock_client, {"args": ["echo", "1"]})

    assert "无法连接评测沙箱" in str(exc_info.value)


@pytest.mark.asyncio
async def test_run_cmd_http_status_error():
    """沙箱返回 HTTP 错误状态码时，应提取状态码并抛出 JudgeError。"""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    req = httpx.Request("POST", "http://test/run")
    resp = httpx.Response(503, request=req, text="Service Unavailable")
    mock_client.post.side_effect = httpx.HTTPStatusError("503", request=req, response=resp)

    with pytest.raises(JudgeError) as exc_info:
        await _run_cmd(mock_client, {"args": ["echo", "1"]})

    assert "无法连接评测沙箱" in str(exc_info.value)


def test_build_compile_cmd_defaults_and_toggle(monkeypatch):
    """验证编译参数生成：默认不带插件，开启配置后注入 -fplugin。"""
    base_cmd = ["g++", "-O2", "-std=c++14", "main.cpp", "-o", "main", "-lm"]

    # 默认关闭插件
    monkeypatch.setattr(settings, "ENABLE_NO_OPT_PRAGMA_PLUGIN", False)
    cmd1 = _build_compile_cmd(base_cmd, "cpp")
    assert not any("-fplugin=" in arg for arg in cmd1)

    # 开启配置
    monkeypatch.setattr(settings, "ENABLE_NO_OPT_PRAGMA_PLUGIN", True)
    cmd2 = _build_compile_cmd(base_cmd, "cpp")
    assert any("-fplugin=" in arg for arg in cmd2)
    assert cmd2[-5].startswith("-fplugin=")
    assert cmd2[-4] == "main.cpp"

    # 强制不带插件（fallback 时）
    cmd3 = _build_compile_cmd(base_cmd, "cpp", with_plugin=False)
    assert not any("-fplugin=" in arg for arg in cmd3)


@pytest.mark.asyncio
async def test_try_run_cleans_up_cached_binary(monkeypatch):
    """自测运行完成或失败后，必须在 finally 中调用 _delete_file 清理沙箱缓存文件。"""
    deleted_files = []

    async def fake_run_cmd(client, cmd):
        args = cmd.get("args", [])
        if "g++" in args:
            return {"status": "Accepted", "fileIds": {"main": "cached_bin_12345"}}
        return {
            "status": "Accepted",
            "files": {"stdout": "hello\n", "stderr": ""},
            "time": 5_000_000,
            "memory": 1024 * 1024,
        }

    async def fake_delete_file(client, fid):
        deleted_files.append(fid)

    monkeypatch.setattr(judge, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(judge, "_delete_file", fake_delete_file)

    res = await try_run(
        language="cpp",
        code="int main(){return 0;}",
        input_data="",
        time_limit_ms=1000,
        memory_mb=128,
    )
    assert res["status"] == "ok"
    assert "cached_bin_12345" in deleted_files


@pytest.mark.asyncio
async def test_try_run_plugin_compile_error_auto_fallback(monkeypatch):
    """自测环境若因插件加载失败导致 CE，应自动降级为无插件重新编译并成功。"""
    monkeypatch.setattr(settings, "ENABLE_NO_OPT_PRAGMA_PLUGIN", True)
    calls = []

    async def fake_run_cmd(client, cmd):
        args = cmd.get("args", [])
        calls.append(list(args))
        if "g++" in args:
            if any("-fplugin=" in a for a in args):
                return {
                    "status": "Nonzero Exit Status",
                    "files": {
                        "stderr": "g++: error: cannot load plugin /usr/local/lib/oj/no_opt_pragma.so: No such file"
                    },
                }
            # 降级后的无插件编译成功
            return {"status": "Accepted", "fileIds": {"main": "fallback_bin"}}
        return {
            "status": "Accepted",
            "files": {"stdout": "success\n"},
            "time": 2_000_000,
            "memory": 1024 * 1024,
        }

    monkeypatch.setattr(judge, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(judge, "_delete_file", AsyncMock())

    res = await try_run(
        language="cpp",
        code="int main(){return 0;}",
        input_data="",
        time_limit_ms=1000,
        memory_mb=128,
    )
    assert res["status"] == "ok"
    assert res["stdout"] == "success\n"
    # 验证第一遍带插件，第二遍自动降级无插件
    assert any("-fplugin=" in a for a in calls[0])
    assert not any("-fplugin=" in a for a in calls[1])
