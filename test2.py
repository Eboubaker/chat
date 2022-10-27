import random
import time
from threading import Thread

from cli_io import IO

io = IO()


def x():
    i = 0
    while True:
        x = str(random.randint(0, 9))
        if i % 2 == 0:
            io.update_input_label_color('yellow')
        else:
            io.update_input_label_color('yellow')
        io.update_input_label('id-' + x + ': ')
        time.sleep(.1)
        i += 1


t = Thread(target=x)
t.daemon = True
# t.start()
n = io.input()
print(n)
