from orchestrai import OrchestrAI
from orchestrai.fixups.base import FixupStage


class PersistenceRegistryFixup:
    def __init__(self):
        self.calls: list[FixupStage] = []

    def apply(self, stage: FixupStage, app, **context):  # pragma: no cover - exercised via test
        self.calls.append(stage)


def test_class_fixup_specs_are_instantiated():
    app = OrchestrAI(fixups=[PersistenceRegistryFixup])

    app.configure()

    assert isinstance(app.fixups[0], PersistenceRegistryFixup)
    assert app.fixups[0].calls[0] == FixupStage.CONFIGURE_PRE

    app.apply_fixups(FixupStage.CONFIGURE_PRE)

    assert app.fixups[0].calls[-1] == FixupStage.CONFIGURE_PRE
