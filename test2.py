import _thread
import random
import sys
import time
from threading import Thread

from cli_io import IO

io = IO()

def cls():
    time.sleep(3)
    sys.stdin.close()

