import pyautogui
import time
import keyboard

def space_click(wait=0.2):
    pyautogui.press('space')
    time.sleep(wait)

def is_color_in_range(target_color, actual_color, tolerance):
    return all(abs(tc - ac) <= tolerance for tc, ac in zip(target_color, actual_color))

def hamsterClimber(a):
    print("START GAME")
    tolerance = 2  
    target_color = (55, 173, 67) 

    while a == 1:
        pic = pyautogui.screenshot(region=(575, 390, 828, 417))
        width, height = pic.size
        found = False
        
        for x in range(0, width, 5):
            for y in range(0, height, 5):
                r, g, b = pic.getpixel((x, y))

                if r == 3 and g == 225 and b == 228:
                    a = 0
                    break

                if is_color_in_range(target_color, (r, g, b), tolerance):
                    space_click(wait=1)
                    found = True
                    break
            if found:
                break

        time.sleep(0.05)

    print("END GAME")
    start()

def start():
    print("Press PAGE UP, when the countdown is displayed")
    keyboard.wait("page up")
    a = 1
    hamsterClimber(a)

start()
