# -*- coding: utf-8 -*-
"""C2 round 18: cover vision prep, chat_turn, run_turn_events, subagent loop,
readline/completer, print helpers, provider config, permission, login, plan, fallback.
"""
import json
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yousini
from yousini import Agent


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _TC:
    def __init__(self, index, id_, fn):
        self.index = index
        self.id = id_
        self.function = fn


@pytest.fixture()
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr(yousini, "CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(yousini, "SESSION_DIR", tmp_path / "sessions")
    (tmp_path / "sessions").mkdir(exist_ok=True)
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    a = Agent(model="test-model", cwd=str(tmp_path))
    a.confirm_files = False
    a.interactive = False
    monkeypatch.setattr(a, "compact", lambda: None)
    return a


# ---------- Group A+Q: _prepare_user_content / _model_supports_vision ----------

def test_prepare_no_img(agent):
    content, w = yousini._prepare_user_content("hello world", agent)
    assert content == "hello world"
    assert w == []


def test_prepare_vision_import_error(agent):
    import types as _types
    _mod = _types.ModuleType("yousini_vision")

    def _failing_cwi(*a, **k):
        raise RuntimeError("vision broken")

    _mod.content_with_images = _failing_cwi
    with mock.patch.dict(sys.modules, {"yousini_vision": _mod}):
        content, w = yousini._prepare_user_content("[img:test.png] hello", agent)
    assert content == "[img:test.png] hello"


def test_prepare_vision_str_result(agent):
    mv = mock.MagicMock()
    mv.content_with_images.return_value = "str_content"
    with mock.patch.dict(sys.modules, {"yousini_vision": mv}):
        content, w = yousini._prepare_user_content("[img:test.png] hello", agent)
    assert content == "str_content"
    assert any("มี [img:...] แต่ไม่พบรูปที่โหลดได้ (ไฟล์ไม่มี, อยู่คนละโฟลเดอร์, หรือใหญ่เกิน 4MB) — " in s for s in w)


def test_prepare_vision_not_vision_model(agent):
    agent.model = "gpt-3.5-turbo"
    mv = mock.MagicMock()
    mv.content_with_images.return_value = [{"type": "image_url"}]
    with mock.patch.dict(sys.modules, {"yousini_vision": mv}):
        content, w = yousini._prepare_user_content("[img:test.png] hello", agent)
    assert any("vision" in s for s in w)


def test_model_supports_vision_true():
    assert yousini._model_supports_vision("pixtral-large-latest") is True


def test_model_supports_vision_false():
    assert yousini._model_supports_vision("gpt-3.5-turbo") is False


# ---------- Group B: chat_turn ----------

def test_chat_turn_warning(agent, monkeypatch):
    printed = []
    spy = mock.MagicMock()
    spy.side_effect = lambda *a, **k: printed.append(str(a))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini.console, "print", spy)
    monkeypatch.setattr(yousini, "_prepare_user_content", lambda u, a: (u, ["warn-x"]))
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    resp = mock.MagicMock()
    resp.choices = [mock.MagicMock(delta=mock.MagicMock(content="hi", tool_calls=None))]
    resp.usage = None
    yousini.client.chat.completions.create.return_value = iter([resp])
    yousini.chat_turn(agent, "hello")
    assert any("warn-x" in s for s in printed)


def test_chat_turn_exception(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    yousini.client.chat.completions.create.side_effect = Exception("boom")
    monkeypatch.setattr(yousini, "_ui_error", mock.MagicMock())
    yousini.chat_turn(agent, "hello")
    yousini._ui_error.assert_called()


def test_chat_turn_no_choices(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    no_choice = mock.MagicMock()
    no_choice.choices = []
    no_choice.usage = None
    final = mock.MagicMock()
    final.choices = [mock.MagicMock(delta=mock.MagicMock(content="done", tool_calls=None))]
    final.usage = None
    yousini.client.chat.completions.create.return_value = iter([no_choice, final])
    yousini.chat_turn(agent, "hello")


def test_chat_turn_usage_chunk(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    usage_chunk = mock.MagicMock()
    usage_chunk.choices = []
    usage_chunk.usage = mock.MagicMock(prompt_tokens=1, completion_tokens=1)
    final = mock.MagicMock()
    final.choices = [mock.MagicMock(delta=mock.MagicMock(content="done", tool_calls=None))]
    final.usage = None
    yousini.client.chat.completions.create.return_value = iter([usage_chunk, final])
    yousini.chat_turn(agent, "hello")


def test_chat_turn_tool_call(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    fn = _Fn("shell", '{"command":"echo hi"}')
    tc = _TC(0, "t1", fn)
    chunk1 = mock.MagicMock()
    chunk1.choices = [mock.MagicMock(delta=mock.MagicMock(content=None, tool_calls=[tc]))]
    chunk1.usage = None
    final = mock.MagicMock()
    final.choices = [mock.MagicMock(delta=mock.MagicMock(content="done", tool_calls=None))]
    final.usage = None
    yousini.client.chat.completions.create.side_effect = [iter([chunk1]), iter([final])]
    monkeypatch.setattr(yousini, "_exec_tool", mock.MagicMock())
    monkeypatch.setattr(yousini, "_think", lambda s: "T")
    yousini.chat_turn(agent, "hello")
    yousini._exec_tool.assert_called()


def test_chat_turn_typewriter(agent, monkeypatch):
    agent._typewriter = True
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    resp = mock.MagicMock()
    resp.choices = [mock.MagicMock(delta=mock.MagicMock(content="answer", tool_calls=None))]
    resp.usage = None
    yousini.client.chat.completions.create.return_value = iter([resp])
    monkeypatch.setattr(yousini, "_ui_typewriter", mock.MagicMock())
    monkeypatch.setattr(yousini, "_ui_status", mock.MagicMock())
    yousini.chat_turn(agent, "hello")
    yousini._ui_typewriter.assert_called()


def test_chat_turn_answer_panel(agent, monkeypatch):
    agent._typewriter = False
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    resp = mock.MagicMock()
    resp.choices = [mock.MagicMock(delta=mock.MagicMock(content="panel answer", tool_calls=None))]
    resp.usage = None
    yousini.client.chat.completions.create.return_value = iter([resp])
    monkeypatch.setattr(yousini, "_ui_answer_panel", mock.MagicMock())
    monkeypatch.setattr(yousini, "_ui_status", mock.MagicMock())
    yousini.chat_turn(agent, "hello")
    yousini._ui_answer_panel.assert_called()

def test_chat_turn_spinner_isatty(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    resp = mock.MagicMock()
    resp.choices = [mock.MagicMock(delta=mock.MagicMock(content="hi", tool_calls=None))]
    resp.usage = None
    yousini.client.chat.completions.create.return_value = iter([resp])
    yousini.chat_turn(agent, "hello")


# ---------- Group C: run_turn_events ----------

def test_run_turn_events_warn(agent, monkeypatch):
    monkeypatch.setattr(yousini, "_prepare_user_content", lambda u, a: (u, ["w1"]))
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    resp = mock.MagicMock()
    resp.choices = [mock.MagicMock(delta=mock.MagicMock(content="hi", tool_calls=None))]
    resp.usage = None
    yousini.client.chat.completions.create.return_value = iter([resp])
    events = list(yousini.run_turn_events(agent, "hello"))
    assert any(e["type"] == "warn" for e in events)


def test_run_turn_events_retry_create(agent, monkeypatch):
    call_count = [0]

    def side_effect(**kwargs):
        call_count[0] += 1
        if call_count[0] < 2:
            raise ValueError("tool call validation failed")
        resp = mock.MagicMock()
        resp.choices = [mock.MagicMock(delta=mock.MagicMock(content="ok", tool_calls=None))]
        resp.usage = None
        return iter([resp])

    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    yousini.client.chat.completions.create.side_effect = lambda **kw: side_effect(**kw)
    events = list(yousini.run_turn_events(agent, "hello"))
    assert call_count[0] >= 2


def test_run_turn_events_stream_error(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())

    def gen():
        raise RuntimeError("stream broken")
        yield  # make it a generator

    yousini.client.chat.completions.create.return_value = gen()
    events = list(yousini.run_turn_events(agent, "hello"))
    assert any(e["type"] == "error" for e in events)

def test_run_turn_events_blocked_tool(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    fn = _Fn("shell", '{"command":"rm -rf /"}')
    tc = _TC(0, "t1", fn)
    chunk = mock.MagicMock()
    chunk.choices = [mock.MagicMock(delta=mock.MagicMock(content=None, tool_calls=[tc]))]
    chunk.usage = None
    final = mock.MagicMock()
    final.choices = [mock.MagicMock(delta=mock.MagicMock(content="done", tool_calls=None))]
    final.usage = None
    yousini.client.chat.completions.create.return_value = iter([chunk, final])
    agent.hooks.run_pre = mock.MagicMock(return_value=(False, "policy"))
    events = list(yousini.run_turn_events(agent, "hello"))
    assert any(e.get("blocked") for e in events)


def test_run_turn_events_allowed_tool(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    fn = _Fn("shell", '{"command":"echo x"}')
    tc = _TC(0, "t1", fn)
    chunk = mock.MagicMock()
    chunk.choices = [mock.MagicMock(delta=mock.MagicMock(content=None, tool_calls=[tc]))]
    chunk.usage = None
    final = mock.MagicMock()
    final.choices = [mock.MagicMock(delta=mock.MagicMock(content="done", tool_calls=None))]
    final.usage = None
    yousini.client.chat.completions.create.side_effect = [iter([chunk]), iter([final])]
    agent.hooks.run_pre = mock.MagicMock(return_value=(True, ""))
    agent.hooks.run_post = mock.MagicMock()
    monkeypatch.setattr(yousini, "_record_usage_tool", mock.MagicMock())
    orig = yousini.IMPL.get("shell")
    yousini.IMPL["shell"] = lambda args, ag: "ok"
    try:
        events = list(yousini.run_turn_events(agent, "hello"))
    finally:
        yousini.IMPL["shell"] = orig
    assert any(e["type"] == "tool_result" for e in events)
    yousini.IMPL["shell"] = orig


# ---------- Group D: _setup_readline ----------

@pytest.mark.skipif(sys.platform == "win32",
                    reason="readline ไมมบน Windows")
def test_setup_readline(monkeypatch):
    import readline as rl_mod
    monkeypatch.setattr(yousini, "readline", rl_mod)
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    yousini._setup_readline()


def test_setup_readline_none(monkeypatch):
    monkeypatch.setattr(yousini, "readline", None)
    yousini._setup_readline()


# ---------- Group E: completer + hints ----------

def test_repl_completer():
    result = yousini._repl_completer("/h", 0)
    assert result is None or result.startswith("/")


def test_repl_completer_empty_text():
    result = yousini._repl_completer("", 0)
    assert result is None or result.startswith("/")


def test_repl_completer_hints(monkeypatch):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    yousini._repl_completer_hints("", ["/help", "/clear"], 2)


# ---------- Group F: _print_history / _print_skills / _print_hooks ----------

def test_print_history_roles(agent):
    agent.messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "content": "tool result"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "msg"},
    ]
    yousini._print_history(agent)


def test_print_skills_empty(agent, monkeypatch):
    agent.skills = []
    printed = []
    monkeypatch.setattr(yousini.console, "print", lambda *a, **k: printed.append(str(a)))
    yousini._print_skills(agent)
    assert any("ไม่มีสกิล" in s for s in printed)


def test_print_skills_with_items(agent):
    agent.skills = [("skill1", None, "project"), ("skill2", None, "global")]
    yousini._print_skills(agent)


def test_print_hooks_no_dir(agent, monkeypatch):
    agent.hooks = mock.MagicMock()
    agent.hooks.dir = None
    printed = []
    monkeypatch.setattr(yousini.console, "print", lambda *a, **k: printed.append(str(a)))
    yousini._print_hooks(agent)
    assert any("ไม่พบโฟลเดอร์ hooks (วาง pre_tool.sh/post_tool.sh ใน ./.yousini/hooks หรือ ~/.yousini/hooks)" in s for s in printed)


def test_print_hooks_with_dir(agent, tmp_path):
    agent.hooks = mock.MagicMock()
    agent.hooks.dir = str(tmp_path)
    agent.hooks._resolve_script.return_value = None
    yousini._print_hooks(agent)


# ---------- Group G: _apply_provider_config ----------

def test_apply_provider_config_default_key(monkeypatch):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_FallbackClient", mock.MagicMock())
    cfg = {
        "default_provider": "groq",
        "providers": {"groq": {"api_key": "mykey",
                               "base_url": "https://api.groq.com/openai/v1",
                               "model": "llama-3.3-70b-versatile"}},
    }
    assert yousini._apply_provider_config(cfg) is True


def test_apply_provider_config_custom(monkeypatch):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_FallbackClient", mock.MagicMock())
    cfg = {
        "default_provider": "custom",
        "providers": {"<custom>": {"api_key": "mykey",
                                   "base_url": "https://custom.api/v1",
                                   "model": "my-model"}},
    }
    assert yousini._apply_provider_config(cfg) is True


# ---------- Group H: permission_cmd ----------

def test_permission_cmd_no_parts(monkeypatch):
    monkeypatch.setattr(yousini, "load_config", lambda: {"allow_shell_prefix": []})
    assert "ใช้:" in yousini.permission_cmd("")


def test_permission_cmd_add_new(monkeypatch):  # noqa: F811
    monkeypatch.setattr(yousini, "load_config", lambda: {"allow_shell_prefix": []})
    monkeypatch.setattr(yousini, "save_config", lambda c: None)
    assert "เพิ่ม" in yousini.permission_cmd("add git")


def test_permission_cmd_add_duplicate(monkeypatch):
    monkeypatch.setattr(yousini, "load_config", lambda: {"allow_shell_prefix": ["git"]})
    monkeypatch.setattr(yousini, "save_config", lambda c: None)
    assert "มีอยู่แล้ว" in yousini.permission_cmd("add git")


def test_permission_cmd_list_empty(monkeypatch):
    monkeypatch.setattr(yousini, "load_config", lambda: {"allow_shell_prefix": []})
    assert "allow-list ว่าง" in yousini.permission_cmd("list")


def test_permission_cmd_list_nonempty(monkeypatch):
    monkeypatch.setattr(yousini, "load_config", lambda: {"allow_shell_prefix": ["git"]})
    assert "git" in yousini.permission_cmd("list")


def test_permission_cmd_remove_present(monkeypatch):
    monkeypatch.setattr(yousini, "load_config", lambda: {"allow_shell_prefix": ["git"]})
    monkeypatch.setattr(yousini, "save_config", lambda c: None)
    assert "ลบ" in yousini.permission_cmd("remove git")


def test_permission_cmd_remove_missing(monkeypatch):
    monkeypatch.setattr(yousini, "load_config", lambda: {"allow_shell_prefix": []})
    monkeypatch.setattr(yousini, "save_config", lambda c: None)
    assert "ไม่มีใน allow-list" in yousini.permission_cmd("remove nonexistent")


def test_permission_cmd_clear(monkeypatch):
    monkeypatch.setattr(yousini, "load_config", lambda: {"allow_shell_prefix": ["git"]})
    monkeypatch.setattr(yousini, "save_config", lambda c: None)
    assert "ล้าง" in yousini.permission_cmd("clear")


def test_permission_cmd_unknown(monkeypatch):
    monkeypatch.setattr(yousini, "load_config", lambda: {"allow_shell_prefix": []})
    assert "ใช้:" in yousini.permission_cmd("unknown")


# ---------- Group I: login_mode ----------

def test_login_mode_empty_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr("builtins.input", lambda p="": "")
    yousini.login_mode()


def test_login_mode_invalid_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    it = iter(["invalid_provider"])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.login_mode()


def test_login_mode_empty_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    it = iter(["groq", ""])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.login_mode()


def test_login_mode_groq_model_select(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_apply_provider_config", mock.MagicMock())
    it = iter(["groq", "myapikey", "1"])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.login_mode()


def test_login_mode_groq_model_default(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_apply_provider_config", mock.MagicMock())
    it = iter(["groq", "myapikey", "invalid"])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.login_mode()


def test_login_mode_groq_custom_0_model(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_apply_provider_config", mock.MagicMock())
    it = iter(["groq", "myapikey", "0", "custom-model"])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.login_mode()


def test_login_mode_groq_custom_0_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    it = iter(["groq", "myapikey", "0", ""])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.login_mode()


def test_login_mode_custom_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_apply_provider_config", mock.MagicMock())
    it = iter(["custom", "myapikey", "https://custom.api/v1", "my-model"])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.login_mode()


def test_login_mode_custom_missing_url(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    it = iter(["custom", "myapikey", "", "my-model"])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.login_mode()


# ---------- Group J: plan_mode ----------

def test_plan_mode_empty_goal(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr("builtins.input", lambda p="": "")
    yousini.plan_mode()


def test_plan_mode_create_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    yousini.client.chat.completions.create.side_effect = Exception("API error")
    it = iter(["build a feature"])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.plan_mode()


def test_plan_mode_cancel(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    resp = mock.MagicMock()
    resp.choices = [mock.MagicMock(message=mock.MagicMock(
        content='[{"id":1,"action":"shell","detail":"echo hi"}]'))]
    yousini.client.chat.completions.create.return_value = resp
    it = iter(["build a feature", "n"])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.plan_mode()


def _plan_run(action, detail, extra_step=None, mock_chat=True):
    """helper: run plan_mode through execution of one step action"""
    step = {"id": 1, "action": action, "detail": detail}
    if extra_step:
        step.update(extra_step)
    content = json.dumps([step], ensure_ascii=False)
    monkeypatch = mock.MagicMock()

    def setup(tmp_path, monkeypatch_):
        monkeypatch_.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
        monkeypatch_.setattr(yousini, "console", mock.MagicMock())
        monkeypatch_.setattr(yousini, "client", mock.MagicMock())
        resp = mock.MagicMock()
        resp.choices = [mock.MagicMock(message=mock.MagicMock(content=content))]
        yousini.client.chat.completions.create.return_value = resp
        fake_agent = mock.MagicMock()
        fake_agent.messages = []
        fake_agent.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        fake_agent.shell.return_value = "ok"
        fake_agent.read_file.return_value = "content"
        monkeypatch_.setattr(yousini, "Agent", mock.MagicMock(return_value=fake_agent))
        if mock_chat:
            monkeypatch_.setattr(yousini, "chat_turn", mock.MagicMock())
        it = iter(["build a feature", "y"])
        monkeypatch_.setattr("builtins.input", lambda p="": next(it))
        return tmp_path, monkeypatch_
    return setup, step


def test_plan_mode_execute_shell(tmp_path, monkeypatch):
    s, _ = _plan_run("shell", "echo hi")
    tmp_path, monkeypatch = s(tmp_path, monkeypatch)
    yousini.plan_mode()
    agent_obj = yousini.Agent.return_value
    agent_obj.shell.assert_called()


def test_plan_mode_execute_run_test(tmp_path, monkeypatch):
    s, _ = _plan_run("run_test", "tests/")
    tmp_path, monkeypatch = s(tmp_path, monkeypatch)
    yousini.plan_mode()
    yousini.Agent.return_value.shell.assert_called()


def test_plan_mode_execute_read(tmp_path, monkeypatch):
    s, _ = _plan_run("read", "README.md")
    tmp_path, monkeypatch = s(tmp_path, monkeypatch)
    yousini.plan_mode()
    yousini.Agent.return_value.read_file.assert_called()


def test_plan_mode_execute_edit_file_with_path(tmp_path, monkeypatch):
    s, _ = _plan_run("edit_file", "new content", extra_step={"path": "f.py", "content": "new"})
    tmp_path, monkeypatch = s(tmp_path, monkeypatch)
    yousini.plan_mode()
    yousini.Agent.return_value.write_file.assert_called()


def test_plan_mode_execute_edit_file_no_path(tmp_path, monkeypatch):
    s, _ = _plan_run("edit_file", "new content",
                     extra_step={"old_string": "old", "new_string": "new"})
    tmp_path, monkeypatch = s(tmp_path, monkeypatch)
    yousini.plan_mode()
    yousini.Agent.return_value.edit_file.assert_called()

def test_plan_mode_execute_general(tmp_path, monkeypatch):
    s, _ = _plan_run("general", "do something")
    tmp_path, monkeypatch = s(tmp_path, monkeypatch)
    yousini.plan_mode()
    yousini.chat_turn.assert_called()


# ---------- Group O: _run_subagent_loop ----------

def test_subagent_loop_create_exception(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    yousini.client.chat.completions.create.side_effect = Exception("API down")
    result = yousini._run_subagent_loop(agent, "do something")
    assert "เอเจนต์ย่อย error" in result


def test_subagent_loop_no_tool_calls(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    msg = mock.MagicMock()
    msg.tool_calls = None
    msg.content = "done 42"
    resp = mock.MagicMock()
    resp.choices = [mock.MagicMock(message=msg)]
    yousini.client.chat.completions.create.return_value = resp
    assert yousini._run_subagent_loop(agent, "do something") == "done 42"


def test_subagent_loop_no_content(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    msg = mock.MagicMock()
    msg.tool_calls = None
    msg.content = None
    resp = mock.MagicMock()
    resp.choices = [mock.MagicMock(message=msg)]
    yousini.client.chat.completions.create.return_value = resp
    assert yousini._run_subagent_loop(agent, "do something") == "(ไม่มีคำตอบ)"


def test_subagent_loop_bad_json_args(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    fn = _Fn("shell", "not-valid-json@@@")
    tc = _TC(0, "t1", fn)
    msg1 = mock.MagicMock()
    msg1.tool_calls = [tc]
    msg1.content = None
    msg2 = mock.MagicMock()
    msg2.tool_calls = None
    msg2.content = "done"
    resp1 = mock.MagicMock()
    resp1.choices = [mock.MagicMock(message=msg1)]
    resp2 = mock.MagicMock()
    resp2.choices = [mock.MagicMock(message=msg2)]
    yousini.client.chat.completions.create.side_effect = [resp1, resp2]
    assert yousini._run_subagent_loop(agent, "do something") == "done"


def test_subagent_loop_spawn_subagent(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    fn = _Fn("spawn_subagent", '{"task":"subtask"}')
    tc = _TC(0, "t1", fn)
    msg1 = mock.MagicMock()
    msg1.tool_calls = [tc]
    msg1.content = None
    msg2 = mock.MagicMock()
    msg2.tool_calls = None
    msg2.content = "done"
    resp1 = mock.MagicMock()
    resp1.choices = [mock.MagicMock(message=msg1)]
    resp2 = mock.MagicMock()
    resp2.choices = [mock.MagicMock(message=msg2)]
    yousini.client.chat.completions.create.side_effect = [resp1, resp2]
    assert yousini._run_subagent_loop(agent, "do something") == "done"


def test_subagent_loop_unknown_tool(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    fn = _Fn("unknown_tool_xyz", "{}")
    tc = _TC(0, "t1", fn)
    msg1 = mock.MagicMock()
    msg1.tool_calls = [tc]
    msg1.content = None
    msg2 = mock.MagicMock()
    msg2.tool_calls = None
    msg2.content = "done"
    resp1 = mock.MagicMock()
    resp1.choices = [mock.MagicMock(message=msg1)]
    resp2 = mock.MagicMock()
    resp2.choices = [mock.MagicMock(message=msg2)]
    yousini.client.chat.completions.create.side_effect = [resp1, resp2]
    assert yousini._run_subagent_loop(agent, "do something") == "done"


def test_subagent_loop_impl_exception(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    fn = _Fn("shell", '{"command":"echo hi"}')
    tc = _TC(0, "t1", fn)
    msg1 = mock.MagicMock()
    msg1.tool_calls = [tc]
    msg1.content = None
    msg2 = mock.MagicMock()
    msg2.tool_calls = None
    msg2.content = "done"
    resp1 = mock.MagicMock()
    resp1.choices = [mock.MagicMock(message=msg1)]
    resp2 = mock.MagicMock()
    resp2.choices = [mock.MagicMock(message=msg2)]
    yousini.client.chat.completions.create.side_effect = [resp1, resp2]
    orig = yousini.IMPL.get("shell")
    yousini.IMPL["shell"] = lambda args, ag: (_ for _ in ()).throw(Exception("shell failed"))
    try:
        assert yousini._run_subagent_loop(agent, "do something") == "done"
    finally:
        if orig:
            yousini.IMPL["shell"] = orig


def test_subagent_loop_exhausted(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    fn = _Fn("shell", '{"command":"echo hi"}')
    tc = _TC(0, "t1", fn)
    msg = mock.MagicMock()
    msg.tool_calls = [tc]
    msg.content = None
    resp = mock.MagicMock()
    resp.choices = [mock.MagicMock(message=msg)]
    yousini.client.chat.completions.create.return_value = resp
    orig = yousini.IMPL.get("shell")
    yousini.IMPL["shell"] = lambda args, ag: "ok"
    try:
        result = yousini._run_subagent_loop(agent, "do something", max_iter=2)
    finally:
        if orig:
            yousini.IMPL["shell"] = orig
    assert "หมดรอบจำกัด" in result


# ---------- Group P: _fallback_turn ----------

def test_fallback_turn_success(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    resp = mock.MagicMock()
    resp.choices = [mock.MagicMock(message=mock.MagicMock(content="fallback answer"))]
    yousini.client.chat.completions.create.return_value = resp
    monkeypatch.setattr(yousini, "_ui_status", mock.MagicMock(), raising=False)
    yousini._fallback_turn(agent, Exception("original"))
    assert any("fallback answer" in m.get("content", "") for m in agent.messages)


def test_fallback_turn_exception(agent, monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    yousini.client.chat.completions.create.side_effect = Exception("fallback error")
    printed = []
    monkeypatch.setattr(yousini.console, "print", lambda *a, **k: printed.append(str(a)))
    yousini._fallback_turn(agent, Exception("original"))
    assert any("Error" in s for s in printed)
