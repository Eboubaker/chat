import os
import sys
import threading
import traceback
from typing import List, Optional

from readchar import readkey
from termcolor import colored

from ReentrantRWLock import ReentrantRWLock


class ReadError(IOError):
    pass


class IO:
    def __init__(self):
        self.read_buffer = ''
        self.label = ''
        self.label_colored = ''
        self.read_lock = threading.Lock()
        self.write_lock = threading.RLock()
        self.buffer_lock = ReentrantRWLock()
        self.last_line = ''
        self.last_writer_was_reader = False
        self.read_interrupted_buffer = ''
        self.label_color = 'white'
        self.history: List[str] = []
        self.history_tail_index = 0
        self.read_error: Optional[ReadError] = None
        self.read_interrupted = False
        self.cursor_at = 0

    def update_input_label(self, label):
        self.label = label
        self.label_colored = colored(self.label, self.label_color)
        if self.read_lock.locked():
            self.__write_input()

    def __clear_input(self):
        with self.write_lock:
            sys.stdout.write('\r')
            sys.stdout.write(''.join(' ' for _ in range(len(self.last_line))))
            sys.stdout.write('\r')
            self.last_line = ''
            sys.stdout.flush()

    def __move_cursor(self, txt: str, at: int):
        with self.write_lock:
            sys.stdout.write('\r')
            sys.stdout.write(txt[:at])
            sys.stdout.flush()

    def __write_input(self, append=''):
        with self.write_lock:
            self.__clear_input()
            with self.buffer_lock.for_read():
                self.last_line = self.label_colored + self.read_buffer + append
                sys.stdout.write(self.last_line)
                self.__move_cursor(self.last_line, self.cursor_at + len(self.label_colored))
                self.last_writer_was_reader = True

    def update_input_label_color(self, color):
        self.label_color = color
        self.label_colored = colored(self.label, self.label_color)
        if self.read_lock.locked():
            self.__write_input()

    def __command_left_key(self):
        with self.write_lock:
            if self.cursor_at > 0:
                self.cursor_at -= 1
                self.__move_cursor(self.last_line, self.cursor_at + len(self.label_colored))

    def __command_right_key(self):
        with self.write_lock:
            if self.cursor_at < len(self.last_line) - len(self.label_colored):
                self.cursor_at += 1
                self.__move_cursor(self.last_line, self.cursor_at + len(self.label_colored))

    def __command_up_key(self):
        with self.write_lock:
            if self.history_tail_index > 0:
                self.history_tail_index -= 1
                self.update_input_buffer(self.history[self.history_tail_index])

    def __command_down_key(self):
        with self.write_lock:
            if len(self.history) - 1 > self.history_tail_index:
                self.history_tail_index += 1
                self.update_input_buffer(self.history[self.history_tail_index])

    def __command_delete_key(self):
        with self.write_lock:
            if self.cursor_at < len(self.read_buffer):
                # delete char after cursor
                self.read_buffer = self.read_buffer[:self.cursor_at] + self.read_buffer[self.cursor_at + 1:]
                self.__write_input()

    if os.name == 'nt':
        def handle_stroke(self, char):
            with self.buffer_lock.for_read():
                if char == '\x00H':
                    self.__command_up_key()
                elif char == '\x00P':
                    self.__command_down_key()
                else:
                    # TODO: modify the code and handle it by yourself...
                    self.write(f"unhandled control: {char.encode('utf-8')}")
    elif os.name == 'posix':
        def handle_stroke(self, char):
            with self.buffer_lock.for_read():
                if char == '\x1b[A':  # up
                    self.__command_up_key()
                elif char == '\x1b[B':  # bottom
                    self.__command_down_key()
                elif char == '\x1b[D':  # left
                    self.__command_left_key()
                elif char == '\x1b[C':  # right
                    self.__command_right_key()
                elif char == '\x1b[3~':  # right
                    self.__command_delete_key()
                else:
                    # TODO: modify the code and handle it by yourself...
                    self.write(f"unhandled control: {char.encode('utf-8')}")

    def thread_read(self):
        self.__write_input()
        try:
            while True:
                try:
                    char = readkey()
                except KeyboardInterrupt:
                    with self.buffer_lock.for_read():
                        self.read_interrupted_buffer = self.read_buffer
                        self.read_interrupted = True
                    self.__clear_input()
                    break
                # self.write(char.encode('utf-8'))
                if len(char) > 1:
                    self.handle_stroke(char)
                    continue
                delchr = ord(char) == 8 or ord(char) == 127
                if delchr:
                    with self.buffer_lock.for_write():
                        if len(self.read_buffer) != 0 and self.cursor_at > 0:
                            # delete char before cursor
                            self.read_buffer = self.read_buffer[:self.cursor_at - 1] + self.read_buffer[self.cursor_at:]
                            self.cursor_at -= 1
                            self.__write_input()
                    continue
                line_feed = char == '\n' or char == '\r'
                read_interrupted = ord(char) == 3

                if line_feed or read_interrupted:
                    self.__clear_input()
                    if read_interrupted:
                        with self.buffer_lock.for_read():
                            self.read_interrupted_buffer = self.read_buffer
                        self.read_interrupted = True
                    break
                if ord(char) <= 31:
                    continue  # control character
                with self.write_lock:
                    with self.buffer_lock.for_write():
                        self.read_buffer = self.read_buffer[:self.cursor_at] + char + self.read_buffer[self.cursor_at:]
                        self.cursor_at += 1
                    self.__write_input()
        except BaseException:
            self.read_error = traceback.format_exc()
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
            self.cursor_at = 0
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
                raise ReadError(err)
            return v
