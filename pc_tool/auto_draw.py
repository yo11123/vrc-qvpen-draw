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
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

try:
    import pyautogui
except ImportError:
    print("pyautoguiが必要です: pip install pyautogui")
    exit(1)

try:
    from pynput import keyboard as pynput_kb
except ImportError:
    print("pynputが必要です: pip install pynput")
    exit(1)

# pyautogui設定
pyautogui.FAILSAFE = True  # 左上隅で緊急停止
pyautogui.PAUSE = 0        # デフォルト待機なし


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
        self.paused = False
        self.thread = None
        self.progress_callback = None
        self.done_callback = None

    def start(self, drawing_data, config):
        if self.running:
            return
        self.running = True
        self.paused = False
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

            # ペン太さ補正: 太い→縮小(密度下げ), 細い→そのまま
            thickness_factor = cfg.get('thickness', 3) / 3.0
            point_skip = max(1, int(thickness_factor))

            # 中央揃えオフセット
            offset_x = dst_x + (dst_w - src_w * scale) / 2
            offset_y = dst_y + (dst_h - src_h * scale) / 2

            def map_point(px, py):
                sx = offset_x + (px - src_min_x) * scale
                sy = offset_y + (py - src_min_y) * scale
                return int(sx), int(sy)

            total = data.stroke_count
            speed = cfg['speed']  # 1-10, 10が最速
            base_delay = 0.02 / (speed / 5.0)
            stroke_delay = cfg['stroke_delay']

            # QVPenはダブルクリックで消しゴムモードになるため
            # mouseUp→次のmouseDown間に最低600ms空ける
            DOUBLE_CLICK_GUARD = 0.6

            # Tabキーを押す
            if cfg.get('use_tab', True):
                pyautogui.keyDown('tab')
                time.sleep(0.3)

            for idx, stroke in enumerate(data.strokes):
                if not self.running:
                    break

                if self.progress_callback:
                    self.progress_callback(
                        (idx + 1) / total,
                        f"ストローク {idx + 1}/{total}"
                    )

                points = stroke['points']
                if len(points) < 2:
                    continue

                # 最初の点に移動
                sx, sy = map_point(points[0]['x'], points[0]['y'])
                pyautogui.moveTo(sx, sy)
                time.sleep(0.05)

                # マウスダウン → 描画 → マウスアップ
                pyautogui.mouseDown(button='left')
                time.sleep(0.03)

                for i in range(1, len(points), point_skip):
                    if not self.running:
                        pyautogui.mouseUp(button='left')
                        break

                    px, py = map_point(points[i]['x'], points[i]['y'])
                    pyautogui.moveTo(px, py)
                    time.sleep(base_delay)

                pyautogui.mouseUp(button='left')

                # ストローク間の待機
                # ダブルクリック判定回避: 最低 DOUBLE_CLICK_GUARD 秒空ける
                wait = max(stroke_delay, DOUBLE_CLICK_GUARD)
                if idx < total - 1:
                    time.sleep(wait)

            # Tabキーを離す
            if cfg.get('use_tab', True):
                pyautogui.keyUp('tab')

            if self.done_callback:
                self.done_callback(None)

        except pyautogui.FailSafeException:
            if cfg.get('use_tab', True):
                try:
                    pyautogui.keyUp('tab')
                except:
                    pass
            if self.done_callback:
                self.done_callback("緊急停止しました（マウスが画面隅に移動）")
        except Exception as e:
            if cfg.get('use_tab', True):
                try:
                    pyautogui.keyUp('tab')
                except:
                    pass
            if self.done_callback:
                self.done_callback(str(e))
        finally:
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
        def on_press(key):
            if key == pynput_kb.Key.esc and self.drawer.running:
                self.drawer.stop()
                try:
                    pyautogui.keyUp('tab')
                except:
                    pass
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
        ttk.Button(area_btn_frame, text="クリックで範囲指定", command=self._pick_area).pack(side='left')
        ttk.Label(area_btn_frame, text="(3秒後に左上→右下をクリック)", foreground='#888').pack(side='left', padx=8)

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
        """3秒後にマウス位置2点で描画エリアを指定"""
        self.status_var.set("3秒後に左上をクリック...")
        self.root.update()

        def pick():
            time.sleep(3)

            # 左上を待つ
            import pyautogui
            self.root.after(0, lambda: self.status_var.set("左上をクリックしてください..."))
            while True:
                if pyautogui.mouseDown:
                    pass
                import pynput.mouse as pm
                break

            # 簡易的にpyautoguiでポジション取得
            self.root.after(0, lambda: self.status_var.set("左上の位置でクリック..."))
            pos1 = pyautogui.position()
            time.sleep(0.5)

            # クリック待ち (簡易: 3秒後に現在位置を取得)
            self.root.after(0, lambda: self.status_var.set("3秒以内に左上に移動してクリック..."))
            time.sleep(3)
            p1 = pyautogui.position()

            self.root.after(0, lambda: self.status_var.set("3秒以内に右下に移動してクリック..."))
            time.sleep(3)
            p2 = pyautogui.position()

            x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
            x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])

            self.root.after(0, lambda: self._set_area(x1, y1, x2 - x1, y2 - y1))

        threading.Thread(target=pick, daemon=True).start()

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
        }

        self.start_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self.progress_var.set(0)

        self.drawer.start(self.drawing_data, config)

    def _stop_draw(self):
        self.drawer.stop()
        try:
            pyautogui.keyUp('tab')
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
