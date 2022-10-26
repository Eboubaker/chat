import socket as sockets


class BufferedSocketStream:
	def __init__(self, socket: sockets.socket):
		self.socket = socket
		self.buffer = bytearray()
		self.size = 0

	def read(self, count) -> bytes:
		"""
		block until "count" bytes are available and return them
		"""
		while True:
			if count <= self.size:
				part = self.buffer[:count]
				self.buffer = self.buffer[count:]
				self.size -= count
				return part
			received = self.socket.recv(64 * 1024)
			self.buffer.extend(received)
			self.size += len(received)
