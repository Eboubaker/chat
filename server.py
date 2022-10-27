import socket as sockets
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from BufferedSocketStream import BufferedSocketStream
from ReadWriteLock import ReadWriteLock
from lib import soft_join, thread_print
from server_types import Invite, Group, ServerMessage, User

server_state_lock = ReadWriteLock()
senders = ThreadPoolExecutor(max_workers=200, thread_name_prefix='server_senders')

system_user = User(None, senders, username='system')
system_user.system_user = system_user

# reserved name 'system'
users: List[User] = [system_user]
global_group = Group('global', system_user, senders)
global_group.locked = True
global_group.admin = system_user

groups = [global_group]  # first group is the global group and it has no admin
reserved_names = [global_group.name, system_user.name, 'admin', 'null', 'none']

# SEND_TIMEOUT = 3600  # 1 hour inactivity

""""
Message Struct
[
    SIG(2)
    SENDER_CONTEXT(1)
    TARGET_CONTEXT(1)
    SENDER_SIZE(1)
    SENDER(utf-8)
    TARGET_SIZE(1)
    TARGET(utf-8)
    MESSAGE_SIZE(2)
    MESSAGE(utf-8)
]

client commands:
/w user_name 			whisper user
/create group_name 		create a new group
/leave 					leave this group
/invite user_name 		add user to this group
/accept group_name 		accept a group invite
/users 					show users in this group
/kick user_name 		kick user from this group
"""


def send_system_message_async(msg: str):
    for user in users:
        user.send_system_message_async(
            ServerMessage.to_client(
                target_context=ServerMessage.CONTEXT_USER,
                sender_context=ServerMessage.CONTEXT_SYSTEM,
                sender=system_user,
                target=user,
                content=msg,
            )
        )


def handle_client(socket: sockets.socket, full_address: str):
    # socket.settimeout(SEND_TIMEOUT)
    input_stream = BufferedSocketStream(socket)
    this_user = User(system_user, senders, socket)
    this_user.print_network = True
    this_user.send_system_message("choose a username")
    this_user.send_system_message("/req username")

    while True:
        uname = ServerMessage.from_client(input_stream, server_state_lock, users, groups).content.strip()
        set_uname = True
        with server_state_lock.for_read():
            for user in users:
                if user.name == uname:
                    this_user.send_system_message(f"username {uname} already taken")
                    set_uname = False
                    break
        if not set_uname or not len(uname) > 0:
            continue
        this_user.name = uname
        break

    with server_state_lock.for_write():
        users.append(this_user)
        global_group.users.append(this_user)
    this_user.send_system_message(f"/set username {this_user.name}")
    global_group.send_system_message_async(f"{this_user.name} has connected")

    try:
        while True:
            message = ServerMessage.from_client(input_stream, server_state_lock, users, groups)
            if message.content.startswith('/create '):
                group_name = message[8:].strip()
                if len(group_name) <= 0:
                    this_user.send_system_message_async("no group name provided try /help command")
                    continue
                exists = False
                with server_state_lock.for_read():
                    for group in groups:
                        if group.name == group_name:
                            exists = True
                            break
                    if group_name in reserved_names:
                        exists = True
                if exists:
                    this_user.send_system_message_async(f"{group_name} name is taken")
                    continue
                group = Group(group_name, system_user, senders)
                with server_state_lock.for_write():
                    group.join_user(this_user)
                    group.admin = this_user
                    groups.append(group)
            elif message.content == '/lock':
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                if not message.target:
                    this_user.send_system_message_async("group no longer exists")
                    continue
                if message.target.admin is not this_user:
                    this_user.send_system_message_async("you are not the group admin")
                    continue
                if message.target.locked:
                    this_user.send_system_message_async("group is already locked")
                    continue
                message.target.lock()
            elif message.content == '/unlock':
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                if not message.target:
                    this_user.send_system_message_async("group no longer exists")
                    continue
                if message.target.admin is not this_user:
                    this_user.send_system_message_async("you are not the group admin")
                    continue
                if not message.target.locked:
                    this_user.send_system_message_async("group is not locked")
                    continue
                message.target.unlock()
            elif message.content.startswith('/invite '):
                user_name = message[8:].strip()
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                group = message.target
                if len(user_name) <= 0:
                    this_user.send_system_message_async("no username provided try /help command")
                    continue

                if not group:
                    this_user.send_system_message_async("group no longer exists")
                    continue
                if group.locked and group.admin is not this_user:
                    this_user.send_system_message_async(
                        "you can't send invites, this group is locked and you are not the admin")
                    continue
                user = None
                with server_state_lock.for_read():
                    for u in users:
                        if u.name == user_name:
                            user = u
                            break
                        if user_name in reserved_names:
                            user = None
                if not user:
                    this_user.send_system_message_async(f"user not found:{user_name}")
                    continue
                with server_state_lock.for_write():
                    group.pending_invites.append(Invite(user=user, invited_by=this_user))
                user.send_system_message_async(
                    f"you was invited by {user.name} to join group {group.name} type \"/accept {group.name}\" to join")
                this_user.send_system_message_async(f"sent invite to {user.name}")
            elif message.content.startswith('/accept '):
                group_name = message[8:].strip()
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                if len(group_name) <= 0:
                    this_user.send_system_message_async("no group name provided try /help command")
                    continue
                group = None
                with server_state_lock.for_read():
                    for gr in groups:
                        if gr.name == group_name:
                            group = gr
                            break
                    invite: Optional[Invite] = None
                    if group:
                        for i in reversed(range(len(group.pending_invites))):
                            if group.pending_invites[i].user == this_user:
                                if invite is None:
                                    invite = group.pending_invites[i]
                                elif group.pending_invites[i].invited_by == group.admin:
                                    invite = group.pending_invites[i]
                                    break  # found best invite # TODO: clear invite list in kick command or leave command
                    invalid = not group or not invite or (group.locked and invite.invited_by is not group.admin)
                if invalid:
                    this_user.send_system_message_async("invite expired or group does not exist")
                    continue
                with server_state_lock.for_write():
                    group.join_user(this_user)
            else:
                if isinstance(message.target, Group) and this_user not in message.target.users:
                    this_user.send_system_message_async(f"message not sent to: {message.target}")
                    continue

                # forward to target(s)
                message.target.send_bytes_async(message.to_client(
                    target_context=message.target_context,
                    sender_context=message.sender_context,
                    target=message.target,
                    sender=this_user,
                    content=message.content
                ))

    except Exception as e:
        thread_print(f"Bye {full_address} Reason {str(e)} {traceback.format_exc()}")
    finally:
        with server_state_lock.for_write():
            for group in groups:
                if this_user in group.users:
                    group.remove_user(this_user)
                for i in reversed(range(len(group.pending_invites))):
                    if group.pending_invites[i].user == this_user:
                        group.pending_invites.pop(i)
            users.remove(this_user)
        socket.close()


def server():
    host = "0.0.0.0"  # all networks
    port = 50600

    server_socket = sockets.socket(sockets.AF_INET, sockets.SOCK_STREAM)
    server_socket.setsockopt(sockets.SOL_SOCKET, sockets.SO_REUSEADDR, 1)

    server_socket.bind((host, port))

    server_socket.listen(5)
    print("chat server is listening in {}:{} press Ctrl+C to stop".format(host, port))
    max_users = 30  # protect the server

    try:
        while True:
            client_socket, address = server_socket.accept()
            with server_state_lock.for_write():
                if len(users) > max_users:
                    client_socket.send("SERVER_FULL".encode("utf-8"))
                    client_socket.close()
                    continue
                print('Accepted:', address[0], ':', address[1])
                # Start a new thread and return its identifier
                c_thread = threading.Thread(target=handle_client,
                                            args=(client_socket, address[0] + ':' + str(address[1])))
                c_thread.name = 'client-loop'
                c_thread.start()
    finally:
        server_socket.close()


if __name__ == '__main__':
    t = threading.Thread(target=server)
    t.daemon = True
    t.start()
    soft_join(t)
    print('\n! Received keyboard interrupt, server stopped, client threads will be killed.\n')
