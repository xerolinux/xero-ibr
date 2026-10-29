from ibr.core.sounds import SoundGate


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_gate():
    played, clock = [], Clock()
    return SoundGate(played.append, clock), played, clock


def test_click_plays():
    gate, played, _ = make_gate()
    gate.click()
    assert played == ["click"]


def test_hover_plays_once_per_target():
    gate, played, clock = make_gate()
    gate.hover("a")
    clock.now = 1.0
    gate.hover("a")
    assert played == ["hover"]


def test_hover_on_a_new_target_plays_again():
    gate, played, clock = make_gate()
    gate.hover("a")
    clock.now = 1.0
    gate.hover("b")
    assert played == ["hover", "hover"]


def test_rapid_hovers_are_throttled():
    gate, played, clock = make_gate()
    gate.hover("a")
    clock.now = 0.02
    gate.hover("b")
    assert played == ["hover"]


def test_leaving_a_target_lets_it_play_again():
    gate, played, clock = make_gate()
    gate.hover("a")
    gate.hover(None)
    clock.now = 1.0
    gate.hover("a")
    assert played == ["hover", "hover"]


def test_disabled_gate_is_silent():
    gate, played, _ = make_gate()
    gate.enabled = False
    gate.hover("a")
    gate.click()
    assert played == []


def test_cue_plays_by_name():
    gate, played, _ = make_gate()
    gate.cue("matrix")
    assert played == ["matrix"]


def test_cue_respects_the_sound_switch():
    gate, played, _ = make_gate()
    gate.enabled = False
    gate.cue("matrix")
    assert played == []
