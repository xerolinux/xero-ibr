import pytest

from ibr.core.catalog import CATALOG, lookup, resolve_finish


def test_iphone_16_pro():
    spec = lookup("iPhone17,1")
    assert spec.name == "iPhone 16 Pro"
    assert spec.kind == "iphone"
    assert spec.cutout == "island"
    assert spec.action_button and spec.camera_control


def test_iphone_15_has_island_without_action_button():
    spec = lookup("iPhone15,4")
    assert spec.name == "iPhone 15"
    assert spec.cutout == "island"
    assert not spec.action_button


def test_iphone_13_mini_notch():
    spec = lookup("iPhone14,4")
    assert spec.name == "iPhone 13 mini"
    assert spec.cutout == "notch"


def test_iphone_se_home_button():
    spec = lookup("iPhone14,6")
    assert spec.name == "iPhone SE (3rd generation)"
    assert spec.cutout == "home"


def test_ipad_pro_m4_landscape_camera():
    spec = lookup("iPad16,5")
    assert spec.name == "iPad Pro 13-inch (M4)"
    assert spec.kind == "ipad"
    assert spec.cutout == "ipad"
    assert spec.landscape_camera


def test_ipad_home_button():
    spec = lookup("iPad12,1")
    assert spec.name == "iPad (9th generation)"
    assert spec.cutout == "ipad_home"


@pytest.mark.parametrize(
    "product_type, device_class, name, cutout",
    [
        ("iPhone99,1", "iPhone", "iPhone", "island"),
        ("iPad99,1", "iPad", "iPad", "ipad"),
        ("Weird1,1", "", "Apple device", "island"),
    ],
)
def test_unknown_falls_back_by_class(product_type, device_class, name, cutout):
    spec = lookup(product_type, device_class)
    assert spec.name == name
    assert spec.cutout == cutout


def test_every_spec_is_sane():
    for product_type, spec in CATALOG.items():
        assert spec.width_mm < spec.height_mm, product_type
        assert spec.finish.startswith("#") and len(spec.finish) == 7, product_type
        assert spec.cutout in {"home", "notch", "island", "ipad", "ipad_home"}, product_type


def test_resolve_finish_prefers_hex_from_device():
    spec = lookup("iPhone10,1")
    assert resolve_finish(spec, "#e1e4e3") == "#e1e4e3"


def test_resolve_finish_ignores_index_codes():
    spec = lookup("iPhone17,1")
    assert resolve_finish(spec, "2") == spec.finish
    assert resolve_finish(spec, None) == spec.finish


@pytest.mark.parametrize("product_type, name", [
    ("iPad6,11", "iPad (5th generation)"),
    ("iPad7,5", "iPad (6th generation)"),
    ("iPad5,3", "iPad Air 2"),
    ("iPad5,1", "iPad mini 4"),
    ("iPad6,3", "iPad Pro 9.7-inch"),
    ("iPad7,3", "iPad Pro 10.5-inch"),
    ("iPad6,7", "iPad Pro 12.9-inch (1st generation)"),
    ("iPad7,1", "iPad Pro 12.9-inch (2nd generation)"),
])
def test_ios15_capable_older_ipads(product_type, name):
    spec = lookup(product_type)
    assert spec.name == name
    assert spec.cutout == "ipad_home"



@pytest.mark.parametrize("product_type, camera", [
    ("iPhone14,6", "single"),
    ("iPhone10,2", "dual_horizontal"),
    ("iPhone10,3", "dual_pill"),
    ("iPhone12,1", "dual_square_vertical"),
    ("iPhone15,4", "dual_square_diagonal"),
    ("iPhone17,3", "dual_pill"),
    ("iPhone17,1", "triple"),
    ("iPhone18,1", "plateau_pro"),
    ("iPhone18,4", "plateau_air"),
    ("iPad16,5", "ipad_pro"),
    ("iPad13,18", "single"),
])
def test_camera_layouts(product_type, camera):
    assert lookup(product_type).camera == camera


def test_every_spec_has_known_camera():
    allowed = {"single", "dual_horizontal", "dual_pill", "dual_square_vertical", "dual_square_diagonal",
               "triple", "plateau_pro", "plateau_air", "ipad_pro"}
    for product_type, spec in CATALOG.items():
        assert spec.camera in allowed, product_type
