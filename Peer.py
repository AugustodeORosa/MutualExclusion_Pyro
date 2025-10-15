import Pyro5.api
import Pyro5.server
import Pyro5.errors
import threading
import time
import sys
import os
import subprocess

TODOS_NOMES_DOS_PARES = ["ProcessoA", "ProcessoB", "ProcessoC", "ProcessoD"]

LIBERADO = 0
DESEJADO = 1
EM_USO = 2

TEMPO_DE_ACESSO_RECURSO = 8
INTERVALO_HEARTBEAT = 2
TIMEOUT_HEARTBEAT = 7
TIMEOUT_REQUISICAO = 5

Pyro5.config.COMMTIMEOUT = TIMEOUT_REQUISICAO

@Pyro5.api.expose
@Pyro5.server.behavior(instance_mode="single")
class Par:
    def __init__(self, nome):
        self.nome = nome
        self.uri = None
        self.estado = LIBERADO
        self.relogio_logico = 0
        self.timestamp_requisicao = -1
        self.respostas_pendentes = set()
        self.fila_requisicoes = []
        self.nomes_pares_ativos = set() # Armazena NOMES, não proxies
        self.ultimo_heartbeat = {}
        self.trava = threading.RLock() # RLock para segurança
        print(f"[{self.nome}] Par inicializado. Estado: LIBERADO.")

    def receber_requisicao(self, nome_requisitante, timestamp):
        with self.trava:
            self.relogio_logico = max(self.relogio_logico, timestamp) + 1
            self.atualizar_heartbeat(nome_requisitante)
            print(f"[{self.nome}] Recebeu pedido de {nome_requisitante} com timestamp {timestamp}.")

            tem_prioridade = (self.timestamp_requisicao, self.nome) < (timestamp, nome_requisitante)

            if self.estado == EM_USO or (self.estado == DESEJADO and tem_prioridade):
                print(f"[{self.nome}] Pedido de {nome_requisitante} enfileirado.")
                self.fila_requisicoes.append(nome_requisitante)
                return False
            else:
                print(f"[{self.nome}] Enviando OK imediato para {nome_requisitante}.")
                self._enviar_resposta_ok(nome_requisitante)
        return True

    def receber_resposta_ok(self, nome_respondente):
        with self.trava:
            self.atualizar_heartbeat(nome_respondente)
            if nome_respondente in self.respostas_pendentes:
                self.respostas_pendentes.remove(nome_respondente)
                print(f"[{self.nome}] Recebeu OK de {nome_respondente}. Faltam {len(self.respostas_pendentes)}.")
        return True

    def receber_heartbeat(self, nome_remetente):
        with self.trava:
            self.atualizar_heartbeat(nome_remetente)
        return True
    
    def _enviar_resposta_ok(self, nome_alvo):
        try:
            proxy_alvo = Pyro5.api.Proxy(f"PYRONAME:{nome_alvo}")
            proxy_alvo.receber_resposta_ok(self.nome)
        except (Pyro5.errors.CommunicationError, Pyro5.errors.NamingError):
            print(f"[{self.nome}] Falha ao enviar OK para {nome_alvo}. Marcando como falho.")
            with self.trava:
                self.tratar_falha_par(nome_alvo)

    def atualizar_heartbeat(self, nome_par):
        if nome_par not in self.nomes_pares_ativos:
             self.nomes_pares_ativos.add(nome_par)
        self.ultimo_heartbeat[nome_par] = time.time()

    def tratar_falha_par(self, nome_par):
        if nome_par in self.nomes_pares_ativos:
            """print(f"[{self.nome}] Par {nome_par} considerado FALHO. Removendo...")"""
            self.nomes_pares_ativos.remove(nome_par)
        
        if nome_par in self.ultimo_heartbeat:
            del self.ultimo_heartbeat[nome_par]
            
        if nome_par in self.respostas_pendentes:
            self.respostas_pendentes.remove(nome_par)
            print(f"[{self.nome}] Removida pendência de OK de {nome_par}.")

        self.fila_requisicoes = [p for p in self.fila_requisicoes if p != nome_par]

    def conectar_aos_pares(self):
        try:
            servidor_nomes = Pyro5.api.locate_ns()
            outros_nomes = [p for p in TODOS_NOMES_DOS_PARES if p != self.nome]
            
            for nome_par in outros_nomes:
                if nome_par not in self.nomes_pares_ativos:
                    try:
                        """uri_par = servidor_nomes.lookup(nome_par)"""
                        with self.trava:
                            self.nomes_pares_ativos.add(nome_par)
                            self.atualizar_heartbeat(nome_par)
                        print(f"[{self.nome}] Par {nome_par} encontrado na rede.")
                    except Pyro5.errors.NamingError:
                        pass
        except Pyro5.errors.NamingError:
            print(f"[{self.nome}] Servidor de Nomes não encontrado.")

    def requisitar_recurso(self):
        self.verificar_pares_falhos(conectar=True)
        pares_para_requisitar = []
        timestamp_da_requisicao = -1

        with self.trava:
            if self.estado != LIBERADO:
                print(f"[{self.nome}] Ação inválida. Estado atual já é {self.estado_para_str()}.")
                return
            
            self.estado = DESEJADO
            self.relogio_logico += 1
            self.timestamp_requisicao = self.relogio_logico
            timestamp_da_requisicao = self.timestamp_requisicao
            
            print(f"[{self.nome}] Estado alterado para DESEJADO. Timestamp: {timestamp_da_requisicao}.")
            
            pares_para_requisitar = list(self.nomes_pares_ativos)
            self.respostas_pendentes = set(pares_para_requisitar)

        if not pares_para_requisitar:
            print(f"[{self.nome}] Nenhum outro par ativo. Entrando na SC diretamente.")
        else:
            print(f"[{self.nome}] Enviando pedidos para: {pares_para_requisitar}")
            for nome_par in pares_para_requisitar:
                try:
                    proxy = Pyro5.api.Proxy(f"PYRONAME:{nome_par}")
                    proxy.receber_requisicao(self.nome, timestamp_da_requisicao)
                except (Pyro5.errors.CommunicationError, Pyro5.errors.NamingError):
                    print(f"[{self.nome}] Falha ao enviar pedido para {nome_par}.")
                    with self.trava:
                        self.tratar_falha_par(nome_par)
        
        threading.Thread(target=self.aguardar_respostas).start()

    def aguardar_respostas(self):
        inicio_espera = time.time()
        while True:
            with self.trava:
                if not self.respostas_pendentes:
                    self.estado = EM_USO
                    print("\n" + "="*40)
                    print(f"[{self.nome}]  PERMISSÃO CONCEDIDA! Entrando na Seção Crítica.")
                    print(f"[{self.nome}] O recurso será liberado em {TEMPO_DE_ACESSO_RECURSO} segundos.")
                    print("="*40)
                    threading.Timer(TEMPO_DE_ACESSO_RECURSO, self.liberar_recurso).start()
                    return
            
            if time.time() - inicio_espera > TIMEOUT_REQUISICAO * len(TODOS_NOMES_DOS_PARES):
                print(f"[{self.nome}] Timeout geral aguardando respostas. Retornando para LIBERADO.")
                with self.trava:
                    self.estado = LIBERADO
                    self.respostas_pendentes.clear()
                return
            time.sleep(0.2)

    def liberar_recurso(self):
        with self.trava:
            if self.estado != EM_USO:
                return
            self.estado = LIBERADO
            self.timestamp_requisicao = -1
            fila = list(self.fila_requisicoes)
            self.fila_requisicoes.clear()

        print("\n" + "="*40)
        print(f"[{self.nome}]  SAINDO da Seção Crítica. Estado: LIBERADO.")
        if fila:
            print(f"[{self.nome}] Processando fila de pedidos: {fila}")
            for nome_requisitante in fila:
                self._enviar_resposta_ok(nome_requisitante)
        print("="*40)

    def listar_pares(self):
        self.verificar_pares_falhos(conectar=True)
        with self.trava:
            print("\n--- Status dos Pares ---")
            print(f"Meu estado: {self.estado_para_str()}")
            print(f"Relógio Lógico: {self.relogio_logico}")
            if not self.nomes_pares_ativos:
                print("Nenhum outro par ativo conhecido.")
            else:
                print("Pares ativos conhecidos:")
                for nome in self.nomes_pares_ativos:
                    visto_por_ultimo = time.time() - self.ultimo_heartbeat.get(nome, 0)
                    print(f"  - {nome} (visto {visto_por_ultimo:.1f}s atrás)")
            print("------------------------\n")

    def estado_para_str(self):
        return {LIBERADO: "LIBERADO", DESEJADO: "DESEJADO", EM_USO: "EM USO"}.get(self.estado, "DESCONHECIDO")

    def enviar_heartbeats(self):
        with self.trava:
            nomes_para_pingar = list(self.nomes_pares_ativos)
        
        for nome_par in nomes_para_pingar:
            try:
                proxy = Pyro5.api.Proxy(f"PYRONAME:{nome_par}")
                proxy.receber_heartbeat(self.nome)
            except (Pyro5.errors.CommunicationError, Pyro5.errors.NamingError):
                with self.trava:
                    self.tratar_falha_par(nome_par)

    def verificar_pares_falhos(self, conectar=False):
        with self.trava:
            agora = time.time()
            for nome_par in list(self.nomes_pares_ativos):
                ultimo_contato = self.ultimo_heartbeat.get(nome_par, 0)
                if agora - ultimo_contato > TIMEOUT_HEARTBEAT:
                    self.tratar_falha_par(nome_par)
        
        if conectar:
            self.conectar_aos_pares()

    def executar_tarefas_background(self):
        while True:
            self.enviar_heartbeats()
            time.sleep(INTERVALO_HEARTBEAT)
            self.verificar_pares_falhos(conectar=True)

def iniciar_servidor_nomes():
    try:
        Pyro5.api.locate_ns()
        print("Servidor de Nomes já está em execução.")
    except Pyro5.errors.NamingError:
        print("Servidor de Nomes não encontrado. Iniciando uma nova instância...")
        try:
            subprocess.Popen(["pyro5-ns"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            Pyro5.api.locate_ns()
            print("Servidor de Nomes iniciado com sucesso.")
        except Exception as e:
            print(f"Falha crítica ao iniciar o Servidor de Nomes: {e}")
            sys.exit(1)

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TODOS_NOMES_DOS_PARES:
        print(f"Uso: python {sys.argv[0]} <NomeDoProcesso>")
        print(f"Nomes disponíveis: {', '.join(TODOS_NOMES_DOS_PARES)}")
        return

    nome_par = sys.argv[1]

    if nome_par == TODOS_NOMES_DOS_PARES[0]:
        iniciar_servidor_nomes()
    else:
        time.sleep(3)

    daemon = Pyro5.server.Daemon()
    servidor_nomes = Pyro5.api.locate_ns()
    
    objeto_par = Par(nome_par)
    uri = daemon.register(objeto_par)
    servidor_nomes.register(nome_par, uri)
    
    objeto_par.uri = uri

    threading.Thread(target=daemon.requestLoop, daemon=True).start()
    threading.Thread(target=objeto_par.executar_tarefas_background, daemon=True).start()

    print(f"[{nome_par}] Servidor Pyro rodando em {uri}")
    print("\nComandos disponíveis: 'requisitar', 'liberar', 'listar', 'sair'")

    try:
        while True:
            comando = input(f">>> {nome_par}: ").strip().lower()
            if comando == 'requisitar':
                objeto_par.requisitar_recurso()
            elif comando == 'liberar':
                objeto_par.liberar_recurso()
            elif comando == 'listar':
                objeto_par.listar_pares()
            elif comando == 'sair':
                break
            else:
                print("Comando inválido.")
    finally:
        print(f"\n[{nome_par}] Desligando...")
        try:
            servidor_nomes.remove(nome_par)
        except Exception as e:
            print(f"Não foi possível remover o registro do Servidor de Nomes: {e}")
        daemon.shutdown()
        os._exit(0)

if __name__ == "__main__":
    main()