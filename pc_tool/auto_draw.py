"""
VRC QVPen 自動描画ツール
JSONデータを読み込み、VRChatのQVPenでマウス操作を自動化して描画する。

使い方:
1. VRChatデスクトップモードでQVPenを持った状態にする
2. このツールを起動し、JSONファイルを読み込む
3. 描画エリアとパラメータを設定
4. 「描画開始」を押す（カウントダウン後に自動描画が始まる）
5. 緊急停止: マウスを画面の左上隅に移動 or Escキー
"""

import json
import time
import threading
import ctypes
import ctypes.wintypes
import tkinter as tk

# DPIスケーリング対応
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

try:
    from pynput import keyboard as pynput_kb
except ImportError:
    print("pynputが必要です: pip install pynput")
    exit(1)

# ============================================================
#  Windows SendInput API — ゲーム(VRChat)に確実に入力を届ける
# ============================================================
user32 = ctypes.windll.user32

# --- 定数 ---
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002

# Tab のスキャンコード
SCAN_TAB = 0x0F

# --- 構造体 (dwExtraInfo を c_size_t に修正) ---
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]

class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTunion)]

def _send_inputs(*inputs):
    """複数のINPUTを一括送信"""
    arr = (INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))

# --- マウス操作 ---
def mouse_move(x, y):
    """絶対座標でマウスを移動 (SendInputで移動イベントを生成)"""
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi.dx = int(x * 65536 / sw) + 1
    inp.u.mi.dy = int(y * 65536 / sh) + 1
    inp.u.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    _send_inputs(inp)

def mouse_down():
    """左クリック押下"""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    _send_inputs(inp)

def mouse_up():
    """左クリック解放"""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi.dwFlags = MOUSEEVENTF_LEFTUP
    _send_inputs(inp)

def mouse_move_and_down(x, y):
    """絶対座標でマウスを移動しつつ左クリック押下（原子的操作で座標ズレを防ぐ）"""
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi.dx = int(x * 65536 / sw) + 1
    inp.u.mi.dy = int(y * 65536 / sh) + 1
    inp.u.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTDOWN
    _send_inputs(inp)

def key_down_tab():
    """Tabキー押下 (スキャンコード)"""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki.wScan = SCAN_TAB
    inp.u.ki.dwFlags = KEYEVENTF_SCANCODE
    _send_inputs(inp)

def key_up_tab():
    """Tabキー解放 (スキャンコード)"""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki.wScan = SCAN_TAB
    inp.u.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
    _send_inputs(inp)

# FAILSAFEチェック
FAILSAFE_MARGIN = 5
def check_failsafe():
    pos = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pos))
    if pos.x <= FAILSAFE_MARGIN and pos.y <= FAILSAFE_MARGIN:
        raise Exception("緊急停止: マウスが画面左上隅に移動されました")


class DrawingData:
    """JSONデータの読み込みと管理"""

    def __init__(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.version = data.get('version', 1)
        self.canvas_w = data['canvas']['width']
        self.canvas_h = data['canvas']['height']
        self.smoothing = data.get('smoothing', 0)
        self.strokes = data['strokes']

    @property
    def stroke_count(self):
        return len(self.strokes)

    @property
    def total_points(self):
        return sum(len(s['points']) for s in self.strokes)

    def get_bounds(self):
        """描画の実際の範囲を取得"""
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        for s in self.strokes:
            for p in s['points']:
                min_x = min(min_x, p['x'])
                min_y = min(min_y, p['y'])
                max_x = max(max_x, p['x'])
                max_y = max(max_y, p['y'])
        return min_x, min_y, max_x, max_y


class AutoDrawer:
    """VRC上での自動描画エンジン"""

    def __init__(self):
        self.running = False
        self.drawing = False  # カウントダウン後、実際に描画中かどうか
        self.thread = None
        self.progress_callback = None
        self.done_callback = None

    def start(self, drawing_data, config):
        if self.running:
            return
        self.running = True
        self.drawing = False
        self.thread = threading.Thread(
            target=self._draw_loop,
            args=(drawing_data, config),
            daemon=True
        )
        self.thread.start()

    def stop(self):
        self.running = False

    def _draw_loop(self, data, cfg):
        try:
            # カウントダウン
            for i in range(cfg['countdown'], 0, -1):
                if not self.running:
                    return
                if self.progress_callback:
                    self.progress_callback(-1, f"開始まで {i} 秒...")
                time.sleep(1)

            if not self.running:
                return

            # 描画範囲の計算
            bounds = data.get_bounds()
            src_min_x, src_min_y, src_max_x, src_max_y = bounds
            src_w = src_max_x - src_min_x
            src_h = src_max_y - src_min_y

            if src_w == 0 or src_h == 0:
                if self.done_callback:
                    self.done_callback("描画データが不正です")
                return

            # アスペクト比を維持してフィット
            dst_x = cfg['area_x']
            dst_y = cfg['area_y']
            dst_w = cfg['area_w']
            dst_h = cfg['area_h']

            scale_x = dst_w / src_w
            scale_y = dst_h / src_h
            scale = min(scale_x, scale_y)

            # ペン太さ補正: 太いペンでは描画を拡大して線同士の潰れを防ぐ
            # 基準太さ3に対して、太くなるほど描画を拡大して間隔を保つ
            # Tabモードなしなら描画エリアをはみ出しても問題ない
            thickness = cfg.get('thickness', 3)
            thickness_scale = max(1.0, thickness / 3.0)
            scale *= thickness_scale

            # 中央揃えオフセット
            offset_x = dst_x + (dst_w - src_w * scale) / 2
            offset_y = dst_y + (dst_h - src_h * scale) / 2

            # Tab感度補正: VRChatのTabモードはマウス移動量に感度係数をかけるため
            # 画面中央から外側に拡大して送信することで補正する
            tab_sens = cfg.get('tab_sensitivity', 1.0)
            use_tab = cfg.get('use_tab', True)
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            screen_cx = sw / 2
            screen_cy = sh / 2

            def map_point(px, py):
                sx = offset_x + (px - src_min_x) * scale
                sy = offset_y + (py - src_min_y) * scale
                # Tabモードの感度補正 (画面中央を基準に拡大)
                if use_tab and tab_sens < 1.0:
                    sx = screen_cx + (sx - screen_cx) / tab_sens
                    sy = screen_cy + (sy - screen_cy) / tab_sens
                return int(sx), int(sy)

            total = data.stroke_count
            speed = cfg['speed']  # 1-10, 10が最速
            base_delay = 0.02 / (speed / 5.0)
            stroke_delay = cfg['stroke_delay']

            # QVPenはダブルクリックで消しゴムモードになるため
            # mouseUp→次のmouseDown間に最低600ms空ける
            DOUBLE_CLICK_GUARD = 0.6

            # 描画開始フラグ — ここからキー停止が有効になる
            self.drawing = True

            # Tabキーを押す (SendInput + スキャンコード)
            if cfg.get('use_tab', True):
                key_down_tab()
                time.sleep(1.0)

                # プライミング: VRChatのカーソル位置を同期させる
                if data.strokes and len(data.strokes[0]['points']) > 0:
                    p0 = data.strokes[0]['points'][0]
                    prime_x, prime_y = map_point(p0['x'], p0['y'])
                    mouse_move(prime_x, prime_y)
                    time.sleep(0.5)

            for idx, stroke in enumerate(data.strokes):
                if not self.running:
                    break

                check_failsafe()

                if self.progress_callback:
                    self.progress_callback(
                        (idx + 1) / total,
                        f"ストローク {idx + 1}/{total}"
                    )

                points = stroke['points']
                if len(points) < 2:
                    continue

                # 最初の点に移動 — ダブルムーブで確実にVRCカーソルを同期
                sx, sy = map_point(points[0]['x'], points[0]['y'])
                tab_sync = cfg.get('tab_sync_delay', 0.15)
                mouse_move(sx, sy)
                time.sleep(tab_sync)
                mouse_move(sx, sy)  # 同じ位置に再送信して確実に同期
                time.sleep(tab_sync)

                # マウスダウン (位置確定後にクリック)
                mouse_down()
                time.sleep(0.05)

                for i in range(1, len(points)):
                    if not self.running:
                        mouse_up()
                        break

                    px, py = map_point(points[i]['x'], points[i]['y'])
                    mouse_move(px, py)
                    time.sleep(base_delay)

                mouse_up()

                # ストローク間の待機
                # ダブルクリック判定回避: 最低 DOUBLE_CLICK_GUARD 秒空ける
                wait = max(stroke_delay, DOUBLE_CLICK_GUARD)
                if idx < total - 1:
                    time.sleep(wait)

            # Tabキーを離す
            if cfg.get('use_tab', True):
                key_up_tab()

            if self.done_callback:
                self.done_callback(None)

        except Exception as e:
            if cfg.get('use_tab', True):
                try:
                    key_up_tab()
                except:
                    pass
            try:
                mouse_up()
            except:
                pass
            if self.done_callback:
                self.done_callback(str(e))
        finally:
            self.drawing = False
            self.running = False


class App:
    """GUI アプリケーション"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("VRC QVPen 自動描画ツール")
        self.root.geometry("520x700")
        self.root.resizable(False, False)
        self.root.configure(bg='#1a1a2e')

        self.drawing_data = None
        self.drawer = AutoDrawer()
        self.drawer.progress_callback = self._on_progress
        self.drawer.done_callback = self._on_done

        # Escキーで停止
        self.esc_listener = None
        self._setup_esc_listener()

        self._build_ui()

    def _setup_esc_listener(self):
        # プログラムが送信するキー（Tab）は無視する
        IGNORE_KEYS = {pynput_kb.Key.tab}

        def on_press(key):
            # 実際の描画中のみ、かつプログラムが送るキー以外で停止
            if self.drawer.drawing and key not in IGNORE_KEYS:
                self.drawer.stop()
                try:
                    mouse_up()
                except:
                    pass
                try:
                    key_up_tab()
                except:
                    pass
                self.root.after(0, lambda: self._stop_draw())
        self.esc_listener = pynput_kb.Listener(on_press=on_press)
        self.esc_listener.daemon = True
        self.esc_listener.start()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use('default')
        style.configure('TLabel', background='#1a1a2e', foreground='#e0e0e0', font=('', 10))
        style.configure('Header.TLabel', font=('', 12, 'bold'))
        style.configure('TFrame', background='#1a1a2e')
        style.configure('TLabelframe', background='#16213e', foreground='#e0e0e0')
        style.configure('TLabelframe.Label', background='#1a1a2e', foreground='#e0e0e0')
        style.configure('TButton', font=('', 10))
        style.configure('Start.TButton', font=('', 12, 'bold'))

        main = ttk.Frame(self.root, padding=12)
        main.pack(fill='both', expand=True)

        # === ファイル選択 ===
        file_frame = ttk.Frame(main)
        file_frame.pack(fill='x', pady=(0, 8))

        ttk.Label(file_frame, text="描画データ (JSON)", style='Header.TLabel').pack(anchor='w')

        row = ttk.Frame(file_frame)
        row.pack(fill='x', pady=4)
        self.file_var = tk.StringVar(value="ファイル未選択")
        ttk.Label(row, textvariable=self.file_var, width=40).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text="開く", command=self._load_file).pack(side='right', padx=(8, 0))

        self.file_info_var = tk.StringVar(value="")
        ttk.Label(file_frame, textvariable=self.file_info_var, foreground='#888').pack(anchor='w')

        # === プレビュー ===
        ttk.Label(main, text="プレビュー", style='Header.TLabel').pack(anchor='w', pady=(8, 4))
        self.preview_canvas = tk.Canvas(main, width=490, height=200, bg='#ffffff', highlightthickness=1, highlightbackground='#333')
        self.preview_canvas.pack()

        # === 描画設定 ===
        ttk.Label(main, text="描画設定", style='Header.TLabel').pack(anchor='w', pady=(12, 4))

        settings = ttk.Frame(main)
        settings.pack(fill='x')

        # 描画エリア
        area_frame = ttk.Frame(settings)
        area_frame.pack(fill='x', pady=2)
        ttk.Label(area_frame, text="描画エリア (px):").pack(side='left')

        self.area_x = tk.IntVar(value=400)
        self.area_y = tk.IntVar(value=200)
        self.area_w = tk.IntVar(value=600)
        self.area_h = tk.IntVar(value=500)

        for label, var in [("X:", self.area_x), ("Y:", self.area_y),
                           ("W:", self.area_w), ("H:", self.area_h)]:
            ttk.Label(area_frame, text=label).pack(side='left', padx=(8, 0))
            e = ttk.Entry(area_frame, textvariable=var, width=5)
            e.pack(side='left', padx=(2, 0))

        # エリア取得ボタン
        area_btn_frame = ttk.Frame(settings)
        area_btn_frame.pack(fill='x', pady=4)
        ttk.Button(area_btn_frame, text="枠で範囲指定", command=self._pick_area).pack(side='left')
        ttk.Label(area_btn_frame, text="(赤枠をドラッグ/リサイズして確定)", foreground='#888').pack(side='left', padx=8)

        # 速度
        speed_frame = ttk.Frame(settings)
        speed_frame.pack(fill='x', pady=4)
        ttk.Label(speed_frame, text="描画速度:").pack(side='left')
        self.speed_var = tk.IntVar(value=5)
        self.speed_scale = ttk.Scale(speed_frame, from_=1, to=10, variable=self.speed_var, orient='horizontal', length=200)
        self.speed_scale.pack(side='left', padx=8)
        self.speed_label = ttk.Label(speed_frame, text="5")
        self.speed_label.pack(side='left')
        self.speed_scale.configure(command=lambda v: self.speed_label.configure(text=str(int(float(v)))))

        # ストローク間隔
        delay_frame = ttk.Frame(settings)
        delay_frame.pack(fill='x', pady=4)
        ttk.Label(delay_frame, text="ストローク間隔 (秒):").pack(side='left')
        self.delay_var = tk.DoubleVar(value=0.15)
        ttk.Entry(delay_frame, textvariable=self.delay_var, width=6).pack(side='left', padx=8)

        # ペン太さ
        thick_frame = ttk.Frame(settings)
        thick_frame.pack(fill='x', pady=4)
        ttk.Label(thick_frame, text="QVPenの太さ:").pack(side='left')
        self.thickness_var = tk.IntVar(value=3)
        self.thick_scale = ttk.Scale(thick_frame, from_=1, to=10, variable=self.thickness_var, orient='horizontal', length=200)
        self.thick_scale.pack(side='left', padx=8)
        self.thick_label = ttk.Label(thick_frame, text="3")
        self.thick_label.pack(side='left')
        self.thick_scale.configure(command=lambda v: self.thick_label.configure(text=str(int(float(v)))))

        # カウントダウン
        cd_frame = ttk.Frame(settings)
        cd_frame.pack(fill='x', pady=4)
        ttk.Label(cd_frame, text="カウントダウン (秒):").pack(side='left')
        self.countdown_var = tk.IntVar(value=5)
        ttk.Entry(cd_frame, textvariable=self.countdown_var, width=4).pack(side='left', padx=8)

        # Tabモード
        tab_frame = ttk.Frame(settings)
        tab_frame.pack(fill='x', pady=4)
        self.use_tab_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab_frame, text="Tabキーモード（2D平面描画）", variable=self.use_tab_var).pack(side='left')

        # Tab感度
        tab_sens_frame = ttk.Frame(settings)
        tab_sens_frame.pack(fill='x', pady=4)
        ttk.Label(tab_sens_frame, text="Tab感度:").pack(side='left')
        self.tab_sens_var = tk.DoubleVar(value=1.0)
        self.tab_sens_scale = ttk.Scale(tab_sens_frame, from_=0.1, to=1.0, variable=self.tab_sens_var, orient='horizontal', length=200)
        self.tab_sens_scale.pack(side='left', padx=8)
        self.tab_sens_label = ttk.Label(tab_sens_frame, text="1.00")
        self.tab_sens_label.pack(side='left')
        self.tab_sens_scale.configure(command=lambda v: self.tab_sens_label.configure(text=f"{float(v):.2f}"))
        ttk.Label(tab_sens_frame, text="(ずれる場合は下げる)", foreground='#888').pack(side='left', padx=4)

        # === 実行 ===
        exec_frame = ttk.Frame(main)
        exec_frame.pack(fill='x', pady=(16, 4))

        self.start_btn = ttk.Button(exec_frame, text="描画開始", style='Start.TButton', command=self._start_draw)
        self.start_btn.pack(side='left', fill='x', expand=True, ipady=6)
        self.stop_btn = ttk.Button(exec_frame, text="停止", command=self._stop_draw, state='disabled')
        self.stop_btn.pack(side='right', padx=(8, 0), ipady=6)

        # プログレス
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(main, variable=self.progress_var, maximum=1.0, length=490)
        self.progress_bar.pack(fill='x', pady=(4, 0))

        self.status_var = tk.StringVar(value="JSONファイルを読み込んでください")
        ttk.Label(main, textvariable=self.status_var, foreground='#aaa').pack(anchor='w', pady=2)

    def _load_file(self):
        path = filedialog.askopenfilename(
            title="描画データを選択",
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            self.drawing_data = DrawingData(path)
            name = Path(path).name
            self.file_var.set(name)
            self.file_info_var.set(
                f"キャンバス: {self.drawing_data.canvas_w}x{self.drawing_data.canvas_h}  |  "
                f"ストローク: {self.drawing_data.stroke_count}  |  "
                f"ポイント: {self.drawing_data.total_points}"
            )
            self.status_var.set("データ読み込み完了")
            self._draw_preview()
        except Exception as e:
            messagebox.showerror("エラー", f"ファイル読み込み失敗:\n{e}")

    def _draw_preview(self):
        if not self.drawing_data:
            return
        c = self.preview_canvas
        c.delete('all')

        pw = int(c['width'])
        ph = int(c['height'])
        padding = 10

        bounds = self.drawing_data.get_bounds()
        src_min_x, src_min_y, src_max_x, src_max_y = bounds
        src_w = src_max_x - src_min_x
        src_h = src_max_y - src_min_y

        if src_w == 0 or src_h == 0:
            return

        scale = min((pw - 2 * padding) / src_w, (ph - 2 * padding) / src_h)
        off_x = padding + ((pw - 2 * padding) - src_w * scale) / 2
        off_y = padding + ((ph - 2 * padding) - src_h * scale) / 2

        for stroke in self.drawing_data.strokes:
            pts = stroke['points']
            if len(pts) < 2:
                continue
            coords = []
            for p in pts:
                coords.append(off_x + (p['x'] - src_min_x) * scale)
                coords.append(off_y + (p['y'] - src_min_y) * scale)
            w = stroke.get('width', 2)
            preview_w = max(1, w * scale * 0.5)
            c.create_line(coords, fill='#000', width=preview_w, capstyle='round', joinstyle='round', smooth=True)

    def _pick_area(self):
        """半透明のオーバーレイ枠を表示して、ドラッグ/リサイズで範囲指定"""
        overlay = tk.Toplevel(self.root)
        overlay.title("描画エリア指定 — ドラッグで移動、端をドラッグでリサイズ、「確定」で決定")
        overlay.geometry(f"{self.area_w.get()}x{self.area_h.get()}+{self.area_x.get()}+{self.area_y.get()}")
        overlay.attributes('-alpha', 0.35)
        overlay.attributes('-topmost', True)
        overlay.configure(bg='#ff0000')
        overlay.overrideredirect(False)
        overlay.resizable(True, True)

        # 内部フレーム（ドラッグ用＋確定ボタン）
        inner = tk.Frame(overlay, bg='#ff0000')
        inner.pack(fill='both', expand=True)

        info_label = tk.Label(inner, text="この枠を描画したい範囲に合わせてください",
                              bg='#ff0000', fg='#ffffff', font=('', 12, 'bold'))
        info_label.pack(pady=10)

        confirm_btn = tk.Button(inner, text="確定", font=('', 14, 'bold'),
                                bg='#ffffff', fg='#000000', padx=20, pady=5,
                                command=lambda: self._confirm_overlay(overlay))
        confirm_btn.pack(pady=5)

        # ドラッグで移動
        self._drag_x = 0
        self._drag_y = 0

        def start_drag(e):
            self._drag_x = e.x
            self._drag_y = e.y

        def do_drag(e):
            x = overlay.winfo_x() + (e.x - self._drag_x)
            y = overlay.winfo_y() + (e.y - self._drag_y)
            overlay.geometry(f"+{x}+{y}")

        inner.bind('<Button-1>', start_drag)
        inner.bind('<B1-Motion>', do_drag)
        info_label.bind('<Button-1>', start_drag)
        info_label.bind('<B1-Motion>', do_drag)

        self.status_var.set("赤い枠を描画エリアに合わせて「確定」を押してください")

    def _confirm_overlay(self, overlay):
        x = overlay.winfo_x()
        y = overlay.winfo_y()
        w = overlay.winfo_width()
        h = overlay.winfo_height()
        overlay.destroy()
        self._set_area(x, y, w, h)

    def _set_area(self, x, y, w, h):
        self.area_x.set(x)
        self.area_y.set(y)
        self.area_w.set(w)
        self.area_h.set(h)
        self.status_var.set(f"描画エリア設定: ({x}, {y}) {w}x{h}")

    def _start_draw(self):
        if not self.drawing_data:
            messagebox.showwarning("警告", "JSONファイルを先に読み込んでください")
            return

        config = {
            'area_x': self.area_x.get(),
            'area_y': self.area_y.get(),
            'area_w': self.area_w.get(),
            'area_h': self.area_h.get(),
            'speed': self.speed_var.get(),
            'stroke_delay': self.delay_var.get(),
            'thickness': self.thickness_var.get(),
            'countdown': self.countdown_var.get(),
            'use_tab': self.use_tab_var.get(),
            'tab_sync_delay': 0.15,
            'tab_sensitivity': self.tab_sens_var.get(),
        }

        self.start_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self.progress_var.set(0)

        self.drawer.start(self.drawing_data, config)

    def _stop_draw(self):
        self.drawer.stop()
        try:
            mouse_up()
        except:
            pass
        try:
            key_up_tab()
        except:
            pass
        self.start_btn.configure(state='normal')
        self.stop_btn.configure(state='disabled')
        self.status_var.set("停止しました")

    def _on_progress(self, ratio, message):
        def update():
            if ratio >= 0:
                self.progress_var.set(ratio)
            self.status_var.set(message)
        self.root.after(0, update)

    def _on_done(self, error):
        def update():
            self.start_btn.configure(state='normal')
            self.stop_btn.configure(state='disabled')
            if error:
                self.status_var.set(f"エラー: {error}")
                messagebox.showerror("エラー", error)
            else:
                self.progress_var.set(1.0)
                self.status_var.set("描画完了!")
        self.root.after(0, update)

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = App()
    app.run()
