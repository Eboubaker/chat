import sys
import threading
from typing import List, Optional

from readchar import readkey
from termcolor import colored

from SelfThreadAwareReadWriteLock import SelfThreadAwareReadWriteLock

# Here are the various escape sequences we can capture
controls = {
    '\x0d': 'return',
    '\x7f': 'backspace',
    '\x08': 'backspace',
    '\x1b': 'escape',
    '\x01': 'ctrl+a',
    '\x02': 'ctrl+b',
    '\x03': 'ctrl+c',
    '\x04': 'ctrl+d',
    '\x05': 'ctrl+e',
    '\x06': 'ctrl+f',
    '\x1a': 'ctrl+z',
    '\x1b\x4f\x50': 'f1',
    '\x1b\x4f\x51': 'f2',
    '\x1b\x4f\x52': 'f3',
    '\x1b\x4f\x53': 'f4',
    '\x1b\x4f\x31\x35\x7e': 'f5',
    '\x1b\x4f\x31\x37\x7e': 'f6',
    '\x1b\x4f\x31\x38\x7e': 'f7',
    '\x1b\x4f\x31\x39\x7e': 'f8',
    '\x1b\x4f\x31\x30\x7e': 'f9',
    '\x1b\x4f\x31\x31\x7e': 'f10',
    '\x1b\x4f\x31\x33\x7e': 'f11',
    '\x1b\x4f\x31\x34\x7e': 'f12',
    '\x1b\x5b\x41': 'up',
    '\x1b\x5b\x42': 'down',
    '\x1b\x5b\x43': 'right',
    '\x1b\x5b\x44': 'left',
    '\x1b\x4f\x46': 'end',
    '\x1b\x4f\x48': 'home',
    '\x1b\x5b\x32\x7e': 'insert',
    '\x1b\x5b\x33\x7e': 'delete',
    '\x1b\x5b\x35\x7e': 'pageup',
    '\x1b\x5b\x36\x7e': 'pagedown',
}.items()


class ReadError(IOError):
    pass


class IO:
    def __init__(self):
        self.read_buffer = ''
        self.label = ''
        self.read_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.buffer_lock = SelfThreadAwareReadWriteLock()
        self.last_line = ''
        self.last_writer_was_reader = False
        self.read_interrupted_buffer = ''
        self.label_color = 'white'
        self.history: List[str] = []
        self.history_tail_index = 0
        self.read_error: Optional[ReadError] = None
        self.read_interrupted = False

    def update_input_label(self, label):
        self.label = label
        if self.read_lock.locked():
            self.__write_input()

    def __clear_input(self):
        sys.stdout.write('\r')
        sys.stdout.write(''.join(' ' for _ in range(len(self.last_line))))
        sys.stdout.write('\r')
        self.last_line = ''
        sys.stdout.flush()

    def __write_input(self, append=''):
        self.__clear_input()
        with self.buffer_lock.for_read():
            self.last_line = colored(self.label, self.label_color) + self.read_buffer + append
            sys.stdout.write(self.last_line)
            sys.stdout.flush()
            self.last_writer_was_reader = True

    def update_input_label_color(self, color):
        self.label_color = color
        if self.read_lock.locked():
            with self.write_lock:
                self.__write_input()

    def thread_read(self):
        with self.write_lock:
            self.__write_input()
        try:
            while True:
                try:
                    char = readkey()
                except KeyboardInterrupt:
                    with self.buffer_lock.for_read():
                        self.read_interrupted_buffer = self.read_buffer
                        self.read_interrupted = True
                    with self.write_lock:
                        self.__clear_input()
                    break

                if char[0] == '\x00':
                    if char == '\x00H':
                        if self.history_tail_index > 0:
                            self.history_tail_index -= 1
                            self.update_input_buffer(self.history[self.history_tail_index])
                    elif char == '\x00P':
                        if len(self.history) - 1 > self.history_tail_index:
                            self.history_tail_index += 1
                            self.update_input_buffer(self.history[self.history_tail_index])
                    else:
                        # TODO: modify the code and handle it by yourself...
                        self.write(f"unhandled control: {char.encode('utf-8')}")
                    continue

                delchr = ord(char) == 8 or ord(char) == 127
                if delchr:
                    with self.buffer_lock.for_write():
                        if len(self.read_buffer) != 0:
                            self.read_buffer = self.read_buffer[:-1]
                            with self.write_lock:
                                self.__write_input()
                            continue
                line_feed = char == '\n' or char == '\r'
                read_interrupted = ord(char) == 3

                if line_feed or read_interrupted:
                    with self.write_lock:
                        self.__clear_input()
                    if read_interrupted:
                        with self.buffer_lock.for_read():
                            self.read_interrupted_buffer = self.read_buffer
                        self.read_interrupted = True
                    break
                if ord(char) <= 31:
                    continue  # control character
                with self.write_lock:
                    self.__write_input(char)

                with self.buffer_lock.for_write():
                    self.read_buffer += char
        except BaseException as e:
            self.read_error = ReadError(e)
            return

    def write(self, txt: object, new_line=True):
        txt = str(txt)
        with self.write_lock:
            if self.read_lock.locked():
                self.__clear_input()
                sys.stdout.write(txt)
                sys.stdout.write('\n')
                with self.buffer_lock.for_read():
                    self.__write_input()
            else:
                sys.stdout.write(txt)
                if new_line:
                    sys.stdout.write('\n')
                sys.stdout.flush()
                self.last_line = ''
            self.last_writer_was_reader = False

    def update_input_buffer(self, txt: str):
        with self.buffer_lock.for_write():
            self.read_buffer = txt
        if self.read_lock.locked():
            with self.write_lock:
                self.__write_input()

    def interrupted_buffer(self):
        with self.buffer_lock.for_read():
            return self.read_interrupted_buffer

    def input(self, label: str = None, color=None, history=None):
        """"
        throws KeyboardInterrupt or ReadError
        """
        with self.read_lock:
            self.history = history or []
            self.history_tail_index = len(self.history)
            self.read_interrupted_buffer = ''
            self.read_interrupted = False
            if label is not None:
                self.update_input_label(label)
            if color is not None:
                self.update_input_label_color(color)
            t = threading.Thread(target=self.thread_read)
            t.daemon = True
            t.start()
            t.join()
            v = self.read_buffer
            self.read_buffer = ''
            if self.read_interrupted:
                self.read_interrupted = False
                raise KeyboardInterrupt()
            if self.read_error:
                err = self.read_error
                self.read_error = None
                raise err
            return v
