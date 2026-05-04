from appium_cli.core.snapshot import compress_xml, generate_snapshot


XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" clickable="false" enabled="true" bounds="[0,0][100,100]">
    <node text="Login" resource-id="com.example:id/login" class="android.widget.Button" clickable="true" bounds="[10,10][90,50]" />
    <node content-desc="Search" class="android.view.View" clickable="true" bounds="[10,60][90,90]" />
  </node>
</hierarchy>
"""


def test_generate_snapshot_creates_refs_and_text() -> None:
    snapshot, ref_map = generate_snapshot(XML)

    assert snapshot.screen_id
    assert "e1" in ref_map
    text = snapshot.to_text()
    assert '[ref:e1] button "Login"' in text
    assert '[ref:e2] button "Search" (content-desc)' in text


def test_compress_xml_removes_noise_preserves_useful_attrs() -> None:
    compressed = compress_xml(XML)

    assert "index=" not in compressed
    assert 'enabled="true"' not in compressed
    assert "com.example:id/login" in compressed
