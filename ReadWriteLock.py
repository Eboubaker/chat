import threading


class ReadWriteLock:
	""" A lock object that allows many simultaneous "read locks", but only one "write lock." """

	def __init__(self):
		self._read_ready = threading.Condition(threading.Lock())
		self._readers = 0
		self.writer = None

	def acquire_read(self):
		"""
		Acquire a read lock. Blocks only if a another thread has acquired the write lock.
		"""
		if self.writer == threading.current_thread().ident:
			return
		self._read_ready.acquire()
		try:
			self._readers += 1
		finally:
			self._read_ready.release()

	def release_read(self):
		"""
		Release a read lock if exists
		"""
		if self.writer == threading.current_thread().ident:
			return
		self._read_ready.acquire()
		try:
			self._readers -= 1
			if not self._readers:
				self._read_ready.notifyAll()
		finally:
			self._read_ready.release()

	def acquire_write(self):
		"""
		Acquire a write lock. Blocks until there are no acquired read or write locks from another thread.
		"""
		if self.writer == threading.current_thread().ident:
			return
		self._read_ready.acquire()
		while self._readers > 0:
			self._read_ready.wait()
		self.writer = threading.current_thread().ident

	def release_write(self):
		"""
		Release a write lock if exists.
		"""
		if not self.writer:
			return
		self._read_ready.release()
		self.writer = None
