import random
import socket as sockets
import time

from cli_io import IO
from server_types import parse_args, ClientMessage, Message

io = IO()

import sys

args = parse_args(sys.argv[1:])
host = args.get('host', 'localhost')

try:
    port = int(args.get('port', 50600))
except ValueError as e:
    print("port parse failed, expected integer")
    raise e

try:
    timeout = float(args.get('timeout', '1.2'))
except ValueError as e:
    print("timeout parse failed, expected integer")
    raise e
s = sockets.socket(sockets.AF_INET, sockets.SOCK_STREAM)

try:
    s.connect((host, port))
except ConnectionRefusedError as e:
    print(f"Server not up at {host}:{port} cause: {e}")
    exit(0)

messages = [
    'Hi there, I\'m Fabio and you?',
    'Nice to meet you',
    'How are you?',
    'Not too bad, thanks',
    'What do you do?',
    'That\'s awesome',
    'I think you\'re a nice person',
    'Why do you think that?',
    'Can you explain?',
    'Anyway I\'ve gotta go now',
    'It was a pleasure chat with you',
    'whats wrong ?',
    'not too good here',
    'where should i send the money ?',
    'are you heading out to Western Union now???',
    'i will send you an email as well so you can respond back now that you got my email',
    'yup. on my way. how can i let you know when i\'ve sent the money ?',
    'Bye',
    ':)',
    'gone?',
    'great',
]

with open('usernames.txt', 'r') as file:
    usernames = file.readlines()
    uname = random.choice(usernames)
    del usernames

s.send(
    ClientMessage.to_server(
        target_context=Message.CONTEXT_GROUP,
        target='global',
        content=uname
    )
)

while True:
    time.sleep(timeout)
    s.send(
        ClientMessage.to_server(
            target_context=Message.CONTEXT_GROUP,
            target='global',
            content=random.choice(messages)
        )
    )

