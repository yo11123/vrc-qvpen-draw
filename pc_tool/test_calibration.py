"""
VRC Tab モード キャリブレーションツール

VRChat内でQVPenを持ってTabを押した状態で実行。
画面上に十字マーカーと等間隔の目盛り線を描画して、
VRChatの内部カーソルがどの程度ずれているかを可視化する。

使い方:
  1. VRChatでQVPenを持つ
  2. このスクリプトを実行 (カウントダウン後に自動的にTabを押す)
  3. VRChat内に描かれたパターンを観察
  4. 期待位置 vs 実際の位置を比較してズレを測定
"""

import ctypes
import ctypes.wintypes
import time
import sys

# DPI対応
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32

# --- SendInput 定義 (auto_draw.py と同じ) ---
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
SCAN_TAB = 0x0F

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_size_t)]

class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTunion)]

def send(inp):
    arr = (INPUT * 1)(inp)
    user32.SendInput(1, arr, ctypes.sizeof(INPUT))

def mouse_move(x, y):
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi.dx = int(x * 65536 / sw) + 1
    inp.u.mi.dy = int(y * 65536 / sh) + 1
    inp.u.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    send(inp)

def mouse_down():
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
    send(inp)

def mouse_up():
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.u.mi.dwFlags = MOUSEEVENTF_LEFTUP
    send(inp)

def key_tab(down=True):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.u.ki.wScan = SCAN_TAB
    inp.u.ki.dwFlags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
    send(inp)


def draw_line(x1, y1, x2, y2, steps=20):
    """(x1,y1)から(x2,y2)まで線を引く"""
    mouse_move(x1, y1)
    time.sleep(0.15)
    mouse_move(x1, y1)
    time.sleep(0.1)
    mouse_down()
    time.sleep(0.05)
    for i in range(1, steps + 1):
        t = i / steps
        x = x1 + (x2 - x1) * t
        y = y1 + (y2 - y1) * t
        mouse_move(int(x), int(y))
        time.sleep(0.01)
    mouse_up()
    time.sleep(0.7)  # ダブルクリック回避


def draw_cross(cx, cy, size=30):
    """十字マーカーを描く"""
    draw_line(cx - size, cy, cx + size, cy)
    draw_line(cx, cy - size, cx, cy + size)


def main():
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    cx, cy = sw // 2, sh // 2

    print(f"画面: {sw}x{sh}, 中央: ({cx},{cy})")
    print()
    print("=== キャリブレーション パターン ===")
    print()
    print("描画するもの:")
    print("  1. 画面中央に十字 (基準点)")
    print("  2. 中央から上下左右 200px に十字 (位置ズレ測定)")
    print("  3. 中央 / 上 / 下 に同じ長さ(200px)の水平線 (長さの変化測定)")
    print("  4. 中央 / 左 / 右 に同じ長さ(200px)の垂直線 (長さの変化測定)")
    print()
    print("期待される位置:")
    print(f"  中央十字:   ({cx}, {cy})")
    print(f"  上の十字:   ({cx}, {cy - 200})")
    print(f"  下の十字:   ({cx}, {cy + 200})")
    print(f"  左の十字:   ({cx - 200}, {cy})")
    print(f"  右の十字:   ({cx + 200}, {cy})")
    print(f"  水平線の長さ: 各200px")
    print(f"  垂直線の長さ: 各200px")
    print()

    print("5秒後に描画を開始します。VRChatでQVPenを持って待機してください...")
    print("(中断: Ctrl+C)")
    for i in range(5, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    print()
    print(">>> カーソルを画面中央に移動...")
    mouse_move(cx, cy)
    time.sleep(0.2)

    print(">>> Tabキーを押下...")
    key_tab(down=True)
    time.sleep(1.5)

    # プライミング
    mouse_move(cx, cy)
    time.sleep(0.5)

    try:
        # === 1. 画面中央に十字 ===
        print("描画中: 中央十字...")
        draw_cross(cx, cy, 30)

        # === 2. 上下左右 200px に十字 ===
        offsets = [
            ("上", cx, cy - 200),
            ("下", cx, cy + 200),
            ("左", cx - 200, cy),
            ("右", cx + 200, cy),
        ]
        for name, ox, oy in offsets:
            print(f"描画中: {name}の十字 ({ox},{oy})...")
            draw_cross(ox, oy, 20)

        # === 3. 水平線 (同じ長さ200px) ===
        h_lines = [
            ("中央の水平線", cx - 100, cy + 60, cx + 100, cy + 60),
            ("上の水平線",   cx - 100, cy - 200 + 40, cx + 100, cy - 200 + 40),
            ("下の水平線",   cx - 100, cy + 200 + 40, cx + 100, cy + 200 + 40),
        ]
        for name, x1, y1, x2, y2 in h_lines:
            print(f"描画中: {name} ({x1},{y1})→({x2},{y2})...")
            draw_line(x1, y1, x2, y2)

        # === 4. 垂直線 (同じ長さ200px) ===
        v_lines = [
            ("中央の垂直線", cx + 60, cy - 100, cx + 60, cy + 100),
            ("左の垂直線",   cx - 200 + 40, cy - 100, cx - 200 + 40, cy + 100),
            ("右の垂直線",   cx + 200 + 40, cy - 100, cx + 200 + 40, cy + 100),
        ]
        for name, x1, y1, x2, y2 in v_lines:
            print(f"描画中: {name} ({x1},{y1})→({x2},{y2})...")
            draw_line(x1, y1, x2, y2)

        print()
        print("=== 描画完了 ===")
        print()
        print("VRChat内で以下を確認してください:")
        print()
        print("【位置のズレ】")
        print("  - 中央の十字は画面中央にありますか？")
        print("  - 上下左右の十字は中央から等距離ですか？")
        print("  - 上下左右の十字は期待位置(200px離れた場所)にありますか？")
        print("    → 近すぎる場合、VRCの感度 < 1.0")
        print("    → 遠すぎる場合、VRCの感度 > 1.0")
        print()
        print("【長さの変化】")
        print("  - 中央/上/下の水平線は全て同じ長さですか？")
        print("  - 中央/左/右の垂直線は全て同じ長さですか？")
        print("    → 同じ長さ: 線形スケーリング (感度補正で修正可能)")
        print("    → 端ほど短い: 非線形 (より複雑な補正が必要)")
        print("    → 端ほど長い: 逆方向の非線形")

    except KeyboardInterrupt:
        print("\n中断されました")
    finally:
        key_tab(down=False)
        mouse_up()
        print("Tabキーを解放しました")


if __name__ == '__main__':
    main()
