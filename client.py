# Import socket module
import socket as sockets
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from termcolor import colored

from BufferedSocketStream import BufferedSocketStream
from ReadWriteLock import ReadWriteLock
from cli_io import IO
from lib import soft_join
from server_types import User, ClientUser, Group, Message, ClientMessage

io = IO()

state_lock = ReadWriteLock()
senders = ThreadPoolExecutor(max_workers=200, thread_name_prefix='client_senders')
system_user = User(None, senders, username='system')
system_user.system_user = system_user
server_user = ClientUser(system_user, senders, username='null')
global_group = Group('global', system_user, senders)
server_user.target = global_group
server_user.target_context = Message.CONTEXT_GROUP
server_user.chat_target = ''
groups = [global_group]
users = [system_user, server_user]

send_receive_lock = threading.Lock()
picking_username = False

allowed_colors = [
    'grey',
    'red',
    'green',
    'yellow',
    'blue',
    'magenta',
    'cyan',
    'white',
]
target_colors = {system_user.name: 'cyan'}
allowed_colors.remove(target_colors[system_user.name])
whisper_color = 'yellow'


def write_message_formatted(txt: str, group: Optional[str] = None, sender: Optional[str] = None,
                            is_system=False,
                            is_whisper=False):
    line = ''
    if group:
        if is_system or is_whisper:
            line += '[' + group + '] '
        else:
            line += colored('[' + group + '] ', target_colors.get(group, 'white'))
    if sender:
        line += sender + ': '
    line += txt
    if is_whisper:
        line = colored(line, whisper_color)
    if is_system:
        line = colored(line, target_colors[system_user.name])
    io.write(line)


def write_error(txt):
    io.write(colored(txt, 'red'))


def reader():
    global picking_username
    input_stream = BufferedSocketStream(server_user.socket)
    while True:
        msg = ClientMessage.from_server(input_stream)
        # io.write(str(msg))
        with send_receive_lock:
            if msg.sender_context == Message.CONTEXT_SYSTEM:
                if msg.target_context == Message.CONTEXT_USER:
                    # only for me
                    if msg.content == '/req username':
                        picking_username = True
                        server_user.target = system_user.name
                        server_user.chat_target = 'username'
                        io.update_input_label("username: ")
                        io.update_input_label_color(target_colors[system_user.name])
                        continue
                    elif msg.content.startswith('/set username '):
                        server_user.name = msg.content[14:]
                        picking_username = False
                        server_user.target_context = Message.CONTEXT_GROUP
                        server_user.chat_target = server_user.target = 'global'
                        io.update_input_label("global: ")
                        io.update_input_label_color('white')
                        continue
                    else:
                        write_message_formatted(msg.content, sender=msg.sender, is_system=True)
                        continue
                elif msg.target_context == Message.CONTEXT_GROUP:
                    write_message_formatted(msg.content, group=msg.target, sender=msg.sender, is_system=True)
                    continue
                else:
                    write_error("error: server sent message with unhandled context: " + msg.target_context)
                    continue
            elif msg.target == server_user.name:
                write_message_formatted(msg.content, sender=msg.sender, is_whisper=True)
                continue
            elif msg.target_context == Message.CONTEXT_GROUP:
                write_message_formatted(msg.content, group=msg.target, sender=msg.sender)
                continue
        write_error(f"received unhandled message {msg}")


def writer():
    while True:
        msg = io.input().strip()
        with send_receive_lock:
            if msg.startswith('/switch ') and len(msg[8:].strip()) > 0:
                server_user.target_context = Message.CONTEXT_GROUP
                server_user.chat_target = server_user.target = msg[8:].strip()
                io.update_input_label(server_user.chat_target + ": ")
                io.update_input_label_color(target_colors.get(server_user.target, 'white'))
                continue
            elif msg.startswith('/color ') and len(msg[7:].strip()) > 0:
                color = msg[7:].strip()
                if color not in allowed_colors:
                    write_error('client: allowed colors are ' + ','.join(allowed_colors))
                    continue
                target_colors[server_user.target] = color
                io.update_input_label_color(color)
            elif msg.startswith('/w ') and len(msg[3:].strip()) > 0:
                txt = msg[3:].strip()
                sep = txt.find(' ')
                if sep == -1:
                    write_error('must provide message')
                    continue
                username = msg[0, sep].strip()
                msg = msg[sep:].strip()
                if len(msg) == 0:
                    write_error('must provide message')
                    continue
                server_user.send_bytes_async(
                    ClientMessage.to_server(
                        target_context=Message.CONTEXT_USER,
                        sender_context=Message.CONTEXT_USER,
                        target=username,
                        content=msg,
                    )
                ).result()
                continue
            elif msg == '/help':
                pass  # show help
            server_user.send_bytes_async(
                ClientMessage.to_server(
                    target_context=server_user.target_context,
                    sender_context=Message.CONTEXT_USER,
                    target=server_user.target,
                    content=msg,
                )
            ).result()


def main():
    host = '127.0.0.1'
    port = 50600
    s = sockets.socket(sockets.AF_INET, sockets.SOCK_STREAM)

    try:
        s.connect((host, port))
    except ConnectionRefusedError as e:
        print(f"Server not up at {host}:{port} cause: {e}")
        exit(0)
    server_user.socket = s
    io.write(f"connected to {host}:{port}")
    message = ""
    to = "system"
    message = message.encode('utf-8')
    to = to.encode("utf-8")
    data = bytearray()
    data.extend(len(to).to_bytes(length=1, byteorder='little'))
    data.extend(to)
    data.extend(len(message).to_bytes(length=2, byteorder='little'))
    data.extend(message)
    # s.send(data)
    t1 = threading.Thread(target=reader)
    t1.daemon = True
    t1.start()
    t2 = threading.Thread(target=writer)
    t2.daemon = True
    t2.start()
    soft_join(t1)
    soft_join(t2)


if __name__ == '__main__':
    main()
