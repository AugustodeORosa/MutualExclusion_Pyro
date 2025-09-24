import Pyro5.server
import Pyro5.api
import os, sys, threading, time

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
    daemon = Pyro5.server.Daemon()
    uri = daemon.register("server")
    print("uri=", uri)
    daemon.requestLoop()
    
def requisitar_recurso():
    return

def liberar_recurso():
    return

def listar_peers():
    return

def client():
    time.sleep(2)
    print("Comandos disponíveis: 'requisitar', 'liberar', 'listar'")

    while True:
        comando = input(">>> ").strip().lower()
        if comando == 'requisitar':
            requisitar_recurso()
        elif comando == 'liberar':
            liberar_recurso()
        elif comando == 'listar':
            listar_peers()
        elif comando == 'sair':
            print(" Encerrando o cliente...")
            os._exit(0)
        else:
            print("Comando inválido. Tente novamente.")
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