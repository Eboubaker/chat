import threading
from typing import List


class ReentrantRWLock:
    """
    A lock object that allows many simultaneous "read locks", but only one "write lock."
    it also ignores multiple write locks from the same thread
    """

    def __init__(self):
        super().__init__()
        self.writer = None  # current writer
        self.readers: List[int] = []
        self._read_ready = threading.Condition(threading.Lock())
        self.with_ops_write = []  # stack for 'with' keyword for write or read ops, 0 for read 1 for write
        self.ops_arr_lock = threading.Lock()

    def acquire_read(self):
        """
        Acquire a read lock. Blocks only if a another thread has acquired the write lock.
        """
        ident = threading.current_thread().ident
        if self.writer == ident or ident in self.readers:
            return
        with self._read_ready:
            self.readers.append(ident)

    def release_read(self):
        """
        Release a read lock if exists from this thread
        """
        ident = threading.current_thread().ident
        if self.writer == ident or ident not in self.readers:
            return
        with self._read_ready:
            self.readers.remove(ident)
            if len(self.readers) == 0:
                self._read_ready.notifyAll()

    def acquire_write(self):
        """
        Acquire a write lock. Blocks until there are no acquired read or write locks from another thread.
        """
        ident = threading.current_thread().ident
        if self.writer == ident:
            return
        self._read_ready.acquire()
        me_included = 1 if ident in self.readers else 0
        while len(self.readers) - me_included > 0:
            self._read_ready.wait()
        self.writer = ident

    def release_write(self):
        """
        Release a write lock if exists from this thread.
        """
        if not self.writer or not self.writer == threading.current_thread().ident:
            return
        self._read_ready.release()
        self.writer = None

    def __enter__(self):
        with self.ops_arr_lock:
            if len(self.with_ops_write) == 0:
                raise RuntimeError("ReentrantRWLock: used 'with' block without call to for_read or for_write")
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
