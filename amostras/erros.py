class ErroKuro(Exception):
    pass


class ErroValidacao(ErroKuro):
    """Entrada do usuário inválida."""


class ErroSeguranca(ErroKuro):
    """Regra de segurança violada. A operação é negada."""


class ErroIA(ErroKuro):
    """A IA local falhou: conexão, tempo ou resposta fora do formato."""


class RequisicaoRecusada(ErroIA):
    """O servidor devolveu 4xx; repetir não adianta."""


class IAIndisponivel(ErroIA):
    """Disjuntor aberto ou servidor fora do ar."""
