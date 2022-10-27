import sys
import threading

from readchar import readchar
from termcolor import colored

from ReadWriteLock import ReadWriteLock


class IO:
    def __init__(self):
        self.read_buffer = ''
        self.label = ''
        self.read_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.buffer_lock = ReadWriteLock()
        self.last_line = ''
        self.read_pending = False
        self.last_writer_was_reader = False
        self.read_interrupted = False
        self.label_color = 'white'

    def update_input_label(self, label):
        with self.write_lock:
            self.label = label
            if self.read_pending:
                self.__write_input()

    def __write_input(self, append=''):
        sys.stdout.write('\r')
        sys.stdout.write(''.join(' ' for _ in range(len(self.last_line))))
        sys.stdout.write('\r')
        with self.buffer_lock.for_read():
            self.last_line = colored(self.label, self.label_color) + self.read_buffer + append
            sys.stdout.write(self.last_line)
            sys.stdout.flush()
            self.last_writer_was_reader = True

    def update_input_label_color(self, color):
        with self.write_lock:
            self.label_color = color
            if self.read_pending:
                self.__write_input()

    def thread_read(self):
        try:
            self.read_pending = True
            with self.write_lock:
                self.last_line = self.read_buffer
                sys.stdout.write(self.last_line)
                sys.stdout.flush()
                self.last_writer_was_reader = True
            while True:
                char = readchar()
                delchr = ord(char) == 8 or ord(char) == 127
                if delchr:
                    with self.buffer_lock.for_write():
                        if len(self.read_buffer) != 0:
                            self.read_buffer = self.read_buffer[:-1]
                line_feed = char == '\n' or char == '\r'
                with self.write_lock:
                    self.__write_input(char)
                if delchr:
                    continue
                if line_feed:
                    sys.stdout.write(char)
                    sys.stdout.flush()
                    break
                if ord(char) == 3:
                    print()
                    self.read_interrupted = True
                    break
                if ord(char) <= 31:
                    continue  # control character
                with self.buffer_lock.for_write():
                    self.read_buffer += char
        finally:
            self.read_pending = False

    def write(self, txt: object, new_line=True):
        txt = str(txt)
        with self.write_lock:
            if self.read_pending:
                sys.stdout.write('\r')
                sys.stdout.write(''.join(' ' for _ in range(len(self.last_line))))
                sys.stdout.write('\r')
                sys.stdout.write(txt)
                if new_line:
                    sys.stdout.write('\n')
                with self.buffer_lock.for_read():
                    self.last_line = self.label + self.read_buffer
                    sys.stdout.write(self.last_line)
                    sys.stdout.flush()
            else:
                sys.stdout.write(txt)
                if new_line:
                    sys.stdout.write('\n')
                sys.stdout.flush()
                self.last_line = ''
            self.last_writer_was_reader = False

    def input(self, label: str = None):
        with self.read_lock:
            if label is not None:
                self.label = label
            t = threading.Thread(target=self.thread_read)
            t.daemon = True
            t.start()
            t.join()
            if self.read_interrupted:
                raise KeyboardInterrupt()
            v = self.read_buffer
            self.read_buffer = ''
            return v
