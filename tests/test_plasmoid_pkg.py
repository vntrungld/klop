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


def test_full_representation_has_progress_and_row_actions():
    full = (PKG / "contents" / "ui" / "FullRepresentation.qml").read_text()
    assert "pendingCount" in full          # indeterminate progress while jobs run
    assert "ProgressBar" in full
    assert "openImage" in full             # open image / folder / copy buttons
    assert "openFolder" in full
    assert "copyImage" in full


def test_main_qml_maps_path_and_tracks_pending():
    main = (PKG / "contents" / "ui" / "main.qml").read_text()
    assert "pendingCount" in main          # in-flight job counter
    assert "path: r.path" in main          # file path surfaced to the model
    assert '" copy "' in main              # copy button invokes the new CLI verb


def test_config_page_is_registered_and_calls_cli():
    cfgqml = (PKG / "contents" / "config" / "config.qml").read_text()
    assert "ConfigGeneral.qml" in cfgqml
    form = (PKG / "contents" / "ui" / "ConfigGeneral.qml").read_text()
    assert "config get --json" in form   # loads current values
    assert "config set" in form          # persists on save
    for field in ("png_lossy", "pngquant_quality", "jpeg_max_quality",
                  "min_bytes_saved", "concurrency", "clipboard_watch"):
        assert field in form
    assert "Kirigami.Heading" in form    # big left-aligned page title, KDE style
    assert "Image optimization" in form


def test_main_qml_routes_web_urls_to_optimize_url():
    main = (PKG / "contents" / "ui" / "main.qml").read_text()
    assert "optimizeUrls" in main            # new remote-URL handler
    assert "optimize-url" in main            # invokes the new CLI verb
    assert "https://" in main                # classifies remote drops
    assert "drop.hasText" in main            # accepts text-only browser drags


def _run_drop_js(expr: str):
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    src = (PKG / "contents" / "code" / "drop.js").read_text()
    src = src.replace(".pragma library", "")
    out = subprocess.run(
        [node, "-e", f"{src}\nconsole.log(JSON.stringify({expr}));"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def test_drop_js_extracts_img_src_from_linked_image_html():
    # Facebook wraps feed images in a link to the photo page; the image URL is
    # only in the drag's text/html, entity-escaped.
    html = (
        '<a href="https://www.facebook.com/photo/?fbid=1">'
        '<img alt="x" src="https://scontent.xx.fbcdn.net/v/pic.jpg?oh=a&amp;oe=b"></a>'
    )
    assert _run_drop_js(f"imageSrcs({json.dumps(html)})") == [
        "https://scontent.xx.fbcdn.net/v/pic.jpg?oh=a&oe=b"
    ]


def test_drop_js_ignores_non_http_img_src():
    html = "<img src='data:image/png;base64,AAA'><img src=\"blob:https://x/1\">"
    assert _run_drop_js(f"imageSrcs({json.dumps(html)})") == []
    assert _run_drop_js("imageSrcs('')") == []


def test_main_qml_tries_html_img_src_before_link_url():
    main = (PKG / "contents" / "ui" / "main.qml").read_text()
    assert 'import "../code/drop.js" as Drop' in main
    assert "drop.html" in main
    assert "Drop.imageSrcs" in main
