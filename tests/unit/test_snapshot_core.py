from appium_cli.core.snapshot import compress_xml, generate_snapshot
from appium_cli.core.snapshot_generator import SnapshotGenerator


XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" clickable="false" enabled="true" bounds="[0,0][100,100]">
    <node text="Login" resource-id="com.example:id/login" class="android.widget.Button" clickable="true" bounds="[10,10][90,50]" />
    <node content-desc="Search" class="android.view.View" clickable="true" bounds="[10,60][90,90]" />
  </node>
</hierarchy>
"""


def test_legacy_generate_snapshot_creates_refs_and_text() -> None:
    """Legacy generate_snapshot still works with e1/e2 refs."""
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


# ============================================================
# SnapshotGenerator tests
# ============================================================


def test_generator_creates_resource_id_based_refs() -> None:
    """SnapshotGenerator creates stable resource-id based refs."""
    gen = SnapshotGenerator(screen_width=100, screen_height=100)
    snapshot, ref_map = gen.generate(XML)

    assert snapshot.screen_id
    # resource-id "com.example:id/login" -> ref "login"
    assert "login" in ref_map
    text = snapshot.to_text()
    assert '[ref:login] button "Login"' in text


def test_generator_content_desc_ref() -> None:
    """content-desc derived ref for elements without resource-id."""
    gen = SnapshotGenerator(screen_width=100, screen_height=100)
    snapshot, ref_map = gen.generate(XML)

    # content-desc "Search" -> ref "search"
    assert "search" in ref_map
    text = snapshot.to_text()
    assert '[ref:search] button "Search" (content-desc)' in text


DUPLICATE_TAB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
    <node class="androidx.recyclerview.widget.RecyclerView"
          resource-id="com.example:id/rv_tab_menu"
          scrollable="true" bounds="[0,2200][1080,2340]">
      <node class="android.widget.LinearLayout" clickable="true"
            resource-id="com.example:id/tabBackground" bounds="[0,2200][270,2340]">
        <node class="android.widget.TextView" text="Home" bounds="[50,2220][220,2300]" />
      </node>
      <node class="android.widget.LinearLayout" clickable="true"
            resource-id="com.example:id/tabBackground" bounds="[270,2200][540,2340]">
        <node class="android.widget.TextView" text="Search" bounds="[320,2220][490,2300]" />
      </node>
      <node class="android.widget.LinearLayout" clickable="true"
            resource-id="com.example:id/tabBackground" bounds="[540,2200][810,2340]">
        <node class="android.widget.TextView" text="Library" bounds="[590,2220][760,2300]" />
      </node>
      <node class="android.widget.LinearLayout" clickable="true"
            resource-id="com.example:id/tabBackground" bounds="[810,2200][1080,2340]">
        <node class="android.widget.TextView" text="Apps" bounds="[860,2220][1030,2300]" />
      </node>
    </node>
  </node>
</hierarchy>
"""


def test_generator_duplicate_resource_id_unique_refs() -> None:
    """Duplicate resource-ids get _2, _3, _4 suffixes."""
    gen = SnapshotGenerator(screen_width=1080, screen_height=2340)
    snapshot, ref_map = gen.generate(DUPLICATE_TAB_XML)

    # First tabBackground -> "tabbackground"
    # Second -> "tabbackground_2", etc.
    assert "tabbackground" in ref_map
    assert "tabbackground_2" in ref_map
    assert "tabbackground_3" in ref_map
    assert "tabbackground_4" in ref_map

    text = snapshot.to_text()
    assert "[ref:tabbackground]" in text
    assert "[ref:tabbackground_4]" in text


def test_generator_ref_entry_has_multiple_strategies() -> None:
    """RefEntry contains id, xpath, and coordinates strategies."""
    gen = SnapshotGenerator(screen_width=1080, screen_height=2340)
    _, ref_map = gen.generate(DUPLICATE_TAB_XML)

    entry = ref_map["tabbackground"]
    strategies = [s.by for s in entry.strategies]
    assert "id" in strategies
    assert "coordinates" in strategies
    assert entry.expected_bounds == (0, 2200, 270, 2340)


def test_generator_ref_entry_coordinates_strategy() -> None:
    """Coordinates strategy has correct center values."""
    gen = SnapshotGenerator(screen_width=1080, screen_height=2340)
    _, ref_map = gen.generate(DUPLICATE_TAB_XML)

    entry = ref_map["tabbackground_4"]
    coord_strategy = next(s for s in entry.strategies if s.by == "coordinates")
    assert coord_strategy.value == "945,2270"  # center of [810,2200][1080,2340]


def test_generator_text_elements_get_refs() -> None:
    """Text elements (non-clickable TextViews) also get refs."""
    gen = SnapshotGenerator(screen_width=1080, screen_height=2340)
    snapshot, ref_map = gen.generate(DUPLICATE_TAB_XML)

    # "Home" text inside tabBackground gets a ref like "txt_home"
    text_refs = [r for r in ref_map if "home" in r.lower()]
    assert len(text_refs) >= 1


def test_generator_container_detection() -> None:
    """RecyclerView with tab in resource-id is detected as a list container."""
    gen = SnapshotGenerator(screen_width=1080, screen_height=2340)
    snapshot, _ = gen.generate(DUPLICATE_TAB_XML)

    list_containers = [c for c in snapshot.containers if c.region == "list"]
    assert len(list_containers) >= 1
    # rv_tab_menu should be a container ref
    assert any(c.ref == "rv_tab_menu" for c in snapshot.containers)
