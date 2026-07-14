import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "clop_kde" / "plasmoid_pkg"


def test_metadata_has_correct_plugin_identity():
    meta = json.loads((PKG / "metadata.json").read_text())
    assert meta["KPlugin"]["Id"] == "org.trungld.klop"
    assert meta["KPlugin"]["Name"] == "Klop"
    assert meta["KPackageStructure"] == "Plasma/Applet"


def test_main_qml_exists_and_uses_backend_constant():
    main = (PKG / "contents" / "ui" / "main.qml").read_text()
    assert "PlasmoidItem" in main
    assert "Backend.CLOP_BIN" in main  # invocations use the baked absolute path
