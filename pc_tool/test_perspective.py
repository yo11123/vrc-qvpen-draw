"""
VRC パースペクティブ プレビュー
QVPenボードの描画がVRC内カメラからどう見えるかをシミュレーション。
左: ボード正面図（実際の描画）  右: カメラから見た表示（パースペクティブ）

カメラ距離・高さ・FOV・レンズ歪みをスライダーで調整して
VRC内の見え方を再現できる。
"""

import math
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path


class PerspectivePreview:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("VRC パースペクティブ プレビュー")
        self.root.geometry("1400x750")
        self.root.configure(bg='#1a1a2e')

        self.strokes = []
        self.bounds = None
        self._redraw_job = None

        self._build_ui()

    # ================================================================
    #  UI
    # ================================================================
    def _build_ui(self):
        style = ttk.Style()
        style.theme_use('default')
        bg = '#1a1a2e'
        fg = '#e0e0e0'
        style.configure('TLabel', background=bg, foreground=fg, font=('', 10))
        style.configure('H.TLabel', background=bg, foreground=fg, font=('', 11, 'bold'))
        style.configure('TFrame', background=bg)
        style.configure('TButton', font=('', 10))
        style.configure('TCheckbutton', background=bg, foreground=fg)

        # --- ファイル ---
        top = ttk.Frame(self.root)
        top.pack(fill='x', padx=10, pady=(8, 4))
        ttk.Button(top, text="JSON読み込み", command=self._load_json).pack(side='left')
        self.file_label = ttk.Label(top, text="  ファイル未選択", foreground='#888')
        self.file_label.pack(side='left', padx=8)

        # --- パラメータ ---
        params = ttk.Frame(self.root)
        params.pack(fill='x', padx=10, pady=4)

        self.dist_var = tk.DoubleVar(value=3.0)
        self.height_var = tk.DoubleVar(value=-0.3)
        self.fov_var = tk.DoubleVar(value=60.0)
        self.distort_var = tk.DoubleVar(value=0.0)

        self._sliders = []
        for label, var, lo, hi, fmt in [
            ("カメラ距離:", self.dist_var, 0.5, 8.0, "{:.1f}"),
            ("カメラ高さ:", self.height_var, -2.0, 2.0, "{:.2f}"),
            ("FOV:", self.fov_var, 20.0, 120.0, "{:.0f}"),
            ("レンズ歪み:", self.distort_var, -1.0, 1.0, "{:.2f}"),
        ]:
            ttk.Label(params, text=label).pack(side='left')
            sc = ttk.Scale(params, from_=lo, to=hi, variable=var,
                           orient='horizontal', length=100)
            sc.pack(side='left', padx=2)
            lbl = ttk.Label(params, text=fmt.format(var.get()), width=5)
            lbl.pack(side='left')
            ttk.Label(params, text="  ").pack(side='left')
            sc.configure(command=lambda v, l=lbl, va=var, f=fmt: self._on_slider(l, va, f))
            self._sliders.append((sc, lbl, var, fmt))

        self.grid_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(params, text="グリッド", variable=self.grid_var,
                        command=self._schedule_redraw).pack(side='left', padx=8)

        # --- キャンバス ---
        cf = ttk.Frame(self.root)
        cf.pack(fill='both', expand=True, padx=10, pady=(0, 8))

        left = ttk.Frame(cf)
        left.pack(side='left', fill='both', expand=True, padx=(0, 4))
        ttk.Label(left, text="ボード正面図（実際の描画）", style='H.TLabel').pack()
        self.flat_cv = tk.Canvas(left, bg='#fff', highlightthickness=1,
                                 highlightbackground='#555')
        self.flat_cv.pack(fill='both', expand=True, pady=4)

        right = ttk.Frame(cf)
        right.pack(side='right', fill='both', expand=True, padx=(4, 0))
        ttk.Label(right, text="VRCカメラ視点（パースペクティブ）", style='H.TLabel').pack()
        self.persp_cv = tk.Canvas(right, bg='#fff', highlightthickness=1,
                                  highlightbackground='#555')
        self.persp_cv.pack(fill='both', expand=True, pady=4)

        self.root.bind('<Configure>', lambda e: self._schedule_redraw())

    # ================================================================
    #  イベント
    # ================================================================
    def _on_slider(self, lbl, var, fmt):
        lbl.configure(text=fmt.format(var.get()))
        self._schedule_redraw()

    def _schedule_redraw(self):
        if self._redraw_job:
            self.root.after_cancel(self._redraw_job)
        self._redraw_job = self.root.after(30, self._redraw)

    def _load_json(self):
        path = filedialog.askopenfilename(
            title="描画データを選択",
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.strokes = data['strokes']
            self._calc_bounds()
            self.file_label.configure(
                text=f"  {Path(path).name}  |  {len(self.strokes)} strokes")
            self._schedule_redraw()
        except Exception as e:
            messagebox.showerror("エラー", str(e))

    def _calc_bounds(self):
        xs = [p['x'] for s in self.strokes for p in s['points']]
        ys = [p['y'] for s in self.strokes for p in s['points']]
        self.bounds = (min(xs), min(ys), max(xs), max(ys))

    # ================================================================
    #  描画
    # ================================================================
    def _redraw(self):
        self._redraw_job = None
        self._draw_flat()
        self._draw_perspective()

    # ---------- 正面図 ----------
    def _draw_flat(self):
        c = self.flat_cv
        c.delete('all')
        cw, ch = c.winfo_width(), c.winfo_height()
        if cw < 20 or ch < 20:
            return
        if not self.strokes:
            c.create_text(cw // 2, ch // 2, text="JSONを読み込んでください", fill='#999')
            return

        min_x, min_y, max_x, max_y = self.bounds
        sw, sh = max_x - min_x, max_y - min_y
        if sw == 0 or sh == 0:
            return

        pad = 30
        scale = min((cw - 2 * pad) / sw, (ch - 2 * pad) / sh)
        ox = pad + ((cw - 2 * pad) - sw * scale) / 2
        oy = pad + ((ch - 2 * pad) - sh * scale) / 2

        # ボード枠
        c.create_rectangle(ox, oy, ox + sw * scale, oy + sh * scale,
                           outline='#ccc', width=1)

        # グリッド
        if self.grid_var.get():
            for i in range(1, 8):
                t = i / 8
                c.create_line(ox + t * sw * scale, oy,
                              ox + t * sw * scale, oy + sh * scale, fill='#eee')
                c.create_line(ox, oy + t * sh * scale,
                              ox + sw * scale, oy + t * sh * scale, fill='#eee')

        # ストローク
        for stroke in self.strokes:
            pts = stroke['points']
            if len(pts) < 2:
                continue
            coords = []
            for p in pts:
                coords.append(ox + (p['x'] - min_x) * scale)
                coords.append(oy + (p['y'] - min_y) * scale)
            c.create_line(coords, fill='#000', width=2,
                          capstyle='round', joinstyle='round', smooth=True)

    # ---------- パースペクティブ ----------
    def _make_projector(self):
        """現在のカメラ設定で 3D→2D 投影関数を生成"""
        cam_d = self.dist_var.get()
        cam_h = self.height_var.get()
        fov_rad = math.radians(self.fov_var.get())
        focal = 1.0 / math.tan(fov_rad / 2)
        distort_k = self.distort_var.get()

        fwd_len = math.sqrt(cam_h ** 2 + cam_d ** 2)
        if fwd_len < 0.001:
            return None

        # カメラ基底ベクトル (カメラ → 原点 方向)
        fx, fy, fz = 0, -cam_h / fwd_len, cam_d / fwd_len
        rx, ry, rz = 1.0, 0.0, 0.0
        ux = ry * fz - rz * fy
        uy = rz * fx - rx * fz
        uz = rx * fy - ry * fx

        min_x, min_y, max_x, max_y = self.bounds
        sw, sh = max_x - min_x, max_y - min_y
        bscale = 1.0 / max(sw, sh)
        cx, cy = min_x + sw / 2, min_y + sh / 2

        def project(bx, by):
            # ボード座標 → 3Dワールド座標 (中央原点, Y反転)
            wx = (bx - cx) * bscale
            wy = -(by - cy) * bscale

            # カメラ空間
            dx, dy, dz = wx, wy - cam_h, cam_d
            vx = dx * rx + dy * ry + dz * rz
            vy = dx * ux + dy * uy + dz * uz
            vz = dx * fx + dy * fy + dz * fz
            if vz <= 0.001:
                return None

            sx = vx / vz * focal
            sy = -vy / vz * focal

            # バレル / ピンクッション歪み
            if distort_k != 0:
                r2 = sx * sx + sy * sy
                factor = 1.0 + distort_k * r2
                sx *= factor
                sy *= factor

            return sx, sy

        return project

    def _draw_perspective(self):
        c = self.persp_cv
        c.delete('all')
        cw, ch = c.winfo_width(), c.winfo_height()
        if cw < 20 or ch < 20:
            return
        if not self.strokes:
            c.create_text(cw // 2, ch // 2, text="JSONを読み込んでください", fill='#999')
            return

        project = self._make_projector()
        if not project:
            return

        min_x, min_y, max_x, max_y = self.bounds
        sw, sh = max_x - min_x, max_y - min_y

        # --- 全ポイント + ボード四隅を投影してスクリーン範囲を得る ---
        all_pts = []
        corner_proj = []
        for bx, by in [(min_x, min_y), (max_x, min_y),
                        (max_x, max_y), (min_x, max_y)]:
            r = project(bx, by)
            if r:
                all_pts.append(r)
                corner_proj.append(r)

        proj_strokes = []
        for stroke in self.strokes:
            ps = []
            for p in stroke['points']:
                r = project(p['x'], p['y'])
                if r:
                    ps.append(r)
                    all_pts.append(r)
            proj_strokes.append(ps)

        if len(all_pts) < 2:
            return

        pmin_x = min(p[0] for p in all_pts)
        pmax_x = max(p[0] for p in all_pts)
        pmin_y = min(p[1] for p in all_pts)
        pmax_y = max(p[1] for p in all_pts)
        pw, ph = pmax_x - pmin_x, pmax_y - pmin_y
        if pw == 0 or ph == 0:
            return

        pad = 30
        pscale = min((cw - 2 * pad) / pw, (ch - 2 * pad) / ph)
        pox = pad + ((cw - 2 * pad) - pw * pscale) / 2
        poy = pad + ((ch - 2 * pad) - ph * pscale) / 2

        def to_scr(px, py):
            return pox + (px - pmin_x) * pscale, poy + (py - pmin_y) * pscale

        # ボード枠 (パースペクティブだと台形になる)
        if len(corner_proj) == 4:
            border = []
            for cp in corner_proj + [corner_proj[0]]:
                border.extend(to_scr(*cp))
            c.create_line(border, fill='#ccc', width=1)

        # グリッド
        if self.grid_var.get():
            steps = 30  # 曲線を滑らかにするための分割数
            for i in range(1, 8):
                t = i / 8
                # 水平線
                pts = []
                by = min_y + t * sh
                for j in range(steps):
                    bx = min_x + (j / (steps - 1)) * sw
                    r = project(bx, by)
                    if r:
                        pts.extend(to_scr(*r))
                if len(pts) >= 4:
                    c.create_line(pts, fill='#eee', width=1, smooth=True)
                # 垂直線
                pts = []
                bx = min_x + t * sw
                for j in range(steps):
                    by2 = min_y + (j / (steps - 1)) * sh
                    r = project(bx, by2)
                    if r:
                        pts.extend(to_scr(*r))
                if len(pts) >= 4:
                    c.create_line(pts, fill='#eee', width=1, smooth=True)

        # ストローク
        for ps in proj_strokes:
            if len(ps) < 2:
                continue
            coords = []
            for px, py in ps:
                coords.extend(to_scr(px, py))
            c.create_line(coords, fill='#000', width=2,
                          capstyle='round', joinstyle='round', smooth=True)

    # ================================================================
    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = PerspectivePreview()
    app.run()
