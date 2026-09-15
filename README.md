# RollerCoin AutoBot Master

**Professional, vision-based automation suite for RollerCoin mini-games.**

A robust, multi-threaded Python application that plays **CoinClick**, **Coin Fisher**, and **Hamster Climber** fully automatically. It uses real-time screen capture, precise HSV colour detection, connected-component analysis, and intelligent menu navigation with recovery logic for pop-ups and cooldowns.

---

### Game-Specific Logic

| Game | Detection Method | Action |
|------|------------------|--------|
| **CoinClick** | Multiple precise BGR colour masks for coin variants | Click the first matching pixel (left-most / top-most) |
| **Coin Fisher** | Complex multi-condition BGR mask for fish / objects | Click largest valid connected component (area & size limits) |
| **Hamster Climber** | Exact BGR match for the green “jump” signal | Press `Space` when signal appears (edge-triggered) |

End-of-game detection uses a narrow cyan-ish colour that appears on the results screen (with a grace period after start).

### Autoplay Flow (Infinite Loop)

```
START (chosen first game)
  │
  ├─► Scroll to top of menu (HOME)
  ├─► Detect all game cards by cyan/gray buttons
  ├─► Wait until target card is cyan (START) instead of gray (WAIT)
  │     └─ after 30 s of WAIT → press F5 and re-scroll
  ├─► Click card → Click global START button
  ├─► Run the corresponding GameBot loop
  ├─► Monitor for YOU WIN or GAME OVER (popup colour + button presence)
  ├─► On WIN  → Collect rewards (COLLECT → CLAIM REWARD → CHOOSE GAME)
  ├─► On LOSS → Click TO GAMES → wait for grid
  └─► Next game in cycle … (repeats forever)
```

When the detector sees only 1–2 tiles (common when a reward popup still covers the grid), it immediately attempts recovery before falling back to the normal wait/F5 logic.

---

## Requirements

- **Python 3.10+**
- Windows / Linux / macOS (tested primarily on Windows)
- Dependencies:

```bash
pip install opencv-python numpy mss pyautogui keyboard
```

> Note: `keyboard` and global hotkeys usually require administrator / elevated privileges on Windows and Linux.

---

## Installation & First Run

1. Clone or download the repository.
2. Install the packages listed above.
3. Run:

```bash
python RollerCoinAutoBotMaster.py
```

4. Click **Set Game Region**.
5. Drag a tight rectangle around the actual play area of the mini-game (the canvas where coins/fish/hamster appear). Confirm.
6. Select the desired minigame from the dropdown (or leave CoinClick).
7. Start the bot according to the mode you want:

   - **Single game**  
     Open the chosen mini-game yourself.  
     When the countdown is running, click the game’s own **START** button, then immediately press **Start / Resume (PAGE UP)** in the bot.  
     The bot takes over and plays the game from that moment.

   - **Autoplay (infinite loop)**  
     Stay on the main **game selection screen** (the grid of mini-games) and simply press **AUTOPLAY – all supported games (infinite loop)**.  
     The bot will handle everything automatically: selecting games, starting them, collecting rewards and cycling forever.

---

## Controls

| Action | GUI | Hotkey |
|--------|-----|--------|
| Start / Resume single game | Start / Resume button | `PAGE UP` |
| Stop everything | STOP button | `Q` or `ESC` |
| Emergency stop | – | Move mouse to **top-left corner** of the screen |
| Select region | Set Game Region button | – |

---

## Configuration (`config.json`)

Automatically created next to the script. Example:

```json
{
  "x": 575,
  "y": 390,
  "width": 828,
  "height": 417,
  "wait_time": 0.02,
  "scan_interval": 0.01,
  "color_tolerance": 12
}
```

| Key | Meaning |
|-----|---------|
| `x`, `y`, `width`, `height` | Absolute screen region of the game canvas |
| `wait_time` | Short sleep after a click (CoinClick / Hamster) |
| `scan_interval` | Polling interval of the game loops |
| `color_tolerance` | Tolerance used for end-of-game colour detection |

You normally never edit this file by hand – the region selector writes the correct values.

---

## Reliability Features

- **Retry loops** with configurable maximum attempts for every critical UI action (card selection, START button, reward collection, return to menu).
- **Grace period** after game start before win/loss detection is allowed (avoids false positives on loading screens).
- **Popup recovery** when the grid appears incomplete.
- **F5 refresh** after prolonged WAIT status on a game card.
- **Thread-safe stop / pause events** so the GUI remains responsive.
- **Fail-safe** of PyAutoGUI + explicit hotkeys.

---

## Limitations & Recommendations

- The bot is vision-based. Significant changes to RollerCoin’s UI colours, button sizes or layout will require updating the HSV ranges and size filters.
- Best results are obtained with a stable resolution and the browser zoom set to 100 %.
- Keep the game window fully visible and unobscured.
- Run the script with the privileges required by the `keyboard` library.
- This tool is intended for personal, educational and experimental use. Respect RollerCoin’s Terms of Service.

---

## Project Structure

```
RollerCoinAutoBotMaster.py   # Complete application (GUI + bots + autoplay)
config.json                  # Auto-generated settings (created on first region save)
README.md                    # This documentation
```

---

## License & Disclaimer

Provided as-is for educational purposes. The author assumes no responsibility for any consequences arising from the use of this software, including account restrictions or bans that may result from automated play on third-party platforms.

Use at your own risk.
