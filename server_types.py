import random
import socket as sockets
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Union

from BufferedSocketStream import BufferedSocketStream
from ReadWriteLock import ReadWriteLock
from lib import thread_print


class User:
	def __init__(self, system_user, senders: ThreadPoolExecutor, socket: sockets.socket = None, username=None):
		self.socket = socket
		self.groups = []
		self.socket_lock = ReadWriteLock()
		self.name = username if username is not None else 'user-' + str(random.randint(1, 9999))
		self.system_user = system_user
		self.senders = senders
		self.print_network = False

	def join_group(self, group):
		group.join_user(self)

	def send_bytes(self, data: bytes):
		self.socket_lock.acquire_write()
		if self.print_network:
			thread_print(f"sending to user {self.name} socket bytes f{data}")
		try:
			self.socket.send(data)
		finally:
			self.socket_lock.release_write()

	def send_bytes_async(self, data: bytes):
		return self.senders.submit(user_send, self, data)

	def send_system_message_async(self, message: str):
		self.send_bytes_async(
			Message.new(
				target_context=Message.CONTEXT_USER,
				sender_context=Message.CONTEXT_SYSTEM,
				sender=self.system_user,
				target=self,
				content=message,
			).to_bytes()
		)

	def send_system_message(self, message: str):
		self.send_bytes(
			Message.new(
				target_context=Message.CONTEXT_USER,
				sender_context=Message.CONTEXT_SYSTEM,
				sender=self.system_user,
				target=self,
				content=message,
			).to_bytes()
		)


class Invite:
	def __init__(self, user: User, invited_by: User):
		self.user = user
		self.invited_by = invited_by


class Group:
	def __init__(self, name: str, system_user: User, senders: ThreadPoolExecutor):
		self.users = []
		self.admin = None
		self.name = name
		self.locked = False
		self.pending_invites: List[Invite] = []
		self.senders = senders
		self.system_user = system_user

	def unlock(self):
		self.locked = False
		self.send_system_message("group is now open for invites")

	def lock(self):
		self.locked = True
		self.send_system_message("group invites are now locked")

	def send_bytes_async(self, data: bytes):
		for user in self.users:
			self.senders.submit(group_send, self, user, data)

	def join_user(self, user: User):
		if user not in self.users:
			self.users.append(user)
			user.groups.append(self)
		self.send_bytes_async(
			Message.new(
				target_context=Message.CONTEXT_GROUP,
				sender_context=Message.CONTEXT_SYSTEM,
				sender=self.system_user,
				target=self,
				content=f"{self.name} has entered the group",
			).to_bytes()
		)

	def remove_user(self, user: User):
		assert user in self.users, "remove_user: user not joined"
		self.users.remove(user)
		if len(self.users) > 0:
			self.send_bytes_async(
				Message.new(
					target_context=Message.CONTEXT_GROUP,
					sender_context=Message.CONTEXT_SYSTEM,
					sender=self.system_user,
					target=self,
					content=f"{user.name} has left the group",
				).to_bytes()
			)
			if self.admin == user:
				self.admin = self.users[0]
				self.send_bytes_async(
					Message.new(
						target_context=Message.CONTEXT_GROUP,
						sender_context=Message.CONTEXT_SYSTEM,
						sender=self.system_user,
						target=self,
						content=f"{self.admin.name} is now the group admin",
					).to_bytes()
				)

	def send_system_message(self, message: str):
		self.send_bytes_async(
			Message.new(
				target_context=Message.CONTEXT_GROUP,
				sender_context=Message.CONTEXT_SYSTEM,
				sender=self.system_user,
				target=self,
				content=message,
			).to_bytes()
		)


def group_send(grp: Group, usr: User, dt: bytes):
	try:
		usr.send_bytes(dt)
	except Exception as e:
		thread_print(f"group {grp.name} send fail to user {usr.name} cause {str(e)} data: {dt.decode('utf-8')}")


class Message:
	CONTEXT_USER = 1  # private
	CONTEXT_GROUP = 2  # group
	CONTEXT_SYSTEM = 3  # system

	SIG_BYTES = (65136).to_bytes(length=2, byteorder='little')

	target_context: int
	sender_context: int
	sender: User
	target: Union[User, Group]
	content: str
	sig: int

	@staticmethod
	def new(
		target_context: int,
		sender_context: int,
		sender: User,
		target: Union[User, Group],
		content: str,
	):
		msg = Message()
		msg.target_context = target_context
		msg.sender_context = sender_context
		msg.sender = sender
		msg.target = target
		msg.content = content
		msg.time_ns = time.time_ns()
		msg.time = time.time()
		msg.sig = Message.SIG_BYTES
		return msg

	def to_bytes(self):
		data = bytearray()
		data.extend(Message.SIG_BYTES)
		data.extend(self.sender_context.to_bytes(length=1, byteorder='little'))
		data.extend(self.target_context.to_bytes(length=1, byteorder='little'))
		uname_bytes = self.sender.name.encode('utf-8')
		data.extend(len(uname_bytes).to_bytes(length=1, byteorder='little'))
		data.extend(uname_bytes)
		target_bytes = self.target.name.encode('utf-8')
		data.extend(len(target_bytes).to_bytes(length=1, byteorder='little'))
		data.extend(target_bytes)
		content_bytes = self.content.encode('utf-8')
		data.extend(len(content_bytes).to_bytes(length=2, byteorder='little'))
		data.extend(content_bytes)
		return data

	@staticmethod
	def read_from_stream(reader: BufferedSocketStream, state_lock: ReadWriteLock, users: List[User] = None,
						 groups: List[Group] = None, print=True):
		msg = Message()
		msg.sig = reader.read(2)
		assert msg.sig == Message.SIG_BYTES, f"Invalid message signature {msg.sig}"
		msg.sender_context = int.from_bytes(reader.read(1), byteorder='little')
		msg.target_context = int.from_bytes(reader.read(1), byteorder='little')
		sender = reader.read(int.from_bytes(reader.read(1), byteorder='little')).decode('utf-8')
		target = reader.read(int.from_bytes(reader.read(1), byteorder='little')).decode('utf-8')
		assert msg.sender_context == Message.CONTEXT_USER or msg.sender_context == Message.CONTEXT_SYSTEM, \
			"sender can only be CONTEXT_USER or CONTEXT_SYSTEM"
		assert msg.target_context == Message.CONTEXT_GROUP or msg.target_context == Message.CONTEXT_USER, "target can only be CONTEXT_USER or CONTEXT_GROUP"
		state_lock.acquire_read()
		msg.target = None
		msg.sender = None
		try:
			if users is not None:
				for user in users:
					if user.name == sender:
						msg.sender = user
						break
			else:
				msg.sender = sender
			if groups is not None:
				for group in groups:
					if group.name == target:
						msg.target = group
						break
				if not msg.target:
					if users is None:
						msg.target = target
					else:
						for user in users:
							if user.name == target:
								msg.target = user
								break
			else:
				msg.target = target
		finally:
			state_lock.release_read()
		msg.content = reader.read(int.from_bytes(reader.read(2), byteorder='little')).decode('utf-8')
		if print:
			thread_print(f"received message f{msg}")
		return msg

	def __str__(self):
		return 'Message{' + f'SENDER_CONTEXT={int_context_str(self.sender_context)},TARGET_CONTEXT={int_context_str(self.target_context)},SENDER={self.sender},TARGET={self.target},CONTENT={self.content}' + '}'


def int_context_str(context: int):
	if context == Message.CONTEXT_USER:
		return 'USER'
	elif context == Message.CONTEXT_GROUP:
		return 'GROUP'
	elif context == Message.CONTEXT_SYSTEM:
		return 'SYSTEM'
	return 'UNKNOWN'


def user_send(usr: User, dt: bytes):
	try:
		usr.send_bytes(dt)
	except Exception as e:
		if usr.print_network:
			thread_print(f"user {usr.name} send fail cause: {str(e)} data {dt.decode('utf-8')}")


class ClientUser(User):
	target: Union[Group, User]
	target_context: int

	def __init__(self, system_user, senders: ThreadPoolExecutor, socket: sockets.socket = None, username=None):
		super().__init__(system_user, senders, socket, username)
