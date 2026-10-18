from types import SimpleNamespace
from typing import Any

from pipeline import seed


class FakeQdrant:
    def __init__(self, aliases: list[str]) -> None:
        self.aliases = aliases

    def get_aliases(self) -> Any:
        return SimpleNamespace(aliases=[SimpleNamespace(alias_name=a) for a in self.aliases])


def test_already_seeded_checks_scene_alias() -> None:
    assert seed.already_seeded(FakeQdrant(["scenes"]), "scenes")  # type: ignore[arg-type]
    # movies 컬렉션만 있거나 다른 alias면 s08이 끝나지 않은 것이다
    assert not seed.already_seeded(FakeQdrant(["other"]), "scenes")  # type: ignore[arg-type]
    assert not seed.already_seeded(FakeQdrant([]), "scenes")  # type: ignore[arg-type]


def test_commands_migrate_first_then_steps_with_limit() -> None:
    cmds = seed.commands(5)
    assert cmds[0][1:] == ["-m", "alembic", "upgrade", "head"]
    modules = [c[2] for c in cmds[1:]]
    assert modules[0] == "pipeline.s01_collect_meta" and modules[-1] == "pipeline.s08_upload"
    # 저장소의 사용자 사전을 backend와 함께 써야 하므로 다시 만들지 않는다
    assert "pipeline.build_user_dict" not in modules
    assert all(c[-2:] == ["--limit", "5"] for c in cmds[1:])
