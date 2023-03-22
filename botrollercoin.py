from ast import While
import pyautogui
import numpy
import time
import keyboard

#64, 117, 1539, 1013
def mouse_click(x, y, wait=0.2):
    pyautogui.click(x, y)
    time.sleep(wait)

def coinclick(a):
    print("START GRY")
    while a==1:
        pic = pyautogui.screenshot(region=(530, 430, 828, 417))
        width, height = pic.size
        for x in range(0, width, 5):
            for y in range(0, height, 5):
                r, g, b = pic.getpixel((x, y))

                if b == 228 and r == 3 and g==225:
                    a=0
                    break

                # blue coin
                if b == 183 and r == 0:
                    mouse_click(x + 530, y + 440, wait=0)
                    break

                # yellow coin
                if b == 64 and r == 200:
                    mouse_click(x + 530, y + 440, wait=0)
                    break

                # orange coin
                if b == 33 and r == 231:
                    mouse_click(x + 530, y + 440, wait=0)
                    break

                # grey coin
                if b == 230 and r == 230:
                    mouse_click(x + 535, y + 440, wait=0)
                    break
    print("KONIEC GRY")
    start()


def start():
    print("Page UP by rozpocząć,naciśnij dopiero gdy będzie odliczanie")
    keyboard.wait("page up")
    a=1
    coinclick(a)
    

start()
