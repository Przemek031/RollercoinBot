import pyautogui
import time
import keyboard

X_START = 64
Y_START = 117
WIDTH = 1475
HEIGHT = 896
GAME_REGION = (X_START, Y_START, WIDTH, HEIGHT)

def mouse_click(x, y):
    """Clicks the target and waits for the hook animation to finish."""
    pyautogui.click(x, y)
    print(f"Target hit at: {x}, {y}. Reeling in...")
    # Adjust this delay based on how long it takes to pull the coin back
    time.sleep(0.5) 

def coin_clicker():
    print("BOT ACTIVE - Precision Mode")
    print("Scanning for coins... Press 'q' to stop.")
    
    while True:
        # Emergency stop
        if keyboard.is_pressed('q'):
            print("Bot deactivated.")
            break

        # Take a screenshot of the specific game area
        pic = pyautogui.screenshot(region=GAME_REGION)
        w, h = pic.size
        found = False

        for x in range(0, w, 7):
            for y in range(0, h, 7):
                r, g, b = pic.getpixel((x, y))

                # 1. BTC 
                if (r > 240 and 130 < g < 170 and b < 50):
                    mouse_click(x + X_START, y + Y_START)
                    found = True

                # 2. DOGE / GOLD 
                elif (r > 220 and g > 190 and 80 < b < 120):
                    mouse_click(x + X_START, y + Y_START)
                    found = True

                # 3. ETH 
                elif (110 < r < 150 and 130 < g < 180 and b > 240):
                    mouse_click(x + X_START, y + Y_START)
                    found = True

                # 4. LTC 
                # Filtering against blue water by ensuring R, G, B are nearly equal
                elif (r > 210 and g > 210 and b > 210 and abs(r - b) < 5):
                    mouse_click(x + X_START, y + Y_START)
                    found = True
                
                # 5. DASH 
                elif (r < 50 and 100 < g < 150 and 190 < b < 230):
                    mouse_click(x + X_START, y + Y_START)
                    found = True

                if found: break
            if found: break

def start():
    print(f"Region set to: {X_START}, {Y_START} with size {WIDTH}x{HEIGHT}")
    print("Press PAGE UP to start the bot.")
    keyboard.wait("page up")
    coin_clicker()

if __name__ == "__main__":
    start()