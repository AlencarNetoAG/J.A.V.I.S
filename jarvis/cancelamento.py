"""Sinais cooperativos separados para operação, captura e fala."""
import time


class Cancelado(Exception):
    pass


def verificar(evento):
    if evento is not None and evento.is_set(): raise Cancelado()


class Eventos:
    def __init__(self, *eventos): self.eventos = eventos
    def is_set(self): return any(e.is_set() for e in self.eventos)
    def wait(self, timeout):
        fim = time.monotonic()+timeout
        while not self.is_set():
            restante = fim-time.monotonic()
            if restante <= 0: break
            self.eventos[0].wait(min(.01, restante))
        return self.is_set()
