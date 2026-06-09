import sys
import subprocess
import inspect
import time
from collections.abc import Iterable
import numpy as np

from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QWidget,
    QSplitter,
    QFrame,
    QFileDialog,
    QScrollArea,
)
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6 import QtWebEngineCore

import py_gearworks as pgw
import build123d as bd
from ocp_vscode import show, set_port, Camera, set_defaults, Animation

geartypes = [
    "SpurGear",
    "SpurRingGear",
    "HelicalGear",
    "HelicalRingGear",
    "BevelGear",
    "CycloidGear",
]


class ViewerWindow(QFrame):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gggears GUI Viewer")
        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl("http://127.0.0.1:3939"))
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.webview)
        
        self.webview.page().settings().setAttribute(
            QtWebEngineCore.QWebEngineSettings.WebAttribute.ShowScrollBars, False
        )


class InputArgPanel(QWidget):
    def __init__(self, signature: inspect.Signature):
        super().__init__()
        self.signature = signature
        self.dictionary = self.init_dict()
        self.spin_boxes = {}
        self.initUI()

    def init_dict(self):
        dictionary = {}
        for key, param in self.signature.parameters.items():
            value = param.default
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
                dictionary[key] = list(value)
            elif value != inspect.Parameter.empty:
                dictionary[key] = value
            else:
                dictionary[key] = 0

        # Number of teeth default override logic
        dictionary["number_of_teeth"] = 12
        return dictionary

    def initUI(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll Area holds components if the parameter form expands past screen limits
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content_widget = QWidget()
        form_layout = QFormLayout(content_widget)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        for key, param in self.signature.parameters.items():
            label = QLabel(f"{key}:")
            value = param.default

            if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
                layout_loc = QHBoxLayout()
                layout_loc.setContentsMargins(0, 0, 0, 0)
                for i in range(len(value)):
                    box = QDoubleSpinBox()
                    box.setRange(-10000.0, 10000.0)
                    box.setValue(value[i])
                    box.valueChanged.connect(
                        lambda val, k=key, idx=i: self.update_dict_iterable(k, idx, val)
                    )
                    layout_loc.addWidget(box)
                input_widget = QWidget()
                input_widget.setLayout(layout_loc)
            else:
                if param.annotation is int:
                    input_widget = QSpinBox()
                    input_widget.setRange(-10000, 10000)
                    input_widget.valueChanged.connect(
                        lambda val, k=key: self.update_dict(k, val)
                    )
                    if value != inspect.Parameter.empty:
                        input_widget.setValue(value)
                    if key == "number_of_teeth":
                        input_widget.setValue(12)
                        input_widget.setRange(1, 500)
                elif param.annotation is bool:
                    input_widget = QCheckBox()
                    input_widget.stateChanged.connect(
                        lambda val, k=key: self.update_dict(k, bool(val))
                    )
                    if value != inspect.Parameter.empty:
                        input_widget.setChecked(value)
                else:
                    input_widget = QDoubleSpinBox()
                    input_widget.setSingleStep(0.1)
                    input_widget.setRange(-10000.0, 10000.0)
                    input_widget.setDecimals(3)
                    if "angle" in key:
                        input_widget.setDecimals(1)
                        input_widget.setRange(-360.0, 360.0)
                        input_widget.valueChanged.connect(
                            lambda val, k=key: self.update_dict(k, val * pgw.PI / 180.0)
                        )
                        if value != inspect.Parameter.empty:
                            input_widget.setValue(value / pgw.PI * 180.0)
                    else:
                        input_widget.valueChanged.connect(
                            lambda val, k=key: self.update_dict(k, val)
                        )
                        if value != inspect.Parameter.empty:
                            input_widget.setValue(value)

            form_layout.addRow(label, input_widget)
            self.spin_boxes[key] = input_widget

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

    def update_dict(self, key, value):
        self.dictionary[key] = value

    def update_dict_iterable(self, key, idx, value):
        self.dictionary[key][idx] = value


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gggears GUI Main")
        self.resize(1100, 700)

        layout_base = QHBoxLayout()

        self.viewer = ViewerWindow()
        self.viewer.setFrameShape(QFrame.Shape.Box)
        self.viewer.setFrameShadow(QFrame.Shadow.Raised)

        self.gear_selector_left = QComboBox(self)
        self.gear_selector_left.addItems(geartypes)
        self.gear_selector_left.currentTextChanged.connect(lambda text: self.change_gear_type("left", text))

        self.gear_selector_right = QComboBox(self)
        self.gear_selector_right.addItems(geartypes)
        self.gear_selector_right.currentTextChanged.connect(lambda text: self.change_gear_type("right", text))

        generate_button_left = QPushButton("Generate 1!")
        generate_button_left.clicked.connect(lambda: self.generate_gear("left"))

        generate_button_right = QPushButton("Generate 2!")
        generate_button_right.clicked.connect(lambda: self.generate_gear("right"))

        save_button_left = QPushButton("Save 1!")
        save_button_left.clicked.connect(lambda: self.file_save(0))
        save_button_right = QPushButton("Save 2!")
        save_button_right.clicked.connect(lambda: self.file_save(1))

        cls = getattr(pgw, geartypes[0])
        sig_left = inspect.signature(cls)
        sig_right = inspect.signature(cls)

        self.numpanel_left = InputArgPanel(sig_left)
        self.left_layout = QVBoxLayout()
        self.left_layout.addWidget(self.gear_selector_left)
        param_label_left = QLabel("Gear Parameters")
        param_label_left.setAlignment(Qt.AlignmentFlag.AlignBottom)
        self.left_layout.addWidget(param_label_left)
        self.left_layout.addWidget(self.numpanel_left)
        self.left_layout.addWidget(generate_button_left)
        self.left_layout.addWidget(save_button_left)

        self.numpanel_right = InputArgPanel(sig_right)
        self.right_layout = QVBoxLayout()
        self.right_layout.addWidget(self.gear_selector_right)
        param_label_right = QLabel("Gear Parameters")
        param_label_right.setAlignment(Qt.AlignmentFlag.AlignBottom)
        self.right_layout.addWidget(param_label_right)
        self.right_layout.addWidget(self.numpanel_right)
        self.right_layout.addWidget(generate_button_right)
        self.right_layout.addWidget(save_button_right)

        clearbutton = QPushButton("Clear Gears")
        clearbutton.clicked.connect(self.clear_gears)

        self.animatebutton = QPushButton("Animate Gears")
        self.animatebutton.setEnabled(False)
        self.animatebutton.clicked.connect(self.animate_gears)

        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.Box)
        panel.setFrameShadow(QFrame.Shadow.Raised)
        panel_layout = QHBoxLayout(panel)
        panel_layout.addLayout(self.left_layout)
        panel_layout.addLayout(self.right_layout)

        panel_container = QWidget()
        panel_container_layout = QVBoxLayout(panel_container)
        panel_container_layout.addWidget(clearbutton)
        panel_container_layout.addWidget(self.animatebutton)
        panel_container_layout.addWidget(panel)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(panel_container)
        splitter.addWidget(self.viewer)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout_base.addWidget(splitter)

        widget = QWidget()
        widget.setLayout(layout_base)
        self.setCentralWidget(widget)

        self.gear1: pgw.GearInfoMixin = None
        self.gear2: pgw.GearInfoMixin = None
        self.gearparts = [pgw.Part(), pgw.Part()]
        self.geargen_finished = [False, False]

    def generate_gear(self, side: str):
        is_left = (side == "left")
        panel = self.numpanel_left if is_left else self.numpanel_right
        selector = self.gear_selector_left if is_left else self.gear_selector_right
        idx = 0 if is_left else 1
        other_idx = 1 if is_left else 0

        sig = panel.signature
        data_dict = panel.dictionary
        positional_args = []
        keyword_args = {}

        for key in sig.parameters.keys():
            value = sig.parameters[key].default
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
                keyword_args[key] = data_dict[key]
            elif value == inspect.Parameter.empty:
                positional_args.append(data_dict[key])
            else:
                keyword_args[key] = data_dict[key]

        cls = getattr(pgw, selector.currentText())
        gear = cls(*positional_args, **keyword_args)

        if is_left:
            self.gear1 = gear
        else:
            self.gear2 = gear
            if self.geargen_finished[0]:
                self.gear2.mesh_to(self.gear1)

        gearpart = gear.build_part()
        gearpart.label = f"Gear{idx + 1}"
        self.gearparts[idx] = gearpart

        camera_opts = Camera.KEEP if any(self.geargen_finished) else Camera.RESET
        show(self.gearparts, reset_camera=camera_opts)
        
        self.geargen_finished[idx] = True
        if self.geargen_finished[other_idx]:
            self.animatebutton.setEnabled(True)

    def change_gear_type(self, side: str, text: str):
        cls = getattr(pgw, text)
        sig = inspect.signature(cls)
        
        layout = self.left_layout if side == "left" else self.right_layout
        old_panel = self.numpanel_left if side == "left" else self.numpanel_right

        index = layout.indexOf(old_panel)
        layout.removeWidget(old_panel)
        old_panel.deleteLater()

        new_panel = InputArgPanel(sig)
        layout.insertWidget(index, new_panel)

        if side == "left":
            self.numpanel_left = new_panel
        else:
            self.numpanel_right = new_panel

    def clear_gears(self):
        self.gearparts = [pgw.Part(), pgw.Part()]
        self.geargen_finished = [False, False]
        show(self.gearparts, reset_camera=Camera.RESET)
        self.animatebutton.setEnabled(False)

    def animate_gears(self):
        a_gear1 = bd.Compound(
            children=[self.gear1.center_location_bottom.inverse() * self.gearparts[0].solid()],
            label="gear1",
        )
        a_gear2 = bd.Compound(
            children=[self.gear2.center_location_bottom.inverse() * self.gearparts[1].solid()],
            label="gear2",
        )
        a_gear1.location = self.gear1.center_location_bottom
        a_gear2.location = self.gear2.center_location_bottom
        gears = bd.Compound(children=[a_gear1, a_gear2], label="gears")

        n = 30
        duration = 2

        angle_sign_1 = -1 if self.gear1.gearcore.tooth_param.inside_teeth else 1
        angle_sign_2 = -1 if self.gear2.gearcore.tooth_param.inside_teeth else 1
        time_track = np.linspace(0, duration, n + 1)
        gear1_track = np.linspace(0, -self.gear1.pitch_angle * angle_sign_1 * 180 / np.pi * 2, n + 1)
        gear2_track = np.linspace(0, self.gear2.pitch_angle * angle_sign_2 * 180 / np.pi * 2, n + 1)
        
        animation = Animation(gears)
        animation.add_track("/gears/gear1", "rz", time_track, gear1_track)
        animation.add_track("/gears/gear2", "rz", time_track, gear2_track)
        show(gears)
        animation.animate(speed=1)

    def file_save(self, idx: int):
        if not self.geargen_finished[idx]:
            return
            
        name, chosen_filter = QFileDialog.getSaveFileName(
            self,
            f"Save Gear {idx + 1}",
            filter="STL files (*.stl);;STEP files (*.stp *.step);; GLTF files (*.gltf)",
        )
        if name:
            if "STEP" in chosen_filter:
                pgw.export_step(self.gearparts[idx], name)
            elif "STL" in chosen_filter:
                pgw.export_stl(self.gearparts[idx], name)
            elif "GLTF" in chosen_filter:
                pgw.export_gltf(self.gearparts[idx], name)


dark_stylesheet = """
QWidget {
    background-color: #2b2b2b;
    color: #ffffff;
}
QPushButton {
    background-color: #3c3c3c;
    color: #ffffff;
    border: 1px solid #555555;
    padding: 4px;
}
QPushButton:hover {
    background-color: #4c4c4c;
}
QSpinBox, QDoubleSpinBox, QCheckBox {
    background-color: #3c3c3c;
    color: #ffffff;
    border: 1px solid #555555;
}
QLabel {
    color: #ffffff;
}
QComboBox {
    background-color: #3c3c3c;
    color: #ffffff;
    border: 1px solid #555555;
}
QComboBox QAbstractItemView {
    background-color: #3c3c3c;
    color: #ffffff;
    selection-background-color: #4c4c4c;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:vertical {
    border: none;
    background: #2b2b2b;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: #555555;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #777777;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    background: none;
    border: none;
}
"""

if __name__ == "__main__":
    ocp_view_process = subprocess.Popen(
        [sys.executable, "-m", "ocp_vscode", "--port", "3939", "--theme", "dark"]
    )
    
    try:
        # Give ocp_vscode subprocess adequate setup headroom
        time.sleep(5)
        
        set_port(3939)
        set_defaults(reset_camera=Camera.KEEP, grid=(True, True, False))

        app = QApplication(sys.argv)
        app.setStyleSheet(dark_stylesheet)
        window = MainWindow()
        window.show()
        app.exec()
        
    finally:
        # Guarantees process cleanup on normal exits or runtime crashes
        ocp_view_process.kill()