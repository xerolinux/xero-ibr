import plistlib

from ibr.core.homescreen import HomeIcon, parse_icon_state


def state(*pages):
    return plistlib.dumps(list(pages))


def app(name, bundle):
    return {"displayName": name, "bundleIdentifier": bundle, "displayIdentifier": bundle}


def test_dock_then_apps_in_home_screen_order():
    data = state(
        [app("Phone", "com.apple.mobilephone"), app("Messages", "com.apple.MobileSMS")],
        [app("Discord", "com.hammerandchisel.discord"), app("‎WhatsApp", "net.whatsapp.WhatsApp")],
        [app("Later", "com.example.later")],
    )
    home = parse_icon_state(data)
    assert home.dock == [HomeIcon("Phone", "com.apple.mobilephone"), HomeIcon("Messages", "com.apple.MobileSMS")]
    assert home.apps == [HomeIcon("Discord", "com.hammerandchisel.discord"),
                         HomeIcon("WhatsApp", "net.whatsapp.WhatsApp"),
                         HomeIcon("Later", "com.example.later")]


def test_folders_kept_widgets_skipped():
    folder = {"displayName": "Utilities", "listType": "folder",
              "iconLists": [[app("Calculator", "com.apple.calculator"), app("Compass", "com.apple.compass")]]}
    widget = {"elementType": "widget", "gridSize": "medium"}
    home = parse_icon_state(state([], [folder, widget, app("Notes", "com.apple.mobilenotes")]))
    assert home.apps == [HomeIcon("Utilities", None, ["com.apple.calculator", "com.apple.compass"]),
                         HomeIcon("Notes", "com.apple.mobilenotes")]


def test_bad_data():
    home = parse_icon_state(b"nope")
    assert home.dock == [] and home.apps == []


def test_names_cover_every_app_including_folders():
    folder = {"displayName": "Utilities", "listType": "folder",
              "iconLists": [[app("Calculator", "com.apple.calculator")], [app("‎Compass", "com.apple.compass")]]}
    home = parse_icon_state(state([app("Phone", "com.apple.mobilephone")], [folder],
                                  [app("Notes", "com.apple.mobilenotes")]))
    assert home.names == {"com.apple.mobilephone": "Phone", "com.apple.calculator": "Calculator",
                          "com.apple.compass": "Compass", "com.apple.mobilenotes": "Notes"}
