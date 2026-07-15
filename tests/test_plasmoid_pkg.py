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


def test_full_representation_lists_history_and_undo():
    full = (PKG / "contents" / "ui" / "FullRepresentation.qml").read_text()
    assert "historyModel" in full          # bound to the shared model
    assert "undoEntry" in full             # Undo button wired to the root
    assert "savedTotal" in full            # header shows the running total


def test_config_page_is_registered_and_calls_cli():
    cfgqml = (PKG / "contents" / "config" / "config.qml").read_text()
    assert "ConfigGeneral.qml" in cfgqml
    form = (PKG / "contents" / "ui" / "ConfigGeneral.qml").read_text()
    assert "config get --json" in form   # loads current values
    assert "config set" in form          # persists on save
    for field in ("png_lossy", "pngquant_quality", "jpeg_max_quality",
                  "min_bytes_saved", "concurrency", "clipboard_watch"):
        assert field in form


def test_main_qml_routes_web_urls_to_optimize_url():
    main = (PKG / "contents" / "ui" / "main.qml").read_text()
    assert "optimizeUrls" in main            # new remote-URL handler
    assert "optimize-url" in main            # invokes the new CLI verb
    assert "https://" in main                # classifies remote drops
    assert "drop.hasText" in main            # accepts text-only browser drags
