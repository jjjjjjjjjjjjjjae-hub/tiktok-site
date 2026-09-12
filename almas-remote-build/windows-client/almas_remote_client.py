import io
import json
import math
import os
import queue
import socket
import struct
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from PIL import Image, ImageTk

APP = "Almas Remote Client"
PROFILE = os.path.join(os.path.expanduser("~"), ".almas_remote_profile.json")

TOUCH_ACTIONS = ["joystick", "camera", "run", "jump", "fire", "aim", "reload", "interact"]
LABELS = {
    "joystick": "Joystick ортасы",
    "camera": "Камера аймағы",
    "run": "Жүгіру / Run",
    "jump": "Секіру / Jump",
    "fire": "Ату / Fire",
    "aim": "Прицел / Aim",
    "reload": "Оқтау / Reload",
    "interact": "Әрекет / Interact",
}
KEY_ACTIONS = ["move_up", "move_down", "move_left", "move_right", "run", "jump", "fire", "aim", "reload", "interact"]
KEY_LABELS = {
    "move_up": "Алға",
    "move_down": "Артқа",
    "move_left": "Солға",
    "move_right": "Оңға",
    "run": "Жүгіру",
    "jump": "Секіру",
    "fire": "Ату",
    "aim": "Прицел",
    "reload": "Оқтау",
    "interact": "Әрекет",
}
DEFAULT_KEYS = {
    "move_up": "w",
    "move_down": "s",
    "move_left": "a",
    "move_right": "d",
    "run": "shift",
    "jump": "space",
    "fire": "",
    "aim": "",
    "reload": "r",
    "interact": "f",
}
DEFAULT = {
    "joystick": [0.18, 0.73],
    "camera": [0.72, 0.50],
    "run": [0.82, 0.61],
    "jump": [0.89, 0.48],
    "fire": [0.92, 0.67],
    "aim": [0.82, 0.37],
    "reload": [0.76, 0.77],
    "interact": [0.62, 0.64],
    "joystick_radius": 0.10,
    "camera_sensitivity": 0.09,
    "auto_camera_turn": True,
    "mapping_enabled": True,
    "keys": DEFAULT_KEYS.copy(),
}


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def norm_key(keysym):
    k = (keysym or "").lower()
    aliases = {
        "shift_l": "shift", "shift_r": "shift",
        "control_l": "ctrl", "control_r": "ctrl",
        "alt_l": "alt", "alt_r": "alt",
        "return": "enter", "escape": "esc",
        "prior": "pageup", "next": "pagedown",
    }
    return aliases.get(k, k)


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP)
        root.geometry("1180x720")
        root.minsize(900, 560)
        self.profile = self.load_profile()
        self.video_sock = None
        self.ctrl_sock = None
        self.connected = False
        self.frames = queue.Queue(maxsize=2)
        self.pressed = set()
        self.bind_mode = None
        self.current_image = None
        self.current_photo = None
        self.img_rect = (0, 0, 1, 1)
        self.gear_rect = (0, 0, 0, 0)
        self.running = True
        self.foreground_package = ""
        self.game_mode = False
        self.touch_start = None
        self.touch_last = None
        self.settings = None
        self.capture_popup = None
        self.capture_action = None
        self.key_vars = {}
        self.joystick_photo = None
        self.build_ui()
        self.bind_inputs()
        root.after(30, self.ui_tick)
        threading.Thread(target=self.movement_loop, daemon=True).start()

    def load_profile(self):
        out = DEFAULT.copy()
        out["keys"] = DEFAULT_KEYS.copy()
        try:
            with open(PROFILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            for k, v in old.items():
                if k != "keys":
                    out[k] = v
            if isinstance(old.get("keys"), dict):
                out["keys"].update(old["keys"])
            if "auto_camera_turn" not in old and "auto_camera_left" in old:
                out["auto_camera_turn"] = bool(old["auto_camera_left"])
        except Exception:
            pass
        return out

    def save_profile(self, quiet=False):
        try:
            with open(PROFILE, "w", encoding="utf-8") as f:
                json.dump(self.profile, f, ensure_ascii=False, indent=2)
            if not quiet:
                self.status.set("Настройка сақталды")
        except Exception as ex:
            messagebox.showerror(APP, str(ex))

    def build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Телефон IP:").pack(side="left")
        self.ip = tk.StringVar(value="192.168.1.100")
        ttk.Entry(top, textvariable=self.ip, width=16).pack(side="left", padx=(4, 10))
        ttk.Label(top, text="PIN:").pack(side="left")
        self.pin = tk.StringVar()
        ttk.Entry(top, textvariable=self.pin, width=9, show="•").pack(side="left", padx=(4, 10))
        self.btn_connect = ttk.Button(top, text="Қосылу", command=self.toggle_connect)
        self.btn_connect.pack(side="left")
        self.status = tk.StringVar(value="Қосылмаған")
        ttk.Label(top, textvariable=self.status).pack(side="left", padx=14)
        self.mode = tk.StringVar(value="⌨ KEYMAP ON" if self.profile.get("mapping_enabled", True) else "⌨ KEYMAP OFF")
        ttk.Label(top, textvariable=self.mode, font=("Segoe UI", 10, "bold")).pack(side="right", padx=(8, 4))
        ttk.Button(top, text="⚙ Настройка", command=self.open_settings).pack(side="right", padx=6)

        self.canvas = tk.Canvas(self.root, bg="#101215", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_touchpad_down)
        self.canvas.bind("<B1-Motion>", self.on_touchpad_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_touchpad_up)
        self.canvas.bind("<ButtonPress-3>", self.on_touchpad_right)
        self.canvas.bind("<MouseWheel>", self.on_touchpad_scroll)
        self.canvas.bind("<Button-4>", lambda e: self.on_touchpad_scroll_linux(e, -1))
        self.canvas.bind("<Button-5>", lambda e: self.on_touchpad_scroll_linux(e, 1))

        bottom = ttk.Frame(self.root, padding=(8, 4, 8, 8))
        bottom.pack(fill="x")
        ttk.Label(bottom, text="Ноутбук touchpad: 1 рет басу = телефонға tap, басып сүйреу = swipe, 2 саусақ scroll = телефонды айналдыру. ⚙ әрқашан бар.").pack(side="left")

    def bind_inputs(self):
        self.root.bind_all("<KeyPress>", self.key_down)
        self.root.bind_all("<KeyRelease>", self.key_up)

    def settings_open(self):
        try:
            return self.settings is not None and self.settings.winfo_exists()
        except Exception:
            return False

    def capture_open(self):
        try:
            return self.capture_popup is not None and self.capture_popup.winfo_exists()
        except Exception:
            return False

    def open_settings(self):
        if self.settings_open():
            self.settings.deiconify()
            self.settings.lift()
            self.settings.focus_force()
            return

        w = tk.Toplevel(self.root)
        self.settings = w
        w.title("Almas Remote — Настройка")
        w.geometry("680x680")
        w.minsize(590, 540)
        w.protocol("WM_DELETE_WINDOW", self.close_settings)

        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        keys_tab = ttk.Frame(nb, padding=12)
        points_tab = ttk.Frame(nb, padding=12)
        joystick_tab = ttk.Frame(nb, padding=12)
        nb.add(keys_tab, text="Пернелер")
        nb.add(points_tab, text="Экран нүктелері")
        nb.add(joystick_tab, text="Joystick / камера")

        self.mapping_var = tk.BooleanVar(value=bool(self.profile.get("mapping_enabled", True)))
        ttk.Checkbutton(keys_tab, text="⌨ Перне басқаруын қосу", variable=self.mapping_var, command=self.mapping_changed).pack(anchor="w", pady=(0, 12))
        ttk.Label(keys_tab, text="Функцияны таңда → «Перне таңдау» бас → шыққан кішкентай терезеде клавиатурадан бір батырма бас.", wraplength=610).pack(anchor="w", pady=(0, 10))

        self.key_vars = {}
        grid = ttk.Frame(keys_tab)
        grid.pack(fill="x")
        for row, action in enumerate(KEY_ACTIONS):
            ttk.Label(grid, text=KEY_LABELS[action], width=20).grid(row=row, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=self.pretty_key(self.profile["keys"].get(action, "")))
            self.key_vars[action] = var
            ttk.Label(grid, textvariable=var, width=14, font=("Segoe UI", 10, "bold")).grid(row=row, column=1, sticky="w", padx=8)
            ttk.Button(grid, text="Перне таңдау", command=lambda a=action: self.begin_key_capture(a)).grid(row=row, column=2, sticky="ew", pady=3)
        ttk.Label(keys_tab, text="Бір перне тек бір функцияда болады. Мысалы A-ны Жүгіруге қойсаң, ол бұрынғы Солға функциясынан автоматты алынады.", wraplength=610).pack(anchor="w", pady=(14, 4))

        ttk.Label(points_tab, text="Функцияны бас → настройка жабылады → телефон экранында сол батырманың орнын touchpad-пен бір рет бас.", wraplength=610).pack(anchor="w", pady=(0, 10))
        for a in TOUCH_ACTIONS:
            ttk.Button(points_tab, text=f"Экраннан орнын таңдау: {LABELS[a]}", command=lambda x=a: self.start_point_pick(x)).pack(fill="x", pady=3)

        try:
            img = Image.open(resource_path("joystick.jpg")).convert("RGB")
            img.thumbnail((320, 190))
            self.joystick_photo = ImageTk.PhotoImage(img)
            ttk.Label(joystick_tab, image=self.joystick_photo).pack(pady=(0, 10))
        except Exception:
            ttk.Label(joystick_tab, text="Joystick суреті табылмады").pack()

        self.auto_cam_var = tk.BooleanVar(value=bool(self.profile.get("auto_camera_turn", True)))
        ttk.Checkbutton(joystick_tab, text="Оң/солға жүргенде камераны автоматты бұру", variable=self.auto_cam_var, command=self.auto_cam_changed).pack(anchor="w", pady=6)
        ttk.Label(joystick_tab, text="Камера бұрылу күші").pack(anchor="w", pady=(12, 2))
        self.cam_sens_var = tk.DoubleVar(value=float(self.profile.get("camera_sensitivity", 0.09)))
        ttk.Scale(joystick_tab, from_=0.02, to=0.25, variable=self.cam_sens_var, command=self.camera_sens_changed).pack(fill="x")
        ttk.Label(joystick_tab, text="Joystick радиусы").pack(anchor="w", pady=(16, 2))
        self.radius_var = tk.DoubleVar(value=float(self.profile.get("joystick_radius", 0.10)))
        ttk.Scale(joystick_tab, from_=0.03, to=0.22, variable=self.radius_var, command=self.radius_changed).pack(fill="x")
        ttk.Label(joystick_tab, text="Оңға жүру пернесін ұстасаң: joystick оңға, камера аймағы солға swipe жасайды — ойын экраны оңға бұрылады. Солға жүргенде керісінше.", wraplength=610).pack(anchor="w", pady=14)

        footer = ttk.Frame(w, padding=(10, 0, 10, 10))
        footer.pack(fill="x")
        ttk.Button(footer, text="Сақтау", command=self.save_profile).pack(side="right", padx=4)
        ttk.Button(footer, text="Жабу", command=self.close_settings).pack(side="right")

    def close_settings(self):
        self.cancel_key_capture()
        try:
            if self.settings is not None:
                self.settings.destroy()
        except Exception:
            pass
        self.settings = None
        try:
            self.root.focus_force()
        except Exception:
            pass

    def pretty_key(self, k):
        return k.upper() if k else "—"

    def refresh_key_vars(self):
        for a, var in self.key_vars.items():
            var.set(self.pretty_key(self.profile["keys"].get(a, "")))

    def begin_key_capture(self, action):
        self.cancel_key_capture()
        self.capture_action = action
        p = tk.Toplevel(self.settings if self.settings_open() else self.root)
        self.capture_popup = p
        p.title("Перне таңдау")
        p.geometry("390x150")
        p.resizable(False, False)
        p.transient(self.settings if self.settings_open() else self.root)
        ttk.Label(p, text=f"{KEY_LABELS[action]} үшін пернені қазір бас", font=("Segoe UI", 13, "bold")).pack(pady=(25, 8))
        ttk.Label(p, text="Мысалы: A, W, Space, Shift, R...").pack()
        ttk.Button(p, text="Бас тарту", command=self.cancel_key_capture).pack(pady=12)
        p.protocol("WM_DELETE_WINDOW", self.cancel_key_capture)
        p.bind("<KeyPress>", self.capture_key_event)
        p.after(80, lambda: (p.lift(), p.focus_force(), p.grab_set()))

    def capture_key_event(self, e):
        if not self.capture_action:
            return "break"
        key = norm_key(e.keysym)
        if key in ("", "esc"):
            if key == "esc":
                self.cancel_key_capture()
            return "break"
        action = self.capture_action
        self.assign_key(action, key)
        self.cancel_key_capture(clear_action=False)
        return "break"

    def cancel_key_capture(self, clear_action=True):
        try:
            if self.capture_popup is not None:
                try:
                    self.capture_popup.grab_release()
                except Exception:
                    pass
                self.capture_popup.destroy()
        except Exception:
            pass
        self.capture_popup = None
        if clear_action:
            self.capture_action = None

    def assign_key(self, action, key):
        keys = self.profile.setdefault("keys", DEFAULT_KEYS.copy())
        for a in KEY_ACTIONS:
            if a != action and keys.get(a) == key:
                keys[a] = ""
        keys[action] = key
        self.profile["mapping_enabled"] = True
        if hasattr(self, "mapping_var"):
            try:
                self.mapping_var.set(True)
            except Exception:
                pass
        self.capture_action = None
        self.refresh_key_vars()
        self.save_profile(quiet=True)
        self.status.set(f"{KEY_LABELS[action]} = {self.pretty_key(key)} сақталды")
        self.update_mode_ui()

    def mapping_changed(self):
        self.profile["mapping_enabled"] = bool(self.mapping_var.get())
        if not self.profile["mapping_enabled"]:
            self.pressed.clear()
        self.save_profile(quiet=True)
        self.update_mode_ui()

    def start_point_pick(self, action):
        self.bind_mode = action
        self.status.set(f"{LABELS[action]} орнын телефон экранынан бас")
        self.close_settings()
        self.redraw()

    def auto_cam_changed(self):
        self.profile["auto_camera_turn"] = bool(self.auto_cam_var.get())
        self.save_profile(quiet=True)

    def camera_sens_changed(self, _=None):
        self.profile["camera_sensitivity"] = float(self.cam_sens_var.get())
        self.save_profile(quiet=True)

    def radius_changed(self, _=None):
        self.profile["joystick_radius"] = float(self.radius_var.get())
        self.save_profile(quiet=True)

    def in_gear(self, x, y):
        x1, y1, x2, y2 = self.gear_rect
        return x1 <= x <= x2 and y1 <= y <= y2

    def on_touchpad_down(self, e):
        if self.in_gear(e.x, e.y):
            self.touch_start = None
            self.touch_last = None
            self.open_settings()
            return "break"
        if self.settings_open() or self.capture_open():
            return "break"
        n = self.canvas_to_normalized(e.x, e.y)
        if n:
            self.touch_start = (n, time.time())
            self.touch_last = n

    def on_touchpad_move(self, e):
        if self.settings_open() or self.capture_open() or not self.touch_start:
            return
        n = self.canvas_to_normalized(e.x, e.y)
        if n:
            self.touch_last = n

    def on_touchpad_up(self, e):
        if self.in_gear(e.x, e.y):
            self.touch_start = None
            self.touch_last = None
            return "break"
        if self.settings_open() or self.capture_open():
            self.touch_start = None
            self.touch_last = None
            return "break"
        end = self.canvas_to_normalized(e.x, e.y) or self.touch_last
        start_info = self.touch_start
        self.touch_start = None
        self.touch_last = None
        if not end or not start_info:
            return
        if self.bind_mode:
            self.profile[self.bind_mode] = [end[0], end[1]]
            self.status.set(f"{LABELS[self.bind_mode]} орны сақталды")
            self.bind_mode = None
            self.save_profile(quiet=True)
            self.redraw()
            return
        start, t0 = start_info
        dx, dy = end[0] - start[0], end[1] - start[1]
        dist = math.hypot(dx, dy)
        if dist > 0.010:
            dur = max(90, min(700, int((time.time() - t0) * 1000)))
            self.send(f"SWIPE {start[0]:.5f} {start[1]:.5f} {end[0]:.5f} {end[1]:.5f} {dur}")
        else:
            self.send(f"TAP {end[0]:.5f} {end[1]:.5f}")

    def on_touchpad_right(self, e):
        if self.settings_open() or self.capture_open():
            return "break"
        n = self.canvas_to_normalized(e.x, e.y)
        if n:
            self.send(f"TAP {n[0]:.5f} {n[1]:.5f}")

    def on_touchpad_scroll(self, e):
        if self.settings_open() or self.capture_open():
            return "break"
        c = self.canvas_to_normalized(e.x, e.y)
        if not c:
            return
        direction = -1 if e.delta > 0 else 1
        self.send_scroll(c, direction)

    def on_touchpad_scroll_linux(self, e, direction):
        if self.settings_open() or self.capture_open():
            return "break"
        c = self.canvas_to_normalized(e.x, e.y)
        if c:
            self.send_scroll(c, direction)

    def send_scroll(self, c, direction):
        amount = 0.23 * direction
        y2 = max(0.05, min(0.95, c[1] + amount))
        self.send(f"SWIPE {c[0]:.5f} {c[1]:.5f} {c[0]:.5f} {y2:.5f} 170")

    def key_down(self, e):
        if self.capture_open() or self.settings_open():
            return
        k = norm_key(e.keysym)
        if not k or not self.connected or not bool(self.profile.get("mapping_enabled", True)):
            return
        if k in self.pressed:
            return
        self.pressed.add(k)
        action = self.action_for_key(k)
        if action in ("run", "jump", "fire", "aim", "reload", "interact"):
            self.tap_action(action)

    def key_up(self, e):
        self.pressed.discard(norm_key(e.keysym))

    def action_for_key(self, key):
        for action, bound in self.profile.get("keys", {}).items():
            if bound == key:
                return action
        return None

    def key_active(self, action):
        k = self.profile.get("keys", {}).get(action, "")
        return bool(k and k in self.pressed)

    def tap_action(self, name):
        p = self.profile.get(name)
        if p:
            self.send(f"TAP {p[0]:.5f} {p[1]:.5f}")

    def movement_loop(self):
        while self.running:
            try:
                mapping = bool(self.profile.get("mapping_enabled", True))
                dx = (1 if self.key_active("move_right") else 0) - (1 if self.key_active("move_left") else 0)
                dy = (1 if self.key_active("move_down") else 0) - (1 if self.key_active("move_up") else 0)
                if self.connected and mapping and not self.settings_open() and (dx or dy):
                    mag = math.hypot(dx, dy)
                    dxn, dyn = dx / mag, dy / mag
                    joy = self.profile.get("joystick", [0.18, 0.73])
                    r = float(self.profile.get("joystick_radius", 0.10))
                    jx = max(0.01, min(0.99, joy[0] + dxn * r))
                    jy = max(0.01, min(0.99, joy[1] + dyn * r))
                    auto = bool(self.profile.get("auto_camera_turn", True))
                    cam = self.profile.get("camera", [0.72, 0.50])
                    if auto and dx != 0 and cam:
                        sens = float(self.profile.get("camera_sensitivity", 0.09))
                        cx2 = max(0.03, min(0.97, cam[0] - (1 if dx > 0 else -1) * sens))
                        self.send(f"DUALSWIPE {joy[0]:.5f} {joy[1]:.5f} {jx:.5f} {jy:.5f} {cam[0]:.5f} {cam[1]:.5f} {cx2:.5f} {cam[1]:.5f} 190")
                    else:
                        self.send(f"SWIPE {joy[0]:.5f} {joy[1]:.5f} {jx:.5f} {jy:.5f} 190")
                    time.sleep(0.17)
                else:
                    time.sleep(0.035)
            except Exception:
                time.sleep(0.1)

    def toggle_connect(self):
        if self.connected:
            self.disconnect()
            return
        ip = self.ip.get().strip()
        pin = self.pin.get().strip()
        if not ip or len(pin) != 6 or not pin.isdigit():
            messagebox.showwarning(APP, "Телефон IP және 6 санды PIN енгіз.")
            return
        self.status.set("Қосылып жатыр...")
        threading.Thread(target=self.connect_worker, args=(ip, pin), daemon=True).start()

    def connect_worker(self, ip, pin):
        try:
            vs = socket.create_connection((ip, 5050), timeout=5)
            vs.settimeout(None)
            vs.sendall(f"PIN {pin}\n".encode())
            cs = socket.create_connection((ip, 5051), timeout=5)
            cs.settimeout(None)
            cs.sendall(f"PIN {pin}\n".encode())
            self.video_sock, self.ctrl_sock = vs, cs
            self.connected = True
            self.root.after(0, lambda: (self.status.set("Қосылды"), self.btn_connect.config(text="Ажырату"), self.update_mode_ui()))
            threading.Thread(target=self.control_status_loop, args=(cs,), daemon=True).start()
            self.video_loop(vs)
        except Exception as ex:
            self.root.after(0, lambda e=str(ex): self.status.set("Қате: " + e))
            self.disconnect(silent=True)

    def control_status_loop(self, s):
        try:
            f = s.makefile("r", encoding="utf-8", newline="\n")
            while self.connected:
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith("APP "):
                    pkg = line[4:].strip()
                    self.foreground_package = pkg
                    active = self.is_game_package(pkg)
                    if active != self.game_mode:
                        self.game_mode = active
                        self.root.after(0, self.update_mode_ui)
        except Exception:
            pass

    def is_game_package(self, pkg):
        p = (pkg or "").lower()
        return "freefire" in p or p in ("com.dts.freefireth", "com.dts.freefiremax")

    def update_mode_ui(self):
        enabled = bool(self.profile.get("mapping_enabled", True))
        if enabled:
            self.mode.set("⌨ KEYMAP ON" + (" · Free Fire" if self.game_mode else ""))
        else:
            self.mode.set("⌨ KEYMAP OFF")
        if self.connected:
            if enabled:
                self.status.set("Touchpad + перне mapping жұмыс істейді")
            else:
                self.status.set("Touchpad жұмыс істейді, перне mapping өшірулі")
        self.redraw()

    def recv_exact(self, s, n):
        out = bytearray()
        while len(out) < n:
            b = s.recv(n - len(out))
            if not b:
                raise ConnectionError("Байланыс үзілді")
            out.extend(b)
        return bytes(out)

    def video_loop(self, s):
        try:
            while self.connected:
                size = struct.unpack(">I", self.recv_exact(s, 4))[0]
                if size <= 0 or size > 10000000:
                    raise ValueError("Bad frame")
                img = Image.open(io.BytesIO(self.recv_exact(s, size))).convert("RGB")
                if self.frames.full():
                    try:
                        self.frames.get_nowait()
                    except queue.Empty:
                        pass
                self.frames.put(img)
        except Exception as ex:
            if self.connected:
                self.root.after(0, lambda e=str(ex): self.status.set("Видео тоқтады: " + e))
        finally:
            self.disconnect(silent=True)

    def disconnect(self, silent=False):
        self.connected = False
        self.game_mode = False
        self.pressed.clear()
        for s in (self.video_sock, self.ctrl_sock):
            try:
                if s:
                    s.close()
            except Exception:
                pass
        self.video_sock = self.ctrl_sock = None
        try:
            self.root.after(0, self.update_mode_ui)
            self.btn_connect.config(text="Қосылу")
        except Exception:
            pass
        if not silent:
            self.status.set("Қосылмаған")

    def send(self, command):
        s = self.ctrl_sock
        if not self.connected or not s:
            return
        try:
            s.sendall((command + "\n").encode())
        except Exception:
            self.disconnect()

    def ui_tick(self):
        try:
            while True:
                self.current_image = self.frames.get_nowait()
        except queue.Empty:
            pass
        if self.current_image is not None:
            self.redraw()
        else:
            self.draw_empty()
        self.root.after(40, self.ui_tick)

    def draw_empty(self):
        cw = max(2, self.canvas.winfo_width())
        ch = max(2, self.canvas.winfo_height())
        self.canvas.delete("all")
        self.canvas.create_text(cw / 2, ch / 2, text="Телефонға қосылғаннан кейін экран осында шығады", fill="white", font=("Segoe UI", 16))
        self.draw_gear(cw - 54, 12)

    def draw_gear(self, gx, gy):
        self.gear_rect = (gx, gy, gx + 42, gy + 42)
        self.canvas.create_rectangle(gx, gy, gx + 42, gy + 42, fill="#20242a", outline="white", width=1)
        self.canvas.create_text(gx + 21, gy + 21, text="⚙", fill="white", font=("Segoe UI Symbol", 19))

    def redraw(self):
        if self.current_image is None:
            return
        cw = max(2, self.canvas.winfo_width())
        ch = max(2, self.canvas.winfo_height())
        iw, ih = self.current_image.size
        scale = min(cw / iw, ch / ih)
        rw, rh = max(1, int(iw * scale)), max(1, int(ih * scale))
        x, y = (cw - rw) // 2, (ch - rh) // 2
        disp = self.current_image.resize((rw, rh), Image.Resampling.BILINEAR)
        self.current_photo = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.create_image(x, y, anchor="nw", image=self.current_photo)
        self.img_rect = (x, y, rw, rh)
        self.draw_gear(x + rw - 52, y + 10)
        if self.bind_mode:
            for a in TOUCH_ACTIONS:
                p = self.profile.get(a)
                if not p:
                    continue
                px, py = x + p[0] * rw, y + p[1] * rh
                self.canvas.create_oval(px - 7, py - 7, px + 7, py + 7, outline="white", width=2)
                self.canvas.create_text(px + 10, py - 10, text=LABELS[a], anchor="sw", fill="white")

    def canvas_to_normalized(self, x, y):
        ix, iy, rw, rh = self.img_rect
        if x < ix or y < iy or x > ix + rw or y > iy + rh:
            return None
        return ((x - ix) / rw, (y - iy) / rh)

    def close(self):
        self.running = False
        self.disconnect(silent=True)
        self.cancel_key_capture()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
