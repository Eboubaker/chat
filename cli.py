import curses
from curses import wrapper


def main(screen: curses.window):
    # Clear screen
    screen.clear()
    pad = curses.newpad(900000, 26)
    screen.refresh()
    for i in range(100):
        for j in range(26):
            char = chr(65 + j)
            pad.addstr(char)
    pad.refresh(0, 5, 3, 0, 5, 5)
    ch = screen.getkey()


wrapper(main)
