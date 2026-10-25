import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    name: str
    kind: str
    cutout: str
    camera: str
    width_mm: float
    height_mm: float
    corner_mm: float
    bezel_mm: float
    finish: str
    action_button: bool = False
    camera_control: bool = False
    landscape_camera: bool = False


def _phone(name, w, h, cutout, camera, finish, corner, bezel, action=False, control=False):
    return ModelSpec(name, "iphone", cutout, camera, w, h, corner, bezel, finish, action, control)


def _pad(name, w, h, cutout, camera, finish, landscape=False):
    return ModelSpec(name, "ipad", cutout, camera, w, h, 12.0 if cutout == "ipad" else 10.0,
                     6.0 if cutout == "ipad" else 9.0, finish, landscape_camera=landscape)


def _many(ids, spec):
    return {i: spec for i in ids}


# Default finishes are each model's darkest colour: lockdown reports colours as undocumented indexes on
# modern devices, so the drawing never claims a specific colour it cannot verify.
_GRAY = "#3d3e41"
_BLACK = "#232325"
_GRAPHITE = "#4a4a4d"
_MIDNIGHT = "#232a31"
_TITANIUM = "#3a3a3d"
_PAD_GRAY = "#6c6d71"
_PAD_BLACK = "#38383a"

CATALOG: dict[str, ModelSpec] = {
    "iPhone7,2": _phone("iPhone 6", 67.0, 138.1, "home", "single", _GRAY, 9.0, 4.0),
    "iPhone7,1": _phone("iPhone 6 Plus", 77.8, 158.1, "home", "single", _GRAY, 10.0, 4.5),
    "iPhone8,1": _phone("iPhone 6s", 67.1, 138.3, "home", "single", _GRAY, 9.0, 4.0),
    "iPhone8,2": _phone("iPhone 6s Plus", 77.9, 158.2, "home", "single", _GRAY, 10.0, 4.5),
    "iPhone8,4": _phone("iPhone SE (1st generation)", 58.6, 123.8, "home", "single", _GRAY, 7.0, 4.0),
    **_many(["iPhone9,1", "iPhone9,3"], _phone("iPhone 7", 67.1, 138.3, "home", "single", _BLACK, 9.0, 4.0)),
    **_many(["iPhone9,2", "iPhone9,4"],
            _phone("iPhone 7 Plus", 77.9, 158.2, "home", "dual_horizontal", _BLACK, 10.0, 4.5)),
    **_many(["iPhone10,1", "iPhone10,4"], _phone("iPhone 8", 67.3, 138.4, "home", "single", _GRAY, 9.0, 4.0)),
    **_many(["iPhone10,2", "iPhone10,5"],
            _phone("iPhone 8 Plus", 78.1, 158.4, "home", "dual_horizontal", _GRAY, 10.0, 4.5)),
    **_many(["iPhone10,3", "iPhone10,6"], _phone("iPhone X", 70.9, 143.6, "notch", "dual_pill", _GRAY, 11.0, 3.2)),
    "iPhone11,2": _phone("iPhone XS", 70.9, 143.6, "notch", "dual_pill", _GRAY, 11.0, 3.2),
    **_many(["iPhone11,4", "iPhone11,6"],
            _phone("iPhone XS Max", 77.4, 157.5, "notch", "dual_pill", _GRAY, 12.0, 3.2)),
    "iPhone11,8": _phone("iPhone XR", 75.7, 150.9, "notch", "single", _BLACK, 11.5, 4.2),
    "iPhone12,1": _phone("iPhone 11", 75.7, 150.9, "notch", "dual_square_vertical", _BLACK, 11.5, 4.2),
    "iPhone12,3": _phone("iPhone 11 Pro", 71.4, 144.0, "notch", "triple", _GRAY, 11.0, 3.2),
    "iPhone12,5": _phone("iPhone 11 Pro Max", 77.8, 158.0, "notch", "triple", _GRAY, 12.0, 3.2),
    "iPhone12,8": _phone("iPhone SE (2nd generation)", 67.3, 138.4, "home", "single", _BLACK, 9.0, 4.0),
    "iPhone13,1": _phone("iPhone 12 mini", 64.2, 131.5, "notch", "dual_square_vertical", _BLACK, 10.0, 2.6),
    "iPhone13,2": _phone("iPhone 12", 71.5, 146.7, "notch", "dual_square_vertical", _BLACK, 11.0, 2.6),
    "iPhone13,3": _phone("iPhone 12 Pro", 71.5, 146.7, "notch", "triple", _GRAPHITE, 11.0, 2.6),
    "iPhone13,4": _phone("iPhone 12 Pro Max", 78.1, 160.8, "notch", "triple", _GRAPHITE, 12.0, 2.6),
    "iPhone14,4": _phone("iPhone 13 mini", 64.2, 131.5, "notch", "dual_square_diagonal", _MIDNIGHT, 10.0, 2.6),
    "iPhone14,5": _phone("iPhone 13", 71.5, 146.7, "notch", "dual_square_diagonal", _MIDNIGHT, 11.0, 2.6),
    "iPhone14,2": _phone("iPhone 13 Pro", 71.5, 146.7, "notch", "triple", _GRAPHITE, 11.0, 2.6),
    "iPhone14,3": _phone("iPhone 13 Pro Max", 78.1, 160.8, "notch", "triple", _GRAPHITE, 12.0, 2.6),
    "iPhone14,6": _phone("iPhone SE (3rd generation)", 67.3, 138.4, "home", "single", _MIDNIGHT, 9.0, 4.0),
    "iPhone14,7": _phone("iPhone 14", 71.5, 146.7, "notch", "dual_square_diagonal", _MIDNIGHT, 11.0, 2.6),
    "iPhone14,8": _phone("iPhone 14 Plus", 78.1, 160.8, "notch", "dual_square_diagonal", _MIDNIGHT, 12.0, 2.6),
    "iPhone15,2": _phone("iPhone 14 Pro", 71.5, 147.5, "island", "triple", _TITANIUM, 11.5, 2.2),
    "iPhone15,3": _phone("iPhone 14 Pro Max", 77.6, 160.7, "island", "triple", _TITANIUM, 12.5, 2.2),
    "iPhone15,4": _phone("iPhone 15", 71.6, 147.6, "island", "dual_square_diagonal", _BLACK, 11.5, 2.4),
    "iPhone15,5": _phone("iPhone 15 Plus", 77.8, 160.9, "island", "dual_square_diagonal", _BLACK, 12.5, 2.4),
    "iPhone16,1": _phone("iPhone 15 Pro", 70.6, 146.6, "island", "triple", _TITANIUM, 11.5, 1.9, action=True),
    "iPhone16,2": _phone("iPhone 15 Pro Max", 76.7, 159.9, "island", "triple", _TITANIUM, 12.5, 1.9, action=True),
    "iPhone17,3": _phone("iPhone 16", 71.6, 147.6, "island", "dual_pill", _BLACK, 11.5, 2.4,
                         action=True, control=True),
    "iPhone17,4": _phone("iPhone 16 Plus", 77.8, 160.9, "island", "dual_pill", _BLACK, 12.5, 2.4,
                         action=True, control=True),
    "iPhone17,1": _phone("iPhone 16 Pro", 71.5, 149.6, "island", "triple", _TITANIUM, 12.0, 1.6,
                         action=True, control=True),
    "iPhone17,2": _phone("iPhone 16 Pro Max", 77.6, 163.0, "island", "triple", _TITANIUM, 12.5, 1.6,
                         action=True, control=True),
    "iPhone17,5": _phone("iPhone 16e", 71.5, 146.7, "notch", "single", _BLACK, 11.0, 2.6, action=True),
    "iPhone18,3": _phone("iPhone 17", 71.5, 149.6, "island", "dual_pill", _BLACK, 12.0, 1.6,
                         action=True, control=True),
    "iPhone18,4": _phone("iPhone Air", 74.7, 156.2, "island", "plateau_air", _BLACK, 12.0, 1.6,
                         action=True, control=True),
    "iPhone18,1": _phone("iPhone 17 Pro", 71.9, 150.0, "island", "plateau_pro", "#2b3a55", 12.0, 1.6,
                         action=True, control=True),
    "iPhone18,2": _phone("iPhone 17 Pro Max", 78.0, 163.4, "island", "plateau_pro", "#2b3a55", 12.5, 1.6,
                         action=True, control=True),
    "iPod9,1": ModelSpec("iPod touch (7th generation)", "ipod", "home", "single", 58.6, 123.4, 7.0, 4.0, _GRAY),
    **_many(["iPad6,11", "iPad6,12"], _pad("iPad (5th generation)", 169.5, 240.0, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad7,5", "iPad7,6"], _pad("iPad (6th generation)", 169.5, 240.0, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad7,11", "iPad7,12"], _pad("iPad (7th generation)", 174.1, 250.6, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad11,6", "iPad11,7"], _pad("iPad (8th generation)", 174.1, 250.6, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad12,1", "iPad12,2"], _pad("iPad (9th generation)", 174.1, 250.6, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad13,18", "iPad13,19"], _pad("iPad (10th generation)", 179.5, 248.6, "ipad", "single", _PAD_GRAY, True)),
    **_many(["iPad15,7", "iPad15,8"], _pad("iPad (A16)", 179.5, 248.6, "ipad", "single", _PAD_GRAY, True)),
    **_many(["iPad5,3", "iPad5,4"], _pad("iPad Air 2", 169.5, 240.0, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad11,3", "iPad11,4"], _pad("iPad Air (3rd generation)", 174.1, 250.6, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad13,1", "iPad13,2"], _pad("iPad Air (4th generation)", 178.5, 247.6, "ipad", "single", _PAD_GRAY)),
    **_many(["iPad13,16", "iPad13,17"], _pad("iPad Air (5th generation)", 178.5, 247.6, "ipad", "single", _PAD_GRAY)),
    **_many(["iPad14,8", "iPad14,9"], _pad("iPad Air 11-inch (M2)", 178.5, 247.6, "ipad", "single", _PAD_GRAY, True)),
    **_many(["iPad14,10", "iPad14,11"],
            _pad("iPad Air 13-inch (M2)", 214.9, 280.6, "ipad", "single", _PAD_GRAY, True)),
    **_many(["iPad15,3", "iPad15,4"], _pad("iPad Air 11-inch (M3)", 178.5, 247.6, "ipad", "single", _PAD_GRAY, True)),
    **_many(["iPad15,5", "iPad15,6"], _pad("iPad Air 13-inch (M3)", 214.9, 280.6, "ipad", "single", _PAD_GRAY, True)),
    **_many(["iPad5,1", "iPad5,2"], _pad("iPad mini 4", 134.8, 203.2, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad11,1", "iPad11,2"],
            _pad("iPad mini (5th generation)", 134.8, 203.2, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad14,1", "iPad14,2"], _pad("iPad mini (6th generation)", 134.8, 195.4, "ipad", "single", _PAD_GRAY)),
    **_many(["iPad16,1", "iPad16,2"], _pad("iPad mini (A17 Pro)", 134.8, 195.4, "ipad", "single", _PAD_GRAY)),
    **_many(["iPad6,3", "iPad6,4"], _pad("iPad Pro 9.7-inch", 169.5, 240.0, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad7,3", "iPad7,4"], _pad("iPad Pro 10.5-inch", 174.1, 250.6, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad6,7", "iPad6,8"],
            _pad("iPad Pro 12.9-inch (1st generation)", 220.6, 305.7, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad7,1", "iPad7,2"],
            _pad("iPad Pro 12.9-inch (2nd generation)", 220.6, 305.7, "ipad_home", "single", _PAD_GRAY)),
    **_many(["iPad8,1", "iPad8,2", "iPad8,3", "iPad8,4"],
            _pad("iPad Pro 11-inch (1st generation)", 178.5, 247.6, "ipad", "single", _PAD_GRAY)),
    **_many(["iPad8,5", "iPad8,6", "iPad8,7", "iPad8,8"],
            _pad("iPad Pro 12.9-inch (3rd generation)", 214.9, 280.6, "ipad", "single", _PAD_GRAY)),
    **_many(["iPad8,9", "iPad8,10"],
            _pad("iPad Pro 11-inch (2nd generation)", 178.5, 247.6, "ipad", "ipad_pro", _PAD_GRAY)),
    **_many(["iPad8,11", "iPad8,12"],
            _pad("iPad Pro 12.9-inch (4th generation)", 214.9, 280.6, "ipad", "ipad_pro", _PAD_GRAY)),
    **_many(["iPad13,4", "iPad13,5", "iPad13,6", "iPad13,7"],
            _pad("iPad Pro 11-inch (3rd generation)", 178.5, 247.6, "ipad", "ipad_pro", _PAD_GRAY)),
    **_many(["iPad13,8", "iPad13,9", "iPad13,10", "iPad13,11"],
            _pad("iPad Pro 12.9-inch (5th generation)", 214.9, 280.6, "ipad", "ipad_pro", _PAD_GRAY)),
    **_many(["iPad14,3", "iPad14,4"],
            _pad("iPad Pro 11-inch (4th generation)", 178.5, 247.6, "ipad", "ipad_pro", _PAD_GRAY)),
    **_many(["iPad14,5", "iPad14,6"],
            _pad("iPad Pro 12.9-inch (6th generation)", 214.9, 280.6, "ipad", "ipad_pro", _PAD_GRAY)),
    **_many(["iPad16,3", "iPad16,4"],
            _pad("iPad Pro 11-inch (M4)", 177.5, 249.7, "ipad", "ipad_pro", _PAD_BLACK, True)),
    **_many(["iPad16,5", "iPad16,6"],
            _pad("iPad Pro 13-inch (M4)", 215.5, 281.6, "ipad", "ipad_pro", _PAD_BLACK, True)),
}

_FALLBACK_PHONE = _phone("iPhone", 71.5, 149.6, "island", "dual_pill", _BLACK, 12.0, 1.6)
_FALLBACK_PAD = _pad("iPad", 178.5, 247.6, "ipad", "single", _PAD_GRAY)
_FALLBACK_OTHER = ModelSpec("Apple device", "iphone", "island", "dual_pill", 71.5, 149.6, 12.0, 1.6, _BLACK)
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def lookup(product_type: str, device_class: str = "") -> ModelSpec:
    spec = CATALOG.get(product_type)
    if spec:
        return spec
    hint = (device_class or product_type).lower()
    if hint.startswith("ipad"):
        return _FALLBACK_PAD
    if hint.startswith("iphone"):
        return _FALLBACK_PHONE
    return _FALLBACK_OTHER


def resolve_finish(spec: ModelSpec, enclosure_color: str | None) -> str:
    if enclosure_color and _HEX.fullmatch(enclosure_color):
        return enclosure_color.lower()
    return spec.finish
