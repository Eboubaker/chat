import random
import socket as sockets
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
            ServerMessage.to_client(
                target_context=ServerMessage.CONTEXT_USER,
                sender_context=ServerMessage.CONTEXT_SYSTEM,
                sender=self.system_user,
                target=self,
                content=message,
            )
        )

    def send_system_message(self, message: str):
        self.send_bytes(
            ServerMessage.to_client(
                target_context=ServerMessage.CONTEXT_USER,
                sender_context=ServerMessage.CONTEXT_SYSTEM,
                sender=self.system_user,
                target=self,
                content=message,
            )
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
        self.send_system_message_async("group is now open for invites")

    def lock(self):
        self.locked = True
        self.send_system_message_async("group invites are now locked")

    def send_bytes_async(self, data: bytes):
        for user in self.users:
            self.senders.submit(group_send, self, user, data)

    def join_user(self, user: User):
        if user not in self.users:
            self.users.append(user)
            user.groups.append(self)
        self.send_bytes_async(
            ServerMessage.to_client(
                target_context=ServerMessage.CONTEXT_GROUP,
                sender_context=ServerMessage.CONTEXT_SYSTEM,
                sender=self.system_user,
                target=self,
                content=f"{self.name} has entered the group",
            )
        )

    def remove_user(self, user: User):
        assert user in self.users, "remove_user: user not joined"
        self.users.remove(user)
        if len(self.users) > 0:
            self.send_bytes_async(
                ServerMessage.to_client(
                    target_context=ServerMessage.CONTEXT_GROUP,
                    sender_context=ServerMessage.CONTEXT_SYSTEM,
                    sender=self.system_user,
                    target=self,
                    content=f"{user.name} has left the group",
                )
            )
            if self.admin == user:
                self.admin = self.users[0]
                self.send_bytes_async(
                    ServerMessage.to_client(
                        target_context=ServerMessage.CONTEXT_GROUP,
                        sender_context=ServerMessage.CONTEXT_SYSTEM,
                        sender=self.system_user,
                        target=self,
                        content=f"{self.admin.name} is now the group admin",
                    )
                )

    def send_system_message_async(self, message: str):
        self.send_bytes_async(
            ServerMessage.to_client(
                target_context=ServerMessage.CONTEXT_GROUP,
                sender_context=ServerMessage.CONTEXT_SYSTEM,
                sender=self.system_user,
                target=self,
                content=message,
            )
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


class ClientMessage(Message):
    target_context: int
    sender_context: int
    sender: str
    target: str
    content: str
    sig: int

    @staticmethod
    def to_server(
        target_context: int,
        sender_context: int,
        target: str,
        content: str,
    ):
        data = bytearray()
        data.extend(ServerMessage.SIG_BYTES)
        data.extend(sender_context.to_bytes(length=1, byteorder='little'))
        data.extend(target_context.to_bytes(length=1, byteorder='little'))
        target_bytes = target.encode('utf-8')
        data.extend(len(target_bytes).to_bytes(length=1, byteorder='little'))
        data.extend(target_bytes)
        content_bytes = content.encode('utf-8')
        data.extend(len(content_bytes).to_bytes(length=2, byteorder='little'))
        data.extend(content_bytes)
        return data

    @staticmethod
    def from_server(reader: BufferedSocketStream):
        msg = ClientMessage()
        msg.sig = reader.read(2)
        assert msg.sig == ServerMessage.SIG_BYTES, f"Invalid message signature {msg.sig}"
        msg.sender_context = int.from_bytes(reader.read(1), byteorder='little')
        msg.target_context = int.from_bytes(reader.read(1), byteorder='little')
        msg.sender = reader.read(int.from_bytes(reader.read(1), byteorder='little')).decode('utf-8')
        msg.target = reader.read(int.from_bytes(reader.read(1), byteorder='little')).decode('utf-8')
        assert msg.sender_context == ServerMessage.CONTEXT_USER or msg.sender_context == ServerMessage.CONTEXT_SYSTEM, \
            "sender can only be CONTEXT_USER or CONTEXT_SYSTEM"
        assert msg.target_context == ServerMessage.CONTEXT_GROUP or msg.target_context == ServerMessage.CONTEXT_USER, f"target can only be CONTEXT_USER or CONTEXT_GROUP got {msg.target_context}"
        msg.content = reader.read(int.from_bytes(reader.read(2), byteorder='little')).decode('utf-8')
        return msg

    def __str__(self):
        return 'ClientMessage{' + f'SENDER_CONTEXT={int_context_str(self.sender_context)},TARGET_CONTEXT={int_context_str(self.target_context)},SENDER={self.sender},TARGET={self.target},CONTENT={self.content}' + '}'


class ServerMessage(Message):
    target_context: int
    sender_context: int
    target: Union[User, Group]
    content: str
    sig: int

    @staticmethod
    def to_client(
        target_context: int,
        sender_context: int,
        sender: Union[User, Group],
        target: Union[User, Group],
        content: str,
    ):
        data = bytearray()
        data.extend(ServerMessage.SIG_BYTES)
        data.extend(sender_context.to_bytes(length=1, byteorder='little'))
        data.extend(target_context.to_bytes(length=1, byteorder='little'))
        uname_bytes = sender.name.encode('utf-8')
        data.extend(len(uname_bytes).to_bytes(length=1, byteorder='little'))
        data.extend(uname_bytes)
        target_bytes = target.name.encode('utf-8')
        data.extend(len(target_bytes).to_bytes(length=1, byteorder='little'))
        data.extend(target_bytes)
        content_bytes = content.encode('utf-8')
        data.extend(len(content_bytes).to_bytes(length=2, byteorder='little'))
        data.extend(content_bytes)
        return data

    @staticmethod
    def from_client(reader: BufferedSocketStream, state_lock: ReadWriteLock, users: List[User],
                    groups: List[Group]):
        msg = ServerMessage()
        msg.sig = reader.read(2)
        assert msg.sig == ServerMessage.SIG_BYTES, f"Invalid message signature {msg.sig}"
        msg.sender_context = int.from_bytes(reader.read(1), byteorder='little')
        msg.target_context = int.from_bytes(reader.read(1), byteorder='little')
        target = reader.read(int.from_bytes(reader.read(1), byteorder='little')).decode('utf-8')
        assert msg.sender_context == ServerMessage.CONTEXT_USER or msg.sender_context == ServerMessage.CONTEXT_SYSTEM, \
            "sender can only be CONTEXT_USER or CONTEXT_SYSTEM"
        assert msg.target_context == ServerMessage.CONTEXT_GROUP or msg.target_context == ServerMessage.CONTEXT_USER, f"target can only be CONTEXT_USER or CONTEXT_GROUP got {msg.target_context}"
        state_lock.acquire_read()
        msg.target = None
        try:
            for group in groups:
                if group.name == target:
                    msg.target = group
                    break
            if not msg.target:
                for user in users:
                    if user.name == target:
                        msg.target = user
                        break
            assert msg.target, "ServerMessage without target"
        finally:
            state_lock.release_read()
        msg.content = reader.read(int.from_bytes(reader.read(2), byteorder='little')).decode('utf-8')
        return msg

    def __str__(self):
        return 'ServerMessage{' + f'SENDER_CONTEXT={int_context_str(self.sender_context)},TARGET_CONTEXT={int_context_str(self.target_context)},TARGET={self.target},CONTENT={self.content}' + '}'


def int_context_str(context: int):
    if context == ServerMessage.CONTEXT_USER:
        return 'USER'
    elif context == ServerMessage.CONTEXT_GROUP:
        return 'GROUP'
    elif context == ServerMessage.CONTEXT_SYSTEM:
        return 'SYSTEM'
    return 'UNKNOWN'


def user_send(usr: User, dt: bytes):
    try:
        usr.send_bytes(dt)
    except Exception as e:
        if usr.print_network:
            thread_print(f"user {usr.name} send fail cause: {str(e)} data {dt.decode('utf-8')}")


class ClientUser(User):
    target: str
    chat_target: str
    target_context: int

    def __init__(self, system_user, senders: ThreadPoolExecutor, socket: sockets.socket = None, username=None):
        super().__init__(system_user, senders, socket, username)
