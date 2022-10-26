import os
import sys
import threading

from readchar import readchar

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
		self.last_wrote_was_reader = False
		self.read_interrupted = False

	def thread_read(self):
		try:
			self.read_pending = True
			self.write_lock.acquire()
			self.last_line = self.label
			sys.stdout.write(self.last_line)
			sys.stdout.flush()
			self.last_wrote_was_reader = True
			self.write_lock.release()
			while True:
				char = readchar()
				delchr = ord(char) == 8 or ord(char) == 127
				line_feed = char == '\n' or char == '\r'
				if delchr:
					self.buffer_lock.acquire_write()
					if len(self.read_buffer) != 0:
						self.read_buffer = self.read_buffer[:-1]
					self.buffer_lock.release_write()
				self.write_lock.acquire()

				sys.stdout.write('\r')
				sys.stdout.write(''.join(' ' for _ in range(len(self.last_line))))
				sys.stdout.write('\r')
				self.buffer_lock.acquire_read()
				self.last_line = self.label + self.read_buffer
				sys.stdout.write(self.last_line)
				sys.stdout.flush()
				self.last_wrote_was_reader = True
				self.buffer_lock.release_read()
				self.write_lock.release()
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
				self.buffer_lock.acquire_write()
				self.read_buffer += char
				self.buffer_lock.release_write()
		finally:
			self.read_pending = False

	def write(self, txt: object, new_line=True):
		txt = str(txt)
		self.write_lock.acquire()
		if self.read_pending:
			sys.stdout.write('\r')
			sys.stdout.write(''.join(' ' for _ in range(len(self.last_line))))
			sys.stdout.write('\r')
			sys.stdout.write(txt)
			if new_line:
				sys.stdout.write('\n')
			self.buffer_lock.acquire_read()
			self.last_line = self.label + self.read_buffer
			sys.stdout.write(self.last_line)
			sys.stdout.flush()
			self.buffer_lock.release_read()
		else:
			sys.stdout.write(txt)
			if new_line:
				sys.stdout.write('\n')
			sys.stdout.flush()
			self.last_line = ''
		self.last_wrote_was_reader = False
		self.write_lock.release()

	def input(self, label: str):
		self.read_lock.acquire()
		try:
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
		finally:
			self.read_lock.release()

