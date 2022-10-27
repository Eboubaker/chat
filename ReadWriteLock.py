import threading


class ReadWriteLock:
    """ A lock object that allows many simultaneous "read locks", but only one "write lock." """

    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0
        self.writer = None  # current writer
        self.with_ops_write = []  # stack for 'with' keyword for write or read ops, 0 for read 1 for write
        self.ops_arr_lock = threading.Lock()

    def for_read(self):
        """
        used for 'with' block
        """
        with self.ops_arr_lock:
            self.with_ops_write.append(0)
        return self

    def for_write(self):
        """
        used for 'with' block
        """
        with self.ops_arr_lock:
            self.with_ops_write.append(1)
        return self

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

    def __enter__(self):
        with self.ops_arr_lock:
            if len(self.with_ops_write) == 0:
                raise RuntimeError("ReadWriteLock: used 'with' block without call to for_read or for_write")
        with self.ops_arr_lock:
            write = self.with_ops_write[-1]
        if write:
            self.acquire_write()
        else:
            self.acquire_read()

    def __exit__(self, exc_type, exc_value, tb):
        with self.ops_arr_lock:
            write = self.with_ops_write.pop()
        if write:
            self.release_write()
        else:
            self.release_read()
        if exc_type is not None:
            return False  # exception happened
        return True
