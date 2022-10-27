import time
from threading import Thread

from cli_io import IO

buffer = {'value': '', 'is_read_pending': True}
label = 'input: '

io = IO()


def writer():
    i = 12
    while True:
        io.write(i)
        time.sleep(.4)
        i += 1


t = Thread(target=writer)
t.daemon = True
t.start()
print("welcome", io.input("your name: "))
