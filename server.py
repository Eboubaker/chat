import os
import re
import socket as sockets
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from termcolor import colored

from BufferedSocketStream import BufferedSocketStream
from SelfThreadAwareReadWriteLock import SelfThreadAwareReadWriteLock
from lib import soft_join, thread_print
from server_types import Invite, Group, ServerMessage, ServerUser, Message, parse_args

server_state_lock = SelfThreadAwareReadWriteLock()
senders = ThreadPoolExecutor(max_workers=200, thread_name_prefix='server_senders')

system_user = ServerUser(None, senders, username='system')
system_user.system_user = system_user

# reserved name 'system'
users: List[ServerUser] = [system_user]
global_group = Group('global', system_user, senders)
global_group.locked = True
global_group.admin = system_user

groups = [global_group]  # first group is the global group and it has no admin
reserved_names = [global_group.name, system_user.name, 'admin', 'null', 'none', 'program']

# SEND_TIMEOUT = 3600  # 1 hour inactivity

""""
Message Struct(server to client)
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

Message Struct(client to server)
[
    SIG(2)
    TARGET_CONTEXT(1)
    TARGET_SIZE(1)
    TARGET(utf-8)
    MESSAGE_SIZE(2)
    MESSAGE(utf-8)
]

client commands handled by server:
/create <group_name>    create a new group
/leave                  leave this group
/invite <user_name>     send a group invite
/accept <group_name>    accept a group invite
/users                  show users in this group
/banned                 show ban list
/ban <user_name>        ban user
/kick <user_name>       kick user from this group
/help                   show commands

client commands handled by client:
/w <user_name>          whisper user
/switch <group_name>    switch to another group
/color                  change color of this group
/quit or /exit          exit
/help                   show commands
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
                report=True
            )
        )


def format_user_group(group: Group, this_user: ServerUser, user: ServerUser):
    txt = user.name
    if this_user == user:
        txt = colored(txt, 'green')
    if group.admin == user:
        txt += colored('[ADMIN]', 'yellow')
    if user in this_user.ban_list:
        txt += colored('[BANNED]', 'red')
    return txt


def handle_client(socket: sockets.socket, full_address: str):
    # socket.settimeout(SEND_TIMEOUT)
    input_stream = BufferedSocketStream(socket)
    this_user = ServerUser(system_user, senders, socket)
    this_user.print_network = True
    try:
        this_user.send_system_message("choose a username")
        this_user.send_system_message("/req username")

        while True:
            try:
                uname = ServerMessage.from_client(input_stream, report_from=this_user).content.strip().lower()
            except ConnectionError as err:
                thread_print(f"user {this_user.name} disconnected, cause: {err}")
                return
            set_uname = True
            with server_state_lock.for_read():
                for user in users:
                    if user.name == uname:
                        this_user.send_system_message(f"username {uname} already taken")
                        set_uname = False
                        break
                if not re.match(r'^[a-z][a-z0-9_-]*[a-z0-9]$', uname):
                    this_user.send_system_message(
                        f"name must begin with a-z letter and contain a-z0-9 '_' or '-' and end with a-z0-9")
                    set_uname = False
            if not set_uname or not len(uname) > 0:
                continue
            this_user.name = uname
            break

        with server_state_lock.for_write():
            users.append(this_user)
            global_group.users.append(this_user)
            this_user.groups.append(global_group)
        this_user.send_system_message(f"/set username {this_user.name}")
        global_group.send_system_message_async(f"{this_user.name} has connected")

        while True:
            try:
                message = ServerMessage.from_client(input_stream, report_from=this_user)
            except ConnectionError as err:
                thread_print(f"user {this_user.name} disconnected, cause: {err}")
                break
            message.target = None
            with server_state_lock.for_read():
                for group in groups:
                    if group.name == message.target_str:
                        message.target = group
                        break
                if not message.target:
                    for user in users:
                        if user.name == message.target_str:
                            message.target = user
                            break
            if not message.target:
                if message.target_context == Message.CONTEXT_GROUP:
                    this_user.send_system_message_async(f"group {message.target_str} does not exist, or not subscribed")
                    this_user.send_system_message(f"/switch {global_group.name}")
                elif message.target_context == Message.CONTEXT_USER:
                    this_user.send_system_message_async(f"user {message.target_str} does not exist")
                else:
                    this_user.send_system_message_async(f"target {message.target_str} does not exist")
                continue
            if message.content.startswith('/create '):
                group_name = message.content[8:].strip()
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
                    group.join_user(this_user, f"you have created the group {group.name}")
                    group.admin = this_user
                    groups.append(group)
                this_user.send_system_message(f"/switch {group.name}")
            elif message.content == '/lock':
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                if not message.target:
                    this_user.send_system_message_async(f"group {message.target_str} does not exist, or not subscribed")
                    this_user.send_system_message(f"/switch {global_group.name}")
                    continue
                if message.target.admin is not this_user:
                    this_user.send_system_message_async("you are not the group admin")
                    continue
                if message.target.locked:
                    this_user.send_system_message_async("group is already locked")
                    continue
                with server_state_lock.for_write():
                    message.target.lock()
                    for i in reversed(range(len(message.target.pending_invites))):
                        if message.target.pending_invites[i].invited_by is not this_user:
                            message.target.pending_invites.pop(i)
            elif message.content == '/unlock':
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                if not message.target:
                    this_user.send_system_message_async(f"group {message.target_str} does not exist, or not subscribed")
                    continue
                if message.target.admin is not this_user:
                    this_user.send_system_message_async("you are not the group admin")
                    continue
                if not message.target.locked:
                    this_user.send_system_message_async("group is not locked")
                    continue
                with server_state_lock.for_write():
                    message.target.unlock()
            elif message.content == '/leave':
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                if not message.target or this_user not in message.target.users:
                    this_user.send_system_message_async(f"group {message.target_str} does not exist, or not subscribed")
                    continue
                with server_state_lock.for_write():
                    message.target.remove_user(this_user, f"{this_user.name} has left")

                if message.target == global_group:
                    global_group.pending_invites.append(Invite(this_user, system_user))
                    this_user.send_system_message_async(
                        f"you have unsubscribed from the global group use \"/accept {global_group.name}\" to come back")
                else:
                    this_user.send_system_message_async(f"you left the group {message.target.name}")
            elif message.content == '/users':
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                if not message.target or this_user not in message.target.users:
                    this_user.send_system_message_async(f"group {message.target_str} does not exist, or not subscribed")
                    continue
                with server_state_lock.for_read():
                    this_user.send_bytes_async(
                        ServerMessage.to_client(
                            target_context=Message.CONTEXT_GROUP,
                            sender_context=Message.CONTEXT_SYSTEM,
                            sender=system_user,
                            target=message.target,  # it is sent only to this_user
                            content=f'users in {message.target.name}:\n' +
                                    '\n'.join(format_user_group(message.target, this_user, user) for user in message.target.users),
                            report=True
                        )
                    )
            elif message.content == '/banned':
                with server_state_lock.for_read():
                    this_user.send_bytes_async(
                        ServerMessage.to_client(
                            target_context=Message.CONTEXT_GROUP,
                            sender_context=Message.CONTEXT_SYSTEM,
                            sender=system_user,
                            target=message.target,  # it is sent only to this_user
                            content=f'banned users:\n' +
                                    '\n'.join(user.name for user in this_user.ban_list),
                            report=True
                        )
                    )
            elif message.content == '/help':
                this_user.send_system_message_async('''chat commands:
/create <group_name>    create a new group
/leave                  leave this group
/invite <user_name>     send a group invite
/accept <group_name>    accept a group invite
/users                  show users in this group
/banned                 show ban list
/ban <user_name>        ban user
/kick <user_name>       kick user from this group
/help                   show commands
''')
                continue
            elif message.content.startswith('/invite '):
                user_name = message.content[8:].strip()
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                group = message.target
                if len(user_name) <= 0:
                    this_user.send_system_message_async("no username provided try /help command")
                    continue

                if not group:
                    this_user.send_system_message_async("group no longer exists")
                    this_user.send_system_message(f"/switch {global_group.name}")
                    continue
                if group.locked and group.admin is not this_user:
                    this_user.send_system_message_async(
                        "you can't send invites, this group is locked and you are not the admin")
                    continue
                user = None
                with server_state_lock.for_write():
                    for u in users:
                        if u.name == user_name:
                            user = u
                            break
                        if user_name in reserved_names:
                            user = None
                    if not user:
                        this_user.send_system_message_async(f"user not found:{user_name}")
                        continue
                    if user == this_user:
                        this_user.send_system_message_async(
                            f"you can't invite yourself, you're already in group {group.name}")
                        continue
                    if user in this_user.ban_list:
                        this_user.send_system_message_async(f"{user.name} is in your ban list")
                        continue
                    group.pending_invites.append(Invite(user=user, invited_by=this_user))
                user.send_system_message_async(
                    f"you was invited by {user.name} to join group {group.name} type \"/accept {group.name}\" to join")
                this_user.send_system_message_async(f"invite was sent to {user.name}")
            elif message.content.startswith('/kick '):
                user_name = message.content[6:].strip()
                sep = user_name.find(' ')
                reason = ''
                if sep != -1:
                    user_name = user_name[:sep]
                    reason = 'reason: ' + message.content[6:].strip()[sep:].strip()
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                group = message.target
                if len(user_name) <= 0:
                    this_user.send_system_message_async("no username provided try /help command")
                    continue

                if not group:
                    this_user.send_system_message_async("group no longer exists")
                    this_user.send_system_message(f"/switch {global_group.name}")
                    continue
                user = None
                with server_state_lock.for_write():
                    if group.admin is not this_user:
                        this_user.send_system_message_async(
                            f"can't kick {user_name} you are not the admin of {group.name}")
                        continue
                    for u in group.users:
                        if u.name == user_name:
                            user = u
                            break
                    if user is None:
                        this_user.send_system_message_async(f"{user_name} is not in your group {group.name}")
                        continue
                    elif user == this_user:
                        this_user.send_system_message_async("you can't kick your self, use /leave")
                        continue
                    group.remove_user(user, f"{user.name} was kicked from the group")
                    user.send_system_message_async(f"you was kicked by the admin from group {group.name} {reason}")
                    user.send_system_message_async(f"/switch {global_group.name}")
                    this_user.send_system_message_async(f"{user.name} was kicked")
            elif message.content.startswith('/ban '):
                user_name = message.content[4:].strip()
                if not isinstance(message.target, Group):
                    this_user.send_system_message_async("target is not a group")
                    continue
                if len(user_name) <= 0:
                    this_user.send_system_message_async("no username provided try /help command")
                    continue

                with server_state_lock.for_write():
                    user = None
                    for u in users:
                        if u.name == user_name:
                            user = u
                            break
                    if not user:
                        this_user.send_system_message_async(f"user {user.name} does not exist")
                        continue
                    for group in this_user.groups:
                        if this_user == group.admin and this_user in group.users and user in group.users:
                            group.remove_user(user, f"{user.name} was banned by the admin")
                            user.send_system_message_async(f"you was kicked from group {group.name}, because the admin banned you")
                    this_user.ban_list.append(user)
                    this_user.send_system_message_async(f"{user.name} is now in your ban list")
            elif message.content.startswith('/accept '):
                group_name = message.content[8:].strip()
                if len(group_name) <= 0:
                    this_user.send_system_message_async("no group name provided try /help command")
                    continue
                group = None
                with server_state_lock.for_write():
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
                                    # TODO: clear invite list in kick command or leave command
                                group.pending_invites.pop(i)  # consume all invites
                    invalid = group is None or invite is None or (group.locked and invite.invited_by is not group.admin)

                    if invalid:
                        this_user.send_system_message_async("invite expired or group does not exist")
                        continue
                    if this_user in group.admin.ban_list:
                        this_user.send_system_message(f"You are banned by the group admin and can't join {group.name}")
                        continue
                    group.join_user(this_user, f"{user.name} has entered the group" if group is not global_group else f"{user.name} has re-entered the group")
                    this_user.send_system_message(f"/switch {group.name}")
            else:
                if isinstance(message.target, Group) and this_user not in message.target.users:
                    this_user.send_system_message_async(f"group {message.target_str} does not exist, or not subscribed")
                    continue
                if isinstance(message.target, ServerUser):
                    this_user.send_system_message_async(
                        f"You're whispering to {message.target.name}: {message.content}")
                if isinstance(message.target, ServerUser) and this_user in message.target.ban_list:
                    this_user.send_system_message_async(f"you are banned by {message.target.name}")
                    continue
                if isinstance(message.target, ServerUser) and message.target in this_user.ban_list:
                    this_user.send_system_message_async(f"you banned {message.target.name}")
                    continue
                if isinstance(message.target, Group) and this_user in message.target.admin.ban_list:
                    this_user.send_system_message_async(f"you are banned by {message.target.name}'s admin")
                    continue
                # forward to target(s)
                message.target.send_bytes_async(
                    ServerMessage.to_client(
                        target_context=message.target_context,
                        sender_context=Message.CONTEXT_USER,
                        target=message.target,
                        sender=this_user,
                        content=message.content,
                        report=True
                    )
                )
    except BaseException:
        thread_print(f"error in handler for {full_address} ({this_user.name}), cause: {traceback.format_exc()}")
    finally:
        with server_state_lock.for_write():
            if this_user in users:
                users.remove(this_user)
            for j in reversed(range(len(groups))):
                removed = False
                if this_user in groups[j].users:
                    groups[j].remove_user(this_user, f"{this_user.name} has disconnected")
                    if len(groups[j].users) == 0 and groups[j] is not global_group:
                        thread_print(f"abandoned group was removed: {groups[j].name}")
                        groups.pop(j)
                        removed = True
                if not removed:
                    for i in reversed(range(len(groups[j].pending_invites))):
                        if groups[j].pending_invites[i].user == this_user:
                            groups[j].pending_invites.pop(i)
        socket.close()


def server():
    import sys
    args = parse_args(sys.argv[1:])
    host = args.get('host', '0.0.0.0')  # default all networks
    try:
        port = int(args.get('port', 50600))
    except ValueError as e:
        print("port parse failed, expected integer")
        raise e

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
                c_thread.daemon = True
                c_thread.name = 'client-loop'
                c_thread.start()
    finally:
        server_socket.close()


def main():
    t = threading.Thread(target=server)
    t.daemon = True
    t.start()
    soft_join(t)
    print('\n! Received keyboard interrupt, server will stop, client threads will be dropped.\n')


if __name__ == '__main__':
    if os.name == 'nt':
        import colorama as colorama

        colorama.init()  # force colors
    main()
