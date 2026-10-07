class Cancelado(Exception):
    """Cancelamento solicitado pelo usuário."""


def verificar(evento):
    if evento is not None and evento.is_set():
        raise Cancelado()
