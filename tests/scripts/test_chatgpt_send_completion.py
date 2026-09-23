import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

SCRIPT_DIR = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "chatgpt-mcp-dev"
    / "scripts"
)
SCRIPT = SCRIPT_DIR / "chatgpt-send"


def _module():
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        loader = SourceFileLoader("chatgpt_send_script", str(SCRIPT))
        spec = importlib.util.spec_from_loader("chatgpt_send_script", loader)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPT_DIR))


def test_conversation_id_supports_project_chat_url():
    module = _module()

    assert (
        module._conversation_id(
            "https://chatgpt.com/g/g-p-abc/project-name/c/"
            "12345678-1234-1234-1234-123456789abc"
        )
        == "12345678-1234-1234-1234-123456789abc"
    )


def test_backend_final_requires_final_assistant_completion():
    module = _module()
    complete = {
        "current_node": "a",
        "mapping": {
            "a": {
                "message": {
                    "author": {"role": "assistant"},
                    "status": "finished_successfully",
                    "end_turn": True,
                    "metadata": {"is_complete": True},
                    "content": {"parts": ["DONE"]},
                }
            }
        },
    }

    assert module._final_from_conversation(complete) == (True, "DONE")

    incomplete = {
        "current_node": "a",
        "mapping": {
            "a": {
                "message": {
                    "author": {"role": "assistant"},
                    "status": "in_progress",
                    "end_turn": False,
                    "metadata": {},
                    "content": {"parts": ["partial"]},
                }
            }
        },
    }
    assert module._final_from_conversation(incomplete) == (False, "partial")


def test_backend_final_rejects_reasoning_recap_current_node():
    module = _module()
    data = {
        "current_node": "r",
        "mapping": {
            "r": {
                "message": {
                    "author": {"role": "assistant"},
                    "status": "finished_successfully",
                    "end_turn": False,
                    "metadata": {},
                    "content": {
                        "content_type": "reasoning_recap",
                        "content": "Worked for a few seconds",
                    },
                }
            }
        },
    }

    assert module._final_from_conversation(data) == (False, "")
