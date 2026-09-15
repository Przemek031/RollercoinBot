"""RollerCoin AutoBot Master.

GUI-driven automation for CoinClick, Coin Fisher, and Hamster Climber.
Uses grid geometry, precise HSV color masks, smart WAIT polling, and controlled F5 refresh.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import keyboard
import mss
import numpy as np
import pyautogui
import tkinter as tk
from tkinter import messagebox, ttk


CONFIG_PATH = Path(__file__).with_name("config.json")
DEFAULT_REGION = (575, 390, 828, 417)

pyautogui.FAILSAFE = True


@dataclass
class GameConfig:
    x: int = DEFAULT_REGION[0]
    y: int = DEFAULT_REGION[1]
    width: int = DEFAULT_REGION[2]
    height: int = DEFAULT_REGION[3]
    wait_time: float = 0.02
    scan_interval: float = 0.01
    color_tolerance: int = 12

    @property
    def region(self) -> dict[str, int]:
        return {"left": self.x, "top": self.y, "width": self.width, "height": self.height}


class ConfigManager:
    """Loads and saves validated application settings in config.json."""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path

    def load(self) -> GameConfig:
        if not self.path.exists():
            return GameConfig()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            defaults = asdict(GameConfig())
            values = {key: data.get(key, value) for key, value in defaults.items()}
            config = GameConfig(**values)
            self._validate(config)
            return config
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logging.warning("Cannot read configuration: %s", exc)
            return GameConfig()

    def save(self, config: GameConfig) -> None:
        self._validate(config)
        self.path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")

    @staticmethod
    def _validate(config: GameConfig) -> None:
        if config.width <= 0 or config.height <= 0:
            raise ValueError("Region width and height must be greater than zero.")
        if config.wait_time < 0 or config.scan_interval <= 0:
            raise ValueError("Delays must have valid values.")
        if not 0 <= config.color_tolerance <= 255:
            raise ValueError("Color tolerance must be in the range 0-255.")


class ScreenSelector:
    """Full-screen transparent overlay used to select a game rectangle."""

    def __init__(self, parent: tk.Misc, on_selected: Callable[[tuple[int, int, int, int]], None]) -> None:
        self.parent = parent
        self.on_selected = on_selected
        self.window = tk.Toplevel(parent)
        self.window.attributes("-fullscreen", True)
        self.window.attributes("-alpha", 0.25)
        self.window.attributes("-topmost", True)
        self.window.configure(background="black")
        self.window.title("Select game region")
        self.canvas = tk.Canvas(self.window, cursor="crosshair", background="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.start: Optional[tuple[int, int]] = None
        self.rectangle: Optional[int] = None
        self.canvas.create_text(
            20,
            20,
            anchor="nw",
            text="Drag a rectangle around the game. ESC cancels.",
            fill="white",
            font=("Segoe UI", 16, "bold"),
        )
        self.canvas.bind("<ButtonPress-1>", self._begin)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        self.window.grab_set()
        self.canvas.focus_set()

    def _begin(self, event: tk.Event) -> None:
        self.start = (event.x, event.y)
        self.rectangle = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#00ff80", width=3)

    def _drag(self, event: tk.Event) -> None:
        if self.start is not None and self.rectangle is not None:
            self.canvas.coords(self.rectangle, self.start[0], self.start[1], event.x, event.y)

    def _finish(self, event: tk.Event) -> None:
        if self.start is None:
            return
        x1, y1 = self.start
        x2, y2 = event.x, event.y
        left, top = min(x1, x2), min(y1, y2)
        width, height = abs(x2 - x1), abs(y2 - y1)
        if width >= 20 and height >= 20:
            self.on_selected((left, top, width, height))
            self.window.destroy()


class GameBots:
    """Thread-safe game runners sharing one capture and input implementation."""

    def __init__(self, config: GameConfig, logger: Callable[[str], None]) -> None:
        self.config = config
        self.logger = logger
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.end_event = threading.Event()
        self.result: Optional[str] = None
        self.last_input_at = 0.0
        self._end_detection_after = 0.0
        self._thread: Optional[threading.Thread] = None
        self._capture = mss.mss()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def ended_normally(self) -> bool:
        return self.end_event.is_set()

    def start(self, game: str) -> None:
        if self.running:
            self.pause_event.set()
            self.logger("Resumed scanning.")
            return
        self.stop_event.clear()
        self.end_event.clear()
        self.result = None
        self.last_input_at = time.monotonic()
        self._end_detection_after = time.monotonic() + 8.0
        self.pause_event.set()
        if game == "CoinClick":
            target = self._coinclick_loop
        elif game == "Coin Fisher":
            target = self._coinfisher_loop
        else:
            target = self._hamster_loop
        self._thread = threading.Thread(target=self._run_safe, args=(target,), daemon=True)
        self._thread.start()

    def pause(self) -> None:
        if self.running:
            self.pause_event.clear()
            self.logger("Paused scanning.")

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.set()
        self.logger("Bot stopped.")

    def close(self) -> None:
        self.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._capture.close()

    def _run_safe(self, target: Callable[[], None]) -> None:
        try:
            self.logger("Bot started.")
            target()
        except pyautogui.FailSafeException:
            self.logger("Emergency stop: cursor moved to the top-left corner.")
            self.stop_event.set()
        except Exception as exc:
            logging.exception("Automation error")
            self.logger(f"Error: {exc}")
        finally:
            self.logger("Bot finished.")

    def _frame(self) -> np.ndarray:
        return np.asarray(self._capture.grab(self.config.region))[:, :, :3]

    def _coinclick_loop(self) -> None:
        hits = 0
        while not self.stop_event.is_set():
            self.pause_event.wait()
            frame = self._frame()
            if self._end_game_detected(frame):
                hits += 1
                if hits >= 3:
                    self.result = "ended"
                    self.logger("End of game detected.")
                    self.end_event.set()
                    break
            else:
                hits = 0
            self._click_coin(frame)
            time.sleep(self.config.scan_interval)

    def _hamster_loop(self) -> None:
        signal_active = False
        target_bgr = np.array([67, 173, 55], dtype=np.int16)
        hits = 0
        while not self.stop_event.is_set():
            self.pause_event.wait()
            frame = self._frame()
            if self._end_game_detected(frame):
                hits += 1
                if hits >= 3:
                    self.result = "ended"
                    self.logger("End of game detected.")
                    self.end_event.set()
                    break
            else:
                hits = 0
            difference = np.abs(frame.astype(np.int16) - target_bgr)
            mask = np.all(difference <= 2, axis=2).astype(np.uint8)
            signal_found = self._largest_component_area(mask) >= 5
            if signal_found and not signal_active:
                self.last_input_at = time.monotonic()
                pyautogui.press("space")
                time.sleep(self.config.wait_time)
            else:
                time.sleep(self.config.scan_interval)
            signal_active = signal_found

    def _coinfisher_loop(self) -> None:
        hits = 0
        while not self.stop_event.is_set():
            self.pause_event.wait()
            frame = self._frame()
            if self._end_game_detected(frame):
                hits += 1
                if hits >= 3:
                    self.result = "ended"
                    self.logger("End of game detected.")
                    self.end_event.set()
                    break
            else:
                hits = 0
            blue, green, red = cv2.split(frame)
            blue_i = blue.astype(np.int16)
            green_i = green.astype(np.int16)
            red_i = red.astype(np.int16)
            mask = (
                ((red_i > 240) & (green_i > 130) & (green_i < 170) & (blue_i < 50))
                | ((red_i > 220) & (green_i > 190) & (blue_i > 80) & (blue_i < 120))
                | ((red_i > 110) & (red_i < 150) & (green_i > 130) & (green_i < 180) & (blue_i > 240))
                | ((red_i > 210) & (green_i > 210) & (blue_i > 210) & (np.abs(red_i - blue_i) < 5))
                | ((red_i < 50) & (green_i > 100) & (green_i < 150) & (blue_i > 190) & (blue_i < 230))
            ).astype(np.uint8)
            self._click_largest_component(mask, minimum_area=4, maximum_area=2500, maximum_size=120)
            time.sleep(max(0.05, self.config.wait_time, 0.5))

    def _has_end_game_color(self, frame: np.ndarray) -> bool:
        blue, green, red = cv2.split(frame)
        tolerance = min(self.config.color_tolerance, 5)
        matching_pixels = (
            (np.abs(blue.astype(np.int16) - 228) <= tolerance)
            & (np.abs(green.astype(np.int16) - 225) <= tolerance)
            & (np.abs(red.astype(np.int16) - 3) <= tolerance)
        )
        return int(np.count_nonzero(matching_pixels)) >= 25

    def _end_game_detected(self, frame: np.ndarray) -> bool:
        return time.monotonic() >= self._end_detection_after and self._has_end_game_color(frame)

    @staticmethod
    def _largest_component_area(mask: np.ndarray) -> int:
        component_count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        if component_count <= 1:
            return 0
        return int(np.max(stats[1:, cv2.CC_STAT_AREA]))

    def _click_largest_component(
        self,
        mask: np.ndarray,
        minimum_area: int,
        maximum_area: int | None = None,
        maximum_size: int | None = None,
    ) -> None:
        component_count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        if component_count <= 1:
            return
        candidates = np.arange(1, component_count)
        areas = stats[1:, cv2.CC_STAT_AREA]
        candidates = candidates[areas >= minimum_area]
        if maximum_area is not None:
            candidates = candidates[stats[candidates, cv2.CC_STAT_AREA] <= maximum_area]
        if maximum_size is not None:
            candidates = candidates[
                (stats[candidates, cv2.CC_STAT_WIDTH] <= maximum_size)
                & (stats[candidates, cv2.CC_STAT_HEIGHT] <= maximum_size)
            ]
        if candidates.size == 0:
            return
        component = int(candidates[np.argmax(stats[candidates, cv2.CC_STAT_AREA])])
        x = int(round(centroids[component][0] + self.config.x))
        y = int(round(centroids[component][1] + self.config.y))
        self.last_input_at = time.monotonic()
        pyautogui.click(x, y)

    def _click_coin(self, frame: np.ndarray) -> None:
        blue, green, red = cv2.split(frame)
        blue_i = blue.astype(np.int16)
        green_i = green.astype(np.int16)
        red_i = red.astype(np.int16)

        channel_tolerance = 3

        def close(channel: np.ndarray, value: int) -> np.ndarray:
            return np.abs(channel - value) <= channel_tolerance

        masks = (
            close(red_i, 0),
            close(red_i, 200),
            close(red_i, 231),
            close(red_i, 230),
            close(red_i, 66) & close(green_i, 105),
        )
        blue_values = (183, 64, 33, 230, 207)
        for color_mask, blue_value in zip(masks, blue_values):
            color_mask = color_mask & close(blue_i, blue_value)
            ys, xs = np.where(color_mask)
            if xs.size == 0:
                continue
            order = np.lexsort((ys, xs))
            x = int(xs[order[0]] + self.config.x)
            y = int(ys[order[0]] + self.config.y)
            self.last_input_at = time.monotonic()
            pyautogui.click(x, y)
            time.sleep(self.config.wait_time)
            return


class AutoplayController:
    """Navigates the Rollercoin game menu and runs the supported mini-games."""

    GAMES = ("CoinClick", "Coin Fisher", "Hamster Climber")

    GAME_GRID_INDEXES = {
        "CoinClick": 1,
        "Coin Fisher": 6,
        "Hamster Climber": 7,
    }

    MAX_RETRIES = 3
    WIN_CHECK_GRACE_PERIOD = 3.0

    def __init__(self, bot: GameBots, logger: Callable[[str], None]) -> None:
        self.bot = bot
        self.logger = logger
        self.stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._capture = mss.mss()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, first_game: str = "CoinClick") -> None:
        if self.running:
            self.logger("Autoplay is already running.")
            return
        if first_game not in self.GAMES:
            first_game = self.GAMES[0]
        start_index = self.GAMES.index(first_game)
        game_cycle = self.GAMES[start_index:] + self.GAMES[:start_index]
        self.stop_event.clear()
        self._thread = threading.Thread(target=self._run_safe, args=(game_cycle,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.bot.stop()
        self.logger("Autoplay stopped.")

    def close(self) -> None:
        self.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._capture.close()

    def _run_safe(self, game_cycle: tuple[str, ...]) -> None:
        try:
            self.logger(f"Autoplay: starting infinite loop from {game_cycle[0]}.")
            while not self.stop_event.is_set():
                for game in game_cycle:
                    if self.stop_event.is_set():
                        break
                    self._play_game(game)
                if self.stop_event.is_set():
                    self.logger("Autoplay: loop stopped.")
                    break
                self.logger("Autoplay: completed one full cycle, continuing...")
        except pyautogui.FailSafeException:
            self.logger("Autoplay stopped by FAILSAFE.")
            self.stop_event.set()
        except Exception as exc:
            logging.exception("Autoplay error")
            self.logger(f"Autoplay - error: {exc}")
            self.stop_event.set()

    def _retry(self, description: str, action: Callable[[int], bool], attempts: int = MAX_RETRIES) -> bool:
        for attempt in range(1, attempts + 1):
            if self.stop_event.is_set():
                return False
            if action(attempt):
                return True
            self.logger(f"Autoplay: {description} - attempt {attempt}/{attempts} failed.")
        self.logger(f"Autoplay: {description} - all {attempts} attempts failed, aborting step.")
        return False

    def _play_game(self, game: str) -> None:
        self.logger(f"Autoplay: selecting {game}.")
        if not self._retry(f"select game card {game}", lambda _attempt: self._click_menu_game(game)):
            raise RuntimeError(f"Failed to start game: {game}")

        time.sleep(1.0)

        if not self._retry(
            "game START button",
            lambda _attempt: self._click_cyan_button(expected=(0.50, 0.38), timeout=20),
        ):
            raise RuntimeError("Game START button not found.")
        self.logger(f"Autoplay: starting {game}.")
        game_started_at = time.monotonic()
        self.bot.start(game)

        max_game_duration = 75.0
        while time.monotonic() - game_started_at < max_game_duration and not self.stop_event.is_set():
            if time.monotonic() - game_started_at >= self.WIN_CHECK_GRACE_PERIOD:
                if self._confirm_win_popup(game):
                    self.bot.result = "ended"
                    self.bot.end_event.set()
                    self.bot.stop()
                    self.logger("Autoplay: YOU WIN confirmed by consistent win popup.")
                    break
                if self._full_screen_game_over_detected():
                    self.bot.result = "ended"
                    self.bot.end_event.set()
                    self.bot.stop()
                    self.logger("Autoplay: GAME OVER detected.")
                    break
            if not self.bot.running and self.bot.ended_normally:
                break
            time.sleep(0.2)

        if self.stop_event.is_set():
            return

        outcome = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            if self.stop_event.is_set():
                return
            outcome = self._resolve_game_result(timeout=15)
            if outcome is not None:
                break
            self.logger(
                f"Autoplay: no clear game result (WIN/GAME OVER) - attempt {attempt}/{self.MAX_RETRIES}."
            )
        if outcome is None:
            self.logger("Autoplay: could not determine game result after several attempts; stopping loop.")
            self.stop_event.set()
            return

        if outcome == "loss":
            self.logger("Autoplay: GAME OVER, moving to next game.")
            to_games_ok = self._retry("return TO GAMES", lambda _attempt: self._click_to_games(timeout=10))
            grid_ok = to_games_ok and self._retry(
                "wait for game grid", lambda _attempt: self._wait_for_game_grid(timeout=15)
            )
            if not grid_ok:
                self.logger("Autoplay: failed to return to menu after GAME OVER.")
                self.stop_event.set()
            return

        if not self._retry("collect rewards", lambda _attempt: self._collect_rewards()):
            self.logger("Autoplay: reward or CHOOSE GAME was not handled correctly; stopping loop.")
            self.stop_event.set()

    def _resolve_game_result(self, timeout: float) -> Optional[str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            if self._full_screen_game_over_detected():
                return "loss"
            if self._full_screen_win_detected():
                return "win"
            time.sleep(0.15)
        return None

    _POPUP_SEARCH_BOUNDS = (0.03, 0.97, 0.08, 0.92)

    def _popup_crop(self, frame: np.ndarray) -> tuple[np.ndarray, int, int]:
        height, width = frame.shape[:2]
        x_min, x_max, y_min, y_max = self._POPUP_SEARCH_BOUNDS
        left, right = int(width * x_min), int(width * x_max)
        top, bottom = int(height * y_min), int(height * y_max)
        return frame[top:bottom, left:right], left, top

    def _full_screen_win_detected(self) -> bool:
        monitor = self._screen_monitor()
        frame = np.asarray(self._capture.grab(monitor))[:, :, :3]
        popup, crop_left, crop_top = self._popup_crop(frame)
        blue, green, red = cv2.split(popup)
        blue_i = blue.astype(np.int16)
        green_i = green.astype(np.int16)
        red_i = red.astype(np.int16)

        claim_button = self._find_claim_reward_button()
        if claim_button is None:
            return False

        gold_mask = ((red_i > 160) & (green_i > 120) & (blue_i < 150)).astype(np.uint8)
        gold_pixels = int(np.count_nonzero(gold_mask))
        if gold_pixels < 300:
            return False

        return True

    def _full_screen_game_over_detected(self) -> bool:
        to_games_button = self._find_to_games_button()
        if to_games_button is None:
            return False

        monitor = self._screen_monitor()
        frame = np.asarray(self._capture.grab(monitor))[:, :, :3]
        popup, _, _ = self._popup_crop(frame)
        blue, green, red = cv2.split(popup)
        blue_i = blue.astype(np.int16)
        green_i = green.astype(np.int16)
        red_i = red.astype(np.int16)

        red_mask = ((red_i > 130) & (red_i > green_i + 40) & (red_i > blue_i + 40)).astype(np.uint8)
        return int(np.count_nonzero(red_mask)) >= 500

    def _click_to_games(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            point = self._find_to_games_button()
            if point is not None:
                x, y = point
                self.logger(f"Autoplay: clicking TO GAMES ({x}, {y}).")
                pyautogui.click(x, y)
                time.sleep(0.5)
                return True
            time.sleep(0.15)
        return False

    def _find_to_games_button(self) -> Optional[tuple[int, int]]:
        screen = self._screen_monitor()
        x_min, x_max, y_min, y_max = self._POPUP_SEARCH_BOUNDS
        left = screen["left"] + screen["width"] * x_min
        right = screen["left"] + screen["width"] * x_max
        top = screen["top"] + screen["height"] * y_min
        bottom = screen["top"] + screen["height"] * y_max
        center_x = (left + right) / 2
        center_y = (top + bottom) / 2
        candidates = []
        for x, y, width, height, area in self._cyan_components():
            center = x + width / 2
            middle = y + height / 2
            if (
                width >= 160
                and height >= 24
                and width / max(height, 1) >= 2.5
                and left <= center <= right
                and top <= middle <= bottom
            ):
                distance = (center - center_x) ** 2 + (middle - center_y) ** 2
                candidates.append((distance, -area, x + width // 2, y + height // 2))
        if not candidates:
            return None
        selected = min(candidates)
        return selected[2], selected[3]

    def _collect_rewards(self) -> bool:
        time.sleep(1.0)

        # Safety: try to close optional reward popup (COLLECT) only if it actually appears
        self.logger("Autoplay: checking for reward popup (COLLECT)...")
        if self._click_optional_collect(timeout=1.0):
            self.logger("Autoplay: clicked COLLECT button in reward popup.")
            time.sleep(1.0)

        first_point = self._wait_for_claim_reward(timeout=10)
        if first_point is not None:
            x, y = first_point
            self.logger(f"Autoplay: clicking CLAIM REWARD ({x}, {y}).")
            pyautogui.click(x, y)
            time.sleep(0.8)

        self.logger("Autoplay: game result collected, waiting for summary.")

        # If another popup appeared after claiming the reward
        if self._click_optional_collect(timeout=1.5):
            self.logger("Autoplay: detected and collected extra reward (COLLECT).")
            time.sleep(1.2)

        if not self._click_choose_game(timeout=15):
            self.logger("Autoplay: CHOOSE GAME not found.")
            return False

        if not self._wait_for_game_grid(timeout=15):
            self.logger("Autoplay: game menu did not load after CHOOSE GAME.")
            return False
        return True

    def _confirm_win_popup(self, game: str) -> bool:
        return self._full_screen_win_detected()

    def _click_optional_collect(self, timeout: float) -> bool:
        # More precise check of the center of the screen where the COLLECT window usually appears
        screen = self._screen_monitor()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            candidates = [
                (x, y, w, h)
                for x, y, w, h, _ in self._cyan_components_raw()
                if screen["left"] + screen["width"] * 0.35 <= x + w // 2 <= screen["left"] + screen["width"] * 0.65
                and screen["top"] + screen["height"] * 0.70 <= y + h // 2 <= screen["top"] + screen["height"] * 0.95
            ]
            if candidates:
                # Choose the one closest to the center
                best = min(candidates, key=lambda c: abs((c[0] + c[2] // 2) - (screen["left"] + screen["width"] * 0.5)))
                px, py = best[0] + best[2] // 2, best[1] + best[3] // 2
                self.logger(f"Autoplay: clicking COLLECT ({px}, {py}).")
                pyautogui.click(px, py)
                time.sleep(0.5)
                return True
            time.sleep(0.2)
        return False

    def _cyan_components_raw(self) -> list[tuple[int, int, int, int, int]]:
        monitor = self._screen_monitor()
        frame = np.asarray(self._capture.grab(monitor))[:, :, :3]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(
            hsv,
            np.array([80, 100, 100], dtype=np.uint8),
            np.array([105, 255, 255], dtype=np.uint8),
        )
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        components: list[tuple[int, int, int, int, int]] = []
        for component in range(1, count):
            x, y, width, height, area = stats[component]
            if area >= 300 and width >= 70 and height >= 20 and width / max(height, 1) >= 2:
                components.append(
                    (
                        int(x + monitor["left"]),
                        int(y + monitor["top"]),
                        int(width),
                        int(height),
                        int(area),
                    )
                )
        return components

    def _click_choose_game(self, timeout: float) -> bool:
        # Precisely look for the CHOOSE GAME button in the upper part of the stats panel
        screen = self._screen_monitor()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            candidates = [
                (x, y, w, h)
                for x, y, w, h, _ in self._cyan_components_raw()
                if screen["left"] + screen["width"] * 0.45 <= x + w // 2 <= screen["left"] + screen["width"] * 0.85
                and screen["top"] + screen["height"] * 0.20 <= y + h // 2 <= screen["top"] + screen["height"] * 0.35
            ]
            if candidates:
                best = min(candidates, key=lambda c: abs((c[0] + c[2] // 2) - (screen["left"] + screen["width"] * 0.65)))
                px, py = best[0] + best[2] // 2, best[1] + best[3] // 2
                self.logger(f"Autoplay: clicking CHOOSE GAME ({px}, {py}).")
                pyautogui.click(px, py)
                time.sleep(0.5)
                return True
            time.sleep(0.2)
        return False

    def _click_menu_game(self, game: str) -> bool:
        self._reset_menu_scroll()
        self.logger(f"Autoplay: looking for {game} card.")

        start_time = time.monotonic()
        max_total_wait = 300.0
        f5_refresh_threshold = 30.0
        last_f5_time = start_time

        while time.monotonic() - start_time < max_total_wait and not self.stop_event.is_set():
            cards = self._detect_all_game_cards()
            target_idx = self.GAME_GRID_INDEXES.get(game)

            if cards and target_idx is not None and target_idx < len(cards):
                bx, by, bw, bh = cards[target_idx]
                click_x = bx + (bw // 2)
                click_y = by + (bh // 2)

                if self._is_start_button_active(click_x, click_y):
                    self.logger(f"Autoplay: game {game} (index {target_idx}) ready! Clicking START ({click_x}, {click_y}).")
                    pyautogui.click(click_x, click_y)
                    time.sleep(1.2)

                    if not self._is_grid_visible():
                        return True
                    else:
                        self.logger("Autoplay: grid still visible, retrying click...")
                else:
                    elapsed_wait = time.monotonic() - last_f5_time
                    self.logger(f"Autoplay: game {game} has WAIT status. Waiting 5s... ({int(elapsed_wait)}s / 30s until F5)")

                    if elapsed_wait >= f5_refresh_threshold:
                        self.logger("Autoplay: 30 seconds of WAIT status elapsed. Refreshing page (F5)...")
                        pyautogui.press("f5")
                        time.sleep(6.0)
                        self._reset_menu_scroll()
                        last_f5_time = time.monotonic()
                    else:
                        time.sleep(5.0)
            else:
                # When too few cards are detected, first check for a reward / COLLECT popup
                # that may be covering the grid (common cause of seeing only 1-2 tiles).
                detected_count = len(cards)
                self.logger(
                    f"Autoplay: detected {detected_count} tiles (required index {target_idx}). "
                    "Checking for reward popup before waiting..."
                )
                if self._handle_possible_reward_popup():
                    self.logger("Autoplay: handled a reward popup that was covering the grid.")
                    time.sleep(1.0)
                    continue  # re-detect cards after dismissing popup

                self.logger(f"Autoplay: detected {detected_count} tiles (required index {target_idx}). Waiting 5s...")
                time.sleep(5.0)

        return False

    def _handle_possible_reward_popup(self) -> bool:
        """
        When the game grid shows far fewer cards than expected, a reward/COLLECT
        or CLAIM REWARD popup is often still open and covering most of the grid.
        Try the common recovery actions once.
        """
        # 1. Optional COLLECT button (bottom-center)
        if self._click_optional_collect(timeout=0.8):
            return True

        # 2. CLAIM REWARD button
        claim = self._find_claim_reward_button()
        if claim is not None:
            x, y = claim
            self.logger(f"Autoplay: clicking CLAIM REWARD while recovering from low tile count ({x}, {y}).")
            pyautogui.click(x, y)
            time.sleep(0.8)
            # After claim there may still be a COLLECT
            self._click_optional_collect(timeout=1.0)
            return True

        # 3. TO GAMES (in case we are on a GAME OVER screen)
        if self._click_to_games(timeout=0.6):
            time.sleep(0.5)
            return True

        return False

    def _is_start_button_active(self, x: int, y: int) -> bool:
        monitor = self._screen_monitor()
        rel_x = int(x - monitor["left"])
        rel_y = int(y - monitor["top"])

        frame = np.asarray(self._capture.grab(monitor))[:, :, :3]

        y1, y2 = max(0, rel_y - 5), min(frame.shape[0], rel_y + 5)
        x1, x2 = max(0, rel_x - 5), min(frame.shape[1], rel_x + 5)
        region = frame[y1:y2, x1:x2]

        if region.size == 0:
            return False

        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        cyan_mask = cv2.inRange(hsv, np.array([80, 150, 180]), np.array([100, 255, 255]))
        return int(np.count_nonzero(cyan_mask)) > 5

    def _is_grid_visible(self) -> bool:
        cards = self._detect_all_game_cards()
        return len(cards) >= 3

    def _detect_all_game_cards(self) -> list[tuple[int, int, int, int]]:
        monitor = self._screen_monitor()
        frame = np.asarray(self._capture.grab(monitor))[:, :, :3]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        cyan_mask = cv2.inRange(hsv, np.array([80, 120, 150]), np.array([100, 255, 255]))
        gray_mask = cv2.inRange(hsv, np.array([0, 0, 40]), np.array([180, 50, 120]))

        combined_mask = cv2.bitwise_or(cyan_mask, gray_mask)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
        btn_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)

        count, _, stats, _ = cv2.connectedComponentsWithStats(btn_mask, 8)
        buttons = []
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            if 100 <= w <= 190 and 20 <= h <= 50 and area >= 1500:
                if y < frame.shape[0] * 0.15:
                    continue
                buttons.append((x + monitor["left"], y + monitor["top"], w, h))

        if not buttons:
            return []

        unique_buttons = []
        for b in buttons:
            if not any(abs(b[0] - u[0]) < 40 and abs(b[1] - u[1]) < 30 for u in unique_buttons):
                unique_buttons.append(b)

        unique_buttons.sort(key=lambda b: (b[1] // 120, b[0]))
        return unique_buttons

    def _reset_menu_scroll(self) -> None:
        monitor = self._screen_monitor()
        center_x = monitor["left"] + monitor["width"] // 2
        center_y = monitor["top"] + monitor["height"] // 2
        pyautogui.moveTo(center_x, center_y)
        pyautogui.press("home")
        time.sleep(1.2)
        self.logger("Autoplay: scrolled page to the very top (HOME).")

    def _click_cyan_button(
        self,
        expected: tuple[float, float],
        timeout: float,
        max_distance: float = 1.0,
    ) -> bool:
        point = self._find_cyan_button(expected, timeout, max_distance)
        if point is None:
            return False
        x, y = point
        self.logger(f"Autoplay: clicking UI button ({x}, {y}).")
        pyautogui.click(x, y)
        time.sleep(0.4)
        return True

    def _wait_for_claim_reward(self, timeout: float) -> Optional[tuple[int, int]]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            point = self._find_claim_reward_button()
            if point is not None:
                return point
            time.sleep(0.15)
        return None

    def _find_claim_reward_button(self) -> Optional[tuple[int, int]]:
        screen = self._screen_monitor()
        center_x = screen["left"] + screen["width"] * 0.50
        candidates = []
        for x, y, width, height, area in self._claim_components():
            center = x + width / 2
            if width >= 160 and height >= 24 and width / max(height, 1) >= 3.0:
                candidates.append((abs(center - center_x), -area, x + width // 2, y + height // 2))
        if not candidates:
            return None
        selected = min(candidates)
        return selected[2], selected[3]

    def _claim_components(self) -> list[tuple[int, int, int, int, int]]:
        monitor = self._screen_monitor()
        frame = np.asarray(self._capture.grab(monitor))[:, :, :3]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(
            hsv,
            np.array([78, 70, 90], dtype=np.uint8),
            np.array([108, 255, 255], dtype=np.uint8),
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 9))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        components: list[tuple[int, int, int, int, int]] = []
        for component in range(1, count):
            x, y, width, height, area = stats[component]
            if area >= 1200 and width >= 140 and height >= 18 and width / max(height, 1) >= 2.5:
                components.append(
                    (
                        int(x + monitor["left"]),
                        int(y + monitor["top"]),
                        int(width),
                        int(height),
                        int(area),
                    )
                )
        return components

    def _find_cyan_button(
        self,
        expected: tuple[float, float],
        timeout: float,
        max_distance: float,
    ) -> Optional[tuple[int, int]]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            candidates = self._cyan_buttons()
            if candidates:
                screen = self._screen_monitor()
                width, height = screen["width"], screen["height"]
                origin_x, origin_y = screen["left"], screen["top"]
                target_x, target_y = expected[0] * width, expected[1] * height
                target_x += origin_x
                target_y += origin_y
                point = min(candidates, key=lambda item: (item[0] - target_x) ** 2 + (item[1] - target_y) ** 2)
                distance = ((point[0] - target_x) ** 2 + (point[1] - target_y) ** 2) ** 0.5
                if distance > max_distance * max(width, height):
                    time.sleep(0.15)
                    continue
                return point
            time.sleep(0.15)
        return None

    def _wait_for_game_grid(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            cards = self._detect_all_game_cards()
            if len(cards) >= 3:
                return True
            time.sleep(0.2)
        return False

    def _screen_monitor(self) -> dict[str, int]:
        for monitor in self._capture.monitors[1:]:
            if (monitor["left"] <= self.bot.config.x < monitor["left"] + monitor["width"] and
                monitor["top"] <= self.bot.config.y < monitor["top"] + monitor["height"]):
                return monitor
        return self._capture.monitors[1]

    def _cyan_buttons(self) -> list[tuple[int, int]]:
        return [(x + width // 2, y + height // 2) for x, y, width, height, _ in self._cyan_components()]

    def _cyan_components(self) -> list[tuple[int, int, int, int, int]]:
        monitor = self._screen_monitor()
        frame = np.asarray(self._capture.grab(monitor))[:, :, :3]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(
            hsv,
            np.array([80, 100, 100], dtype=np.uint8),
            np.array([105, 255, 255], dtype=np.uint8),
        )
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        components: list[tuple[int, int, int, int, int]] = []
        for component in range(1, count):
            x, y, width, height, area = stats[component]
            if area >= 300 and width >= 70 and height >= 20 and width / max(height, 1) >= 2:
                components.append(
                    (
                        int(x + monitor["left"]),
                        int(y + monitor["top"]),
                        int(width),
                        int(height),
                        int(area),
                    )
                )
        return components


class AppGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("RollerCoin AutoBot Master")
        self.root.geometry("480x380")
        self.root.attributes("-topmost", True)
        self.config_manager = ConfigManager()
        self.config = self.config_manager.load()
        self.log_queue: list[str] = []
        self.bot = GameBots(self.config, self._log_from_thread)
        self.autoplay = AutoplayController(self.bot, self._log_from_thread)
        self.game = tk.StringVar(value="CoinClick")
        self._build()
        self.root.after(100, self._flush_log)
        keyboard.add_hotkey("page up", self._toggle_from_hotkey)
        keyboard.add_hotkey("q", self._stop_from_hotkey)
        keyboard.add_hotkey("esc", self._stop_from_hotkey)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="RollerCoin AutoBot Master", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        self.region_label = ttk.Label(frame, text=self._region_text())
        self.region_label.pack(anchor="w", pady=(8, 12))
        ttk.Button(frame, text="Set Game Region", command=self.select_region).pack(fill=tk.X)
        ttk.Label(frame, text="Minigame").pack(anchor="w", pady=(14, 2))
        ttk.Combobox(
            frame,
            textvariable=self.game,
            values=("CoinClick", "Hamster Climber", "Coin Fisher"),
            state="readonly",
        ).pack(fill=tk.X)
        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=16)
        ttk.Button(buttons, text="Start / Resume (PAGE UP)", command=self.start).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        ttk.Button(buttons, text="STOP (Q / ESC)", command=self.stop).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))
        ttk.Button(frame, text="AUTOPLAY - all supported games (infinite loop)", command=self.start_autoplay).pack(fill=tk.X, pady=(0, 10))
        self.status = ttk.Label(frame, text="Ready.")
        self.status.pack(anchor="w")
        self.log = tk.Text(frame, height=9, state=tk.DISABLED, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

    def _region_text(self) -> str:
        return f"Region: ({self.config.x}, {self.config.y})  {self.config.width} x {self.config.height}"

    def select_region(self) -> None:
        ScreenSelector(self.root, self._region_selected)

    def _region_selected(self, region: tuple[int, int, int, int]) -> None:
        self.config.x, self.config.y, self.config.width, self.config.height = region
        self.config_manager.save(self.config)
        self.region_label.configure(text=self._region_text())
        self._log_from_thread("Region saved to config.json.")

    def start(self) -> None:
        if self.autoplay.running:
            self._log_from_thread("Stop Autoplay first.")
            return
        self.config_manager.save(self.config)
        self.bot.start(self.game.get())

    def stop(self) -> None:
        self.autoplay.stop()
        self.bot.stop()

    def start_autoplay(self) -> None:
        if self.bot.running:
            self._log_from_thread("Stop the manually started game first.")
            return
        self.root.iconify()
        self.autoplay.start(self.game.get())

    def _toggle_from_hotkey(self) -> None:
        self.root.after(0, self.start)

    def _stop_from_hotkey(self) -> None:
        self.root.after(0, self.stop)

    def _log_from_thread(self, message: str) -> None:
        self.log_queue.append(message)

    def _flush_log(self) -> None:
        while self.log_queue:
            message = self.log_queue.pop(0)
            self.status.configure(text=message)
            self.log.configure(state=tk.NORMAL)
            self.log.insert(tk.END, message + "\n")
            self.log.see(tk.END)
            self.log.configure(state=tk.DISABLED)
        self.root.after(100, self._flush_log)

    def close(self) -> None:
        keyboard.unhook_all()
        self.autoplay.close()
        self.bot.close()
        self.root.destroy()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = tk.Tk()
    try:
        AppGUI(root)
        root.mainloop()
    except tk.TclError as exc:
        messagebox.showerror("GUI Error", str(exc))


if __name__ == "__main__":
    main()
