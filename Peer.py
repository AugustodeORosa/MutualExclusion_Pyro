import Pyro5.api
import Pyro5.server
import Pyro5.errors
import threading
import time
import sys
import os
import random
import subprocess

TODOS_NOMES_DOS_PARES = ["ProcessoA", "ProcessoB", "ProcessoC", "ProcessoD"]

LIBERADO = 0
DESEJADO = 1
EM_USO = 2

TEMPO_DE_ACESSO_RECURSO = 8
INTERVALO_HEARTBEAT = 2
TIMEOUT_HEARTBEAT = 5
TIMEOUT_REQUISICAO = 5

Pyro5.config.COMMTIMEOUT = TIMEOUT_REQUISICAO

@Pyro5.api.expose
@Pyro5.server.behavior(instance_mode="single")
class Par:
    def __init__(self, nome):
        self.nome = nome
        self.uri = None
        self.servidor_nomes = None
        self.estado = LIBERADO
        self.relogio_logico = 0
        self.timestamp_requisicao = -1
        self.respostas_pendentes = set()
        self.fila_requisicoes = []
        self.outros_pares = {}
        self.ultimo_heartbeat = {}
        self.trava = threading.Lock()
        print(f"[{self.nome}] Par inicializado. Estado: LIBERADO.")

    def receber_requisicao(self, nome_requisitante, timestamp):
        with self.trava:
            self.relogio_logico = max(self.relogio_logico, timestamp) + 1
            self.atualizar_heartbeat(nome_requisitante)
            
            print(f"[{self.nome}] Recebeu pedido de {nome_requisitante} com timestamp {timestamp}.")

            tem_prioridade = (timestamp < self.timestamp_requisicao) or \
                           (timestamp == self.timestamp_requisicao and nome_requisitante < self.nome)

            if self.estado == EM_USO or (self.estado == DESEJADO and not tem_prioridade):
                print(f"[{self.nome}] Pedido de {nome_requisitante} enfileirado.")
                self.fila_requisicoes.append(nome_requisitante)
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
        if nome_alvo in self.outros_pares:
            try:
                self.outros_pares[nome_alvo].receber_resposta_ok(self.nome)
            except Pyro5.errors.CommunicationError:
                print(f"[{self.nome}] Falha ao enviar OK para {nome_alvo}. Marcando como falho.")
                self.tratar_falha_par(nome_alvo)

    def atualizar_heartbeat(self, nome_par):
        self.ultimo_heartbeat[nome_par] = time.time()

    def tratar_falha_par(self, nome_par):
        print(f"[{self.nome}] Par {nome_par} considerado FALHO. Removendo...")
        
        if nome_par in self.outros_pares:
            del self.outros_pares[nome_par]
        if nome_par in self.ultimo_heartbeat:
            del self.ultimo_heartbeat[nome_par]
            
        if nome_par in self.respostas_pendentes:
            self.respostas_pendentes.remove(nome_par)
            print(f"[{self.nome}] Removida pendência de OK de {nome_par}.")

        self.fila_requisicoes = [p for p in self.fila_requisicoes if p != nome_par]

    def conectar_aos_pares(self):
        print(f"[{self.nome}] Procurando outros pares...")
        nomes_outros_pares = [p for p in TODOS_NOMES_DOS_PARES if p != self.nome]
        
        for nome_par in nomes_outros_pares:
            if nome_par not in self.outros_pares:
                try:
                    uri_par = self.servidor_nomes.lookup(nome_par)
                    self.outros_pares[nome_par] = Pyro5.api.Proxy(uri_par)
                    self.outros_pares[nome_par]._pyroBind()
                    self.atualizar_heartbeat(nome_par)
                    print(f"[{self.nome}] Conectado com sucesso a {nome_par}.")
                except Pyro5.errors.NamingError:
                    pass
                except Pyro5.errors.CommunicationError:
                    print(f"[{self.nome}] Encontrou {nome_par}, mas não conseguiu se conectar.")

    def requisitar_recurso(self):
        with self.trava:
            if self.estado != LIBERADO:
                print(f"[{self.nome}] Ação inválida. Estado atual já é {self.estado_para_str()}.")
                return

            self.estado = DESEJADO
            self.relogio_logico += 1
            self.timestamp_requisicao = self.relogio_logico
            
            print(f"[{self.nome}] Estado alterado para DESEJADO. Timestamp: {self.timestamp_requisicao}.")

            self.conectar_aos_pares()

            if not self.outros_pares:
                print(f"[{self.nome}] Nenhum outro par ativo. Entrando na SC diretamente.")
                self.respostas_pendentes = set()
            else:
                self.respostas_pendentes = set(self.outros_pares.keys())
                
                print(f"[{self.nome}] Enviando pedidos para: {list(self.respostas_pendentes)}")
                
                for nome_par, proxy in list(self.outros_pares.items()):
                    try:
                        proxy.receber_requisicao(self.nome, self.timestamp_requisicao)
                    except Pyro5.errors.CommunicationError:
                        print(f"[{self.nome}] Falha ao enviar pedido para {nome_par}.")
                        self.tratar_falha_par(nome_par)
        
        threading.Thread(target=self.aguardar_respostas).start()

    def aguardar_respostas(self):
        inicio_espera = time.time()
        while True:
            with self.trava:
                if not self.respostas_pendentes:
                    self.estado = EM_USO
                    print("\n" + "="*40)
                    print(f"[{self.nome}] 👑 PERMISSÃO CONCEDIDA! Entrando na Seção Crítica.")
                    print(f"[{self.nome}] O recurso será liberado em {TEMPO_DE_ACESSO_RECURSO} segundos.")
                    print("="*40)
                    
                    threading.Timer(TEMPO_DE_ACESSO_RECURSO, self.liberar_recurso).start()
                    return
            
            if time.time() - inicio_espera > TIMEOUT_REQUISICAO * 2:
                print(f"[{self.nome}] Timeout geral aguardando respostas. Retornando para LIBERADO.")
                with self.trava:
                    self.estado = LIBERADO
                    self.respostas_pendentes.clear()
                return

            time.sleep(0.1)

    def liberar_recurso(self):
        with self.trava:
            if self.estado != EM_USO:
                return
            
            self.estado = LIBERADO
            self.timestamp_requisicao = -1
            print("\n" + "="*40)
            print(f"[{self.nome}] 🚪 SAINDO da Seção Crítica. Estado: LIBERADO.")
            
            if self.fila_requisicoes:
                print(f"[{self.nome}] Processando fila de pedidos: {self.fila_requisicoes}")
                for nome_requisitante in self.fila_requisicoes:
                    self._enviar_resposta_ok(nome_requisitante)
                self.fila_requisicoes.clear()
            print("="*40)

    def listar_pares(self):
        with self.trava:
            print("\n--- Status dos Pares ---")
            print(f"Meu estado: {self.estado_para_str()}")
            print(f"Relógio Lógico: {self.relogio_logico}")
            if not self.outros_pares:
                print("Nenhum outro par ativo conhecido.")
            else:
                print("Pares ativos conhecidos:")
                for nome in self.outros_pares.keys():
                    visto_por_ultimo = time.time() - self.ultimo_heartbeat.get(nome, 0)
                    print(f"  - {nome} (visto {visto_por_ultimo:.1f}s atrás)")
            print("------------------------\n")

    def estado_para_str(self):
        return {LIBERADO: "LIBERADO", DESEJADO: "DESEJADO", EM_USO: "EM USO"}.get(self.estado, "DESCONHECIDO")

    def executar_envio_heartbeat(self):
        while True:
            time.sleep(INTERVALO_HEARTBEAT)
            with self.trava:
                pares_para_pingar = list(self.outros_pares.items())
            
            for nome_par, proxy in pares_para_pingar:
                try:
                    proxy.receber_heartbeat(self.nome)
                except Pyro5.errors.CommunicationError:
                    pass
    
    def executar_verificador_heartbeat(self):
        while True:
            time.sleep(TIMEOUT_HEARTBEAT)
            with self.trava:
                self.conectar_aos_pares()
                agora = time.time()
                for nome_par, visto_por_ultimo in list(self.ultimo_heartbeat.items()):
                    if agora - visto_por_ultimo > TIMEOUT_HEARTBEAT:
                        self.tratar_falha_par(nome_par)

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

def principal():
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
    objeto_par.servidor_nomes = servidor_nomes

    threading.Thread(target=daemon.requestLoop, daemon=True).start()
    threading.Thread(target=objeto_par.executar_envio_heartbeat, daemon=True).start()
    threading.Thread(target=objeto_par.executar_verificador_heartbeat, daemon=True).start()

    print(f"[{nome_par}] Servidor Pyro rodando em {uri}")
    print("\nComandos disponíveis: 'requisitar', 'liberar', 'listar', 'sair'")

    try:
        while True:
            comando = input(f">>> {nome_par}: ").strip().lower()
            if comando == 'requisitar':
                objeto_par.requisitar_recurso()
            elif comando == 'liberar':
                with objeto_par.trava:
                    if objeto_par.estado == EM_USO:
                        objeto_par.liberar_recurso()
                    else:
                        print(f"[{nome_par}] Não está na Seção Crítica para liberar.")
            elif comando == 'listar':
                objeto_par.listar_pares()
            elif comando == 'sair':
                break
            else:
                print("Comando inválido.")
    finally:
        print(f"\n[{nome_par}] Desligando...")
        servidor_nomes.remove(nome_par)
        daemon.shutdown()
        os._exit(0)

if __name__ == "__main__":
    principal()