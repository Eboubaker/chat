# Import socket module
import os
import socket as sockets
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from termcolor import colored

from BufferedSocketStream import BufferedSocketStream
from SelfThreadAwareReadWriteLock import SelfThreadAwareReadWriteLock
from cli_io import IO, ReadError
from lib import soft_join
from server_types import ServerUser, ClientUser, Group, Message, ClientMessage, parse_args

io = IO()

state_lock = SelfThreadAwareReadWriteLock()
senders = ThreadPoolExecutor(max_workers=200, thread_name_prefix='client_senders')
system_user = ServerUser(None, senders, username='system')
global_group = Group('global', system_user, senders)
system_user.system_user = system_user
server_user = ClientUser(senders=senders, username='null')
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
close_program = threading.Event()


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
        if is_whisper:
            line += f"{sender}'s whispers: "
        else:
            line += sender + ': '
    line += txt
    if is_whisper:
        line = colored(line, whisper_color)
    if is_system:
        line = colored(line, target_colors[system_user.name])
    io.write(line)


def write_error(txt):
    io.write(colored(txt, 'red'))


def write_program_info(txt):
    io.write(colored('program: ' + txt, target_colors[system_user.name]))


def server_interface_thread():
    """
    handles commands from the server
    """
    global picking_username
    try:
        input_stream = BufferedSocketStream(server_user.socket)
        while True:
            try:
                msg = ClientMessage.from_server(input_stream)
            except ConnectionError as err:
                write_error(f"fatal: server connection dropped, cause: {err}")
                break
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
                            server_user.chat_target = server_user.target = 'global'
                            io.update_input_label("global: ")
                            io.update_input_label_color('white')
                            continue
                        elif msg.content.startswith('/switch '):
                            server_user.target = server_user.chat_target = msg.content[8:]
                            io.update_input_label(server_user.chat_target + ": ")
                            io.update_input_label_color(target_colors.get(server_user.target, 'white'))
                            continue
                        elif msg.content.startswith("You're whispering to"):
                            io.write(colored(msg.content, whisper_color))
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
    finally:
        close_program.set()


def interaction_thread():
    """
    handles commands from the user terminal
    """
    last_was_interrupt = False
    interrupt_times = 0
    input_history = []
    try:
        while True:
            try:
                msg = io.input(history=input_history).strip()
                input_history.append(msg)
                if len(input_history) > 1000:
                    input_history.pop(0)
            except KeyboardInterrupt:
                if interrupt_times == 2:
                    write_program_info("exiting chat program")
                    close_program.set()
                    return
                if last_was_interrupt or len(io.interrupted_buffer()) == 0:
                    write_program_info(f"type /exit to quit or hit Ctrl+C {2 - interrupt_times} more times")
                    interrupt_times += 1
                else:
                    last_was_interrupt = True
                    continue
                continue
            except ReadError as e:
                write_error("input-error:" + str(e) + "\ntraceback:" + traceback.format_exc())
                continue
            last_was_interrupt = False
            interrupt_times = 0
            try:
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
                        continue
                    elif msg == '/exit' or msg == '/quit':
                        write_program_info("exiting chat program")
                        close_program.set()
                        #server_user.socket.close()
                        return

                    elif msg.startswith('/w ') and len(msg[3:].strip()) > 0:
                        msg = msg[3:].strip()
                        sep = msg.find(' ')
                        if sep == -1:
                            write_error('must provide user and message')
                            continue
                        username = msg[0:sep].strip()
                        msg = msg[sep:].strip()
                        if len(msg) == 0:
                            write_error('must provide user and message message')
                            continue
                        server_user.send_bytes_async(
                            ClientMessage.to_server(
                                target_context=Message.CONTEXT_USER,
                                target=username,
                                content=msg,
                            )
                        )
                        io.update_input_buffer(f'/w {username} ')
                        continue
                    elif msg == '/help':
                        io.write('')
                        write_program_info('''chat commands
/w <user_name>          whisper user
/switch <group_name>    switch to another group
/color                  change color of this group
/quit or /exit          exit
/help                   show commands\n''')
                        pass  # show program
                    # otherwise send to server
                    server_user.send_bytes_async(
                        ClientMessage.to_server(
                            target_context=server_user.target_context,
                            target=server_user.target,
                            content=msg,
                        )
                    )
            except BaseException as e:
                write_error("error:" + str(e) + "\ntraceback:" + traceback.format_exc())
    finally:
        close_program.set()


def main():
    import sys
    args = parse_args(sys.argv[1:])
    host = args.get('host', 'localhost')  # default all networks
    try:
        port = int(args.get('port', 50600))
    except ValueError as e:
        print("port parse failed, expected integer")
        raise e

    s = sockets.socket(sockets.AF_INET, sockets.SOCK_STREAM)

    try:
        s.connect((host, port))
    except ConnectionRefusedError as e:
        print(f"Server not up at {host}:{port} cause: {e}")
        exit(0)
    server_user.socket = s
    io.write(f"connected to {host}:{port}")
    communicator = threading.Thread(target=server_interface_thread)
    communicator.daemon = True
    communicator.start()
    interactor = threading.Thread(target=interaction_thread)
    interactor.daemon = True
    interactor.start()
    soft_join(interactor, close_program)
    soft_join(communicator, close_program)
    print()


if __name__ == '__main__':
    if os.name == 'nt':
        import colorama as colorama

        colorama.init()  # force colors
    main()
