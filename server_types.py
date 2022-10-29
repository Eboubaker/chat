import random
import socket as sockets
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import List, Union, Optional

from termcolor import colored

from BufferedSocketStream import BufferedSocketStream
from SelfThreadAwareReadWriteLock import SelfThreadAwareReadWriteLock
from lib import thread_print


class DisconnectedError(Exception):
    pass


class User:
    def __init__(self, senders: ThreadPoolExecutor, socket: sockets.socket, username=None):
        self.socket = socket
        self.socket_lock = SelfThreadAwareReadWriteLock()
        self.name = username if username is not None else 'user-' + str(random.randint(1, 9999))
        self.senders = senders

    def join_group(self, group):
        group.join_user(self)

    def send_bytes_async(self, data: bytes):
        return self.senders.submit(user_send, self, data)

    def send_bytes(self, data: bytes):
        with self.socket_lock.for_write():
            self.socket.send(data)


class ServerUser(User):
    def __init__(self, system_user, senders: ThreadPoolExecutor, socket: sockets.socket = None, username=None):
        super().__init__(senders, socket, username)
        self.groups = []
        self.system_user = system_user
        self.ban_list: List[ServerUser] = []

    def send_system_message_async(self, message: str):
        self.send_bytes_async(
            ServerMessage.to_client(
                target_context=ServerMessage.CONTEXT_USER,
                sender_context=ServerMessage.CONTEXT_SYSTEM,
                sender=self.system_user,
                target=self,
                content=message,
                report=True,
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
                report=True,
            )
        )


class Invite:
    def __init__(self, user: ServerUser, invited_by: ServerUser):
        self.user = user
        self.invited_by = invited_by


class Group:
    def __init__(self, name: str, system_user: ServerUser, senders: ThreadPoolExecutor):
        self.users: List[ServerUser] = []
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

    def join_user(self, user: ServerUser, report: str):
        assert user not in self.users, "can't join two times"
        self.users.append(user)
        user.groups.append(self)
        self.send_bytes_async(
            ServerMessage.to_client(
                target_context=ServerMessage.CONTEXT_GROUP,
                sender_context=ServerMessage.CONTEXT_SYSTEM,
                sender=self.system_user,
                target=self,
                content=report,
                report=True,
            )
        )

    def remove_user(self, user: ServerUser, report: str):
        assert user in self.users, "remove_user: user not joined"
        self.users.remove(user)
        user.groups.remove(self)
        if len(self.users) > 0:
            self.send_bytes_async(
                ServerMessage.to_client(
                    target_context=ServerMessage.CONTEXT_GROUP,
                    sender_context=ServerMessage.CONTEXT_SYSTEM,
                    sender=self.system_user,
                    target=self,
                    content=report,
                    report=True,
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
                        report=True,
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
                report=True,
            )
        )


def group_send(grp: Group, usr: ServerUser, dt: bytes):
    try:
        usr.send_bytes(dt)
    except BaseException as e:
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
        target: str,
        content: str,
    ):
        data = bytearray()
        data.extend(ServerMessage.SIG_BYTES)
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


def report_send(target_context: int,
                sender_context: int,
                sender: Union[User, Group],
                target: Union[User, Group],
                content: str):
    print(f"{colored('sending message :', 'cyan')} sender:{(sender.name if sender else 'null').ljust(10)},sender_ctx={int_context_str(sender_context).ljust(10)},target_ctx={int_context_str(target_context).ljust(10)},target={(target.name if target else 'null').ljust(10)},content={(content[:15] + '...(truncated)') if len(content) > 15 else content}")


def report_receive(target_context: int,
                   sender: Optional[User],
                   target: str,
                   content: str):
    print(f"{colored('received message:', 'green')} sender:{sender.name.ljust(10)},sender_ctx={'USER'.ljust(10)},target_ctx={int_context_str(target_context).ljust(10)},target={target.ljust(10)},content={(content[:15] + '...(truncated)') if len(content) > 15 else content}")


class ServerMessage(Message):
    target_context: int
    target: Optional[Union[ServerUser, Group]]
    target_str: str
    content: str
    sig: int

    @staticmethod
    def to_client(
        target_context: int,
        sender_context: int,
        sender: Union[ServerUser, Group],
        target: Union[ServerUser, Group],
        content: str,
        report: bool
    ):
        if report:
            report_send(target_context, sender_context, sender, target, content)
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
    def from_client(reader: BufferedSocketStream, report_from: User = None):
        msg = ServerMessage()
        msg.sig = reader.read(2)
        assert msg.sig == ServerMessage.SIG_BYTES, f"Invalid message signature {msg.sig}"
        msg.target_context = int.from_bytes(reader.read(1), byteorder='little')
        msg.target_str = reader.read(int.from_bytes(reader.read(1), byteorder='little')).decode('utf-8')
        msg.content = reader.read(int.from_bytes(reader.read(2), byteorder='little')).decode('utf-8')
        if report_from:
            report_receive(
                target_context=msg.target_context,
                sender=report_from,
                target=msg.target_str,
                content=msg.content,
            )
        assert msg.target_context == ServerMessage.CONTEXT_GROUP or msg.target_context == ServerMessage.CONTEXT_USER, f"target can only be CONTEXT_USER or CONTEXT_GROUP got {msg.target_context}"
        return msg

    def __str__(self):
        return 'ServerMessage{' + f'SENDER_CONTEXT={int_context_str(self.sender_context)},TARGET_CONTEXT={int_context_str(self.target_context)},TARGET={self.target},CONTENT={self.content}' + '}'


def int_context_str(context: int):
    if context == Message.CONTEXT_USER:
        return 'USER'
    elif context == Message.CONTEXT_GROUP:
        return 'GROUP'
    elif context == Message.CONTEXT_SYSTEM:
        return 'SYSTEM'
    return 'UNKNOWN'


def user_send(usr: ServerUser, dt: bytes):
    try:
        usr.send_bytes(dt)
    except BaseException:
        thread_print(f"send bytes to user {usr.name} failed, bytes: {dt.decode('utf-8')}, cause: {traceback.format_exc()}")


class ClientUser(User):
    target: str
    chat_target: str
    target_context: int

    def __init__(self, senders: ThreadPoolExecutor, socket: sockets.socket = None, username=None):
        super().__init__(senders, socket, username)


def parse_args(argv: List[str]):
    args = {}  # Dict[str, str]
    for arg in argv:
        try:
            k, v = arg.split('=')
            args[k] = v
        except ValueError:
            print(f"option without value: {arg} use option=value syntax")
    return args
