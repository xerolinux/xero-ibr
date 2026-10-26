import time

from gi.repository import GLib, Gtk

from ..core.fmt import format_eta, format_size, format_speed
from ..core.progress import Bytes, Finished, Percent, Phase, Sent, SpeedMeter, TransferCounter
from .widgets import hbox, label, set_classes, vbox

_STEPS = {
    "backup": ("Preparing", "Receiving files", "Finishing"),
    "restore": ("Preparing", "Sending files", "Finishing"),
}
_PHASE_TEXT = {
    "starting": "Preparing",
    "passcode": "Enter your passcode on the device to continue",
    "receiving": "Receiving files",
    "sending": "Sending files",
}


class ProgressCard(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add_css_class("progress-card")

        top = hbox(12)
        left = vbox(4)
        left.set_hexpand(True)
        self._phase = label("Preparing", "card-label")
        self._copied = label("Waiting for device", "h3")
        left.append(self._phase)
        left.append(self._copied)
        top.append(left)
        self._percent = label("", "big-percent", xalign=1.0)
        self._percent.set_valign(Gtk.Align.END)
        top.append(self._percent)
        self.append(top)

        self._bar = Gtk.ProgressBar()
        self._bar.add_css_class("thick")
        self._bar.set_pulse_step(0.04)
        self.append(self._bar)

        self._steps_box = hbox(8)
        self.append(self._steps_box)

        stats = Gtk.Grid(column_spacing=12, column_homogeneous=True)
        stats.add_css_class("stats")
        self._stat_values = []
        for column, title in enumerate(("Copied", "Speed", "Time left")):
            cell = vbox(2)
            cell.append(label(title, "card-label"))
            value = label("…", "stat-value")
            self._stat_values.append(value)
            cell.append(value)
            stats.attach(cell, column, 0, 1, 1)
        self.append(stats)

        self._pulse_id = 0
        self.reset("backup")
        self._stop_pulse()

    def reset(self, kind: str):
        self._kind = kind
        self._counter = TransferCounter()
        self._bytes_meter = SpeedMeter()
        self._percent_meter = SpeedMeter()
        self._percent_value = None
        self._step = 0
        self._phase.set_label("Preparing")
        self._copied.set_label("Waiting for device")
        self._percent.set_label("")
        for value in self._stat_values:
            value.set_label("…")
        self._bar.set_fraction(0)
        self._build_steps()
        self._start_pulse()

    def _build_steps(self):
        while child := self._steps_box.get_first_child():
            self._steps_box.remove(child)
        self._step_labels = []
        for index, name in enumerate(_STEPS[self._kind]):
            if index:
                line = Gtk.Box()
                line.add_css_class("step-line")
                line.set_valign(Gtk.Align.CENTER)
                self._steps_box.append(line)
            step = label(name, "step")
            self._step_labels.append(step)
            self._steps_box.append(step)
        self._render_steps()

    def _render_steps(self):
        names = _STEPS[self._kind]
        for index, step in enumerate(self._step_labels):
            if index < self._step:
                step.set_label(f"✓ {names[index]}")
                set_classes(step, "done", keep=("step",))
            elif index == self._step:
                step.set_label(f"● {names[index]}")
                set_classes(step, "current", keep=("step",))
            else:
                step.set_label(names[index])
                set_classes(step, keep=("step",))

    def _start_pulse(self):
        if not self._pulse_id:
            self._pulse_id = GLib.timeout_add(120, self._pulse)

    def _stop_pulse(self):
        if self._pulse_id:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = 0

    def _pulse(self):
        self._bar.pulse()
        return GLib.SOURCE_CONTINUE

    def _set_step(self, step: int):
        if step > self._step:
            self._step = step
            self._render_steps()

    def handle(self, event):
        now = time.monotonic()
        if isinstance(event, Phase):
            self._phase.set_label(_PHASE_TEXT.get(event.name, event.name.title()))
            if event.name in ("receiving", "sending"):
                self._set_step(1)
        elif isinstance(event, Percent):
            self._stop_pulse()
            self._percent_value = event.value
            self._percent.set_label(f"{event.value:.0f}%")
            self._bar.set_fraction(event.value / 100)
            self._percent_meter.update(event.value, now)
            if event.value >= 100:
                self._set_step(2)
            self._update_eta()
        elif isinstance(event, Bytes):
            self._update_bytes(self._counter.batch(event.done, event.total), now)
        elif isinstance(event, Sent):
            self._update_bytes(self._counter.sent(event.size), now)
        elif isinstance(event, Finished):
            self.finish(event.success)

    def _update_bytes(self, copied: int, now: float):
        self._set_step(1)
        self._copied.set_label(format_size(copied))
        self._stat_values[0].set_label(format_size(copied))
        self._bytes_meter.update(copied, now)
        if self._bytes_meter.speed:
            self._stat_values[1].set_label(format_speed(self._bytes_meter.speed))

    def _update_eta(self):
        if self._percent_value is None:
            return
        self._stat_values[2].set_label(format_eta(self._percent_meter.eta(100, self._percent_value)))

    def waiting(self, text: str):
        self._phase.set_label("Reconnecting")
        self._copied.set_label(text)
        self._percent.set_label("")
        self._start_pulse()

    def finish(self, success: bool):
        self._stop_pulse()
        if success:
            self._bar.set_fraction(1)
            self._percent.set_label("100%")
            self._step = len(_STEPS[self._kind])
            self._render_steps()
            self._stat_values[2].set_label("Done")

    def do_unroot(self):
        self._stop_pulse()
        Gtk.Box.do_unroot(self)
