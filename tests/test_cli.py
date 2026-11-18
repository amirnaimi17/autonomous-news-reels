"""CLI and workflow contract."""

from app.cli import main
from app.orchestrator.workflow import WORKFLOW_STEPS, WorkflowOrchestrator


def test_workflow_order_is_fixed() -> None:
    assert [step.value for step in WORKFLOW_STEPS] == [
        "research",
        "select",
        "reserve_slot",
        "reserve_story",
        "write_script",
        "generate_images",
        "generate_voice",
        "render_video",
        "validate_video",
        "complete",
        "notify",
    ]
    assert WorkflowOrchestrator().steps == WORKFLOW_STEPS
    assert not hasattr(WorkflowOrchestrator, "run")


def test_init_and_status_do_not_print_secrets(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "reels.db"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret-token")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    assert main(["init-db"]) == 0
    assert main(["status"]) == 0
    output = capsys.readouterr().out
    assert "schema: 001" in output
    assert "Europe/Berlin" in output
    assert "super-secret-token" not in output
    assert "sk-secret" not in output
    assert (tmp_path / "media" / "videos").is_dir()
    assert main(["init-db"]) == 0


def test_status_without_a_database_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "missing.db"))
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    assert main(["status"]) == 1


def test_instagram_flag_refuses_to_start(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "reels.db"))
    monkeypatch.setenv("INSTAGRAM_PUBLISH_ENABLED", "true")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    assert main(["init-db"]) == 1
