# Import socket module
import socket as sockets
import threading
from concurrent.futures import ThreadPoolExecutor

from BufferedSocketStream import BufferedSocketStream
from ReadWriteLock import ReadWriteLock
from cli_io import IO
from lib import soft_join
from server_types import Message, User, ClientUser, Group

io = IO()

state_lock = ReadWriteLock()
senders = ThreadPoolExecutor(max_workers=200, thread_name_prefix='client_senders')
system_user = User(None, senders, username='system')
system_user.system_user = system_user
this_user = ClientUser(system_user, senders, username='null')
global_group = Group('global', system_user, senders)
this_user.target = global_group
this_user.target_context = Message.CONTEXT_GROUP
groups = [global_group]
users = [system_user, this_user]


def reader():
	input_stream = BufferedSocketStream(this_user.socket)
	while True:
		io.write(f"received {Message.read_from_stream(input_stream, state_lock, print=False)}")


def writer():
	while True:
		msg = io.input(this_user.target.name + ": ")
		this_user.send_bytes_async(
			Message.new(
				target_context=this_user.target_context,
				sender_context=Message.CONTEXT_USER,
				sender=this_user,
				target=this_user.target,
				content=msg,
			).to_bytes()
		).result()


def main():
	host = '127.0.0.1'
	port = 50600
	s = sockets.socket(sockets.AF_INET, sockets.SOCK_STREAM)

	s.connect((host, port))
	this_user.socket = s
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
