import Pyro5.server
import Pyro5.api
import os
import sys
import threading

RELEASED = 0
WANTED = 1
HELD = 2

class PyroService(object):

    def random_func():
        return

"""On initialization
    state := RELEASED;
To enter the section
    state := WANTED;
Multicast request to all processes;
    T := request’s timestamp;
Wait until (number of replies received = (N – 1));
    state := HELD;
On receipt of a request <Ti, pi> at pj (i ≠ j)
    if (state = HELD or (state = WANTED and (T, pj) < (Ti, pi)))
    then
        queue request from pi without replying;
    else
        reply immediately to pi;
    end if
To exit the critical section
    state := RELEASED;
    reply to any queued requests;"""


def server(state):
    
    return

def client():
    return


if __name__ ==  "__main__":
    try:
        state = RELEASED
        t_server = threading.Thread(target=server, args=(state,))
        t_client = threading.Thread(target=client)
        t_server.start()
        t_client.start()
        t_server.join()
        t_client.join()
    except KeyboardInterrupt:
        print("\nPrograma interrompido pelo usuário.")
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)