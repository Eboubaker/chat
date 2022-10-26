import threading
from threading import Thread

release_joins = {'value': False}


def soft_join(t: Thread):
	"""
	join but interrupt on Ctrl+C
	all attempt to join after Ctrl+C will be ignored
	"""
	if not t.daemon:
		assert False, "not daemon"
	while t.is_alive() and not release_joins['value']:
		try:
			t.join(.2)  # check interrupt every 200ms
		except (KeyboardInterrupt, SystemExit):  # Ctrl+C
			release_joins['value'] = True


def thread_print(msg):
	"""
	print the thread id along with the message
	"""
	print(f'{threading.current_thread().name}-{str(threading.current_thread().ident)}: {msg}')
