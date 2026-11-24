"""
Lógica de repetição espaçada do Revisa.

Este módulo não conhece Flask nem banco de dados: recebe dados simples
(datas, acertos, totais) e devolve resultados. Assim tudo pode ser testado
de forma isolada (ver tests/test_logica.py).

Convenções:
- Percentuais são frações entre 0 e 1 (0.85 = 85%).
- Sessões são tuplas (data, acertos, total) em ordem cronológica
  (a mais antiga primeiro, a mais recente por último).
- Dias da semana seguem date.weekday(): 0 = segunda ... 6 = domingo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil, floor

# Pequena tolerância para comparar frações (ex.: 17/20 deve contar como 85%).
EPS = 1e-9

# Pesos do domínio: sessão mais recente, penúltima, antepenúltima.
PESOS_DOMINIO = (0.5, 0.3, 0.2)

# Tabela de intervalo e questões sugeridas, aplicada ao domínio do assunto
# (média ponderada das últimas sessões, ver dominio()).
# Cada linha: (limite inferior da faixa, dias até a próxima revisão, questões).
# A busca é feita de cima para baixo: a primeira faixa cujo limite foi atingido vale.
TABELA = (
    (0.95, 30, 4),   # >= 95%
    (0.85, 15, 6),   # 85–94%
    (0.70, 7, 10),   # 70–84%
    (0.50, 4, 15),   # 50–69%
    (0.00, 3, 20),   # < 50%
)

LIMIAR_BOM = 0.85          # sessões >= 85% contam para o bônus
QUESTOES_REFERENCIA = 10   # a partir de 10 questões a sessão tem peso cheio no domínio
INTERVALO_MAXIMO = 365     # limite absoluto do bônus: 1 ano (opção "Livre" do usuário)
PERDA_POR_SEMANA = 0.05    # esquecimento: -5 pontos percentuais por semana de atraso
PESO_ATRASO = 0.1          # cada dia de atraso soma 0,1 na prioridade

# Fase de aprendizado: teto do intervalo depois da 1ª e da 2ª sessão de um
# assunto. Mesmo acertando tudo, um assunto novo volta em até 7 dias e depois
# em até 15, antes de seguir livre pela tabela (30 dias, bônus...).
TETOS_APRENDIZADO = (7, 15)

# O usuário escolhe como quer a fase de aprendizado (onboarding/Configurações).
FASES_APRENDIZADO = {
    "cautelosa": (2, 4, 8, 15),  # esquece rápido: degraus curtos 2 -> 4 -> 8 -> 15 -> 30
    "degraus": (3, 7, 15),    # confirma bem antes de espaçar:        3 -> 7 -> 15 -> 30
    "padrao": (7, 15),        # equilíbrio (recomendado):             7 -> 15 -> 30 -> 60
    "solta": (10, 20),        # já tem alguma base:                   10 -> 20 -> 40
}


def tetos_da_fase(nome: str | None) -> tuple[int, ...]:
    return FASES_APRENDIZADO.get(nome or "padrao", TETOS_APRENDIZADO)


# Teto escolhido pelo usuário: máximo de dias que um assunto fica sem revisão.
TETO_PADRAO = 45
TETO_MIN, TETO_MAX = 7, 365
TETO_LIVRE = 365           # "Livre (até 1 ano)": para quem estuda a longo prazo, sem prova
TETO_POR_RITMO = {"leve": 60, "moderado": 45, "intenso": 30}
AJUSTE_TETO_FASE = {"cautelosa": -15, "solta": 15}


def sugerir_teto(ritmo: str | None, aprendizado: str | None) -> int:
    """
    Sugestão de teto a partir das respostas do onboarding:
    ritmo (leve 60, moderado 45, intenso 30) ajustado pela fase de
    aprendizado ("esqueço rápido" -15, "já tenho base" +15).
    """
    base = TETO_POR_RITMO.get(ritmo or "leve", TETO_PADRAO)
    return max(21, min(90, base + AJUSTE_TETO_FASE.get(aprendizado or "", 0)))

# Ritmo de estudo: multiplica o intervalo final. Quem faz mais questões
# (fase só de questões) revisa com mais frequência.
RITMOS = {
    "leve": 1.0,       # estudando conteúdo + questões
    "moderado": 0.75,  # rotina regular de questões
    "intenso": 0.5,    # fase só de questões
}


# ---------------------------------------------------------------------------
# Funções básicas
# ---------------------------------------------------------------------------

def percentual(acertos: int, total: int) -> float:
    """Fração de acerto de uma sessão. Exige total > 0 e 0 <= acertos <= total."""
    if total <= 0:
        raise ValueError("total deve ser maior que zero")
    if acertos < 0 or acertos > total:
        raise ValueError("acertos deve estar entre 0 e o total")
    return acertos / total


def faixa_da_tabela(pct: float) -> tuple[int, int]:
    """Devolve (dias, questões) da tabela para uma % de acerto."""
    for limite, dias, questoes in TABELA:
        if pct + EPS >= limite:
            return dias, questoes
    return TABELA[-1][1], TABELA[-1][2]


def peso_por_tamanho(total: int | None) -> float:
    """
    Quanto uma sessão vale conforme o número de questões.
    10 questões ou mais = peso cheio (1); menos que isso, proporcional
    (2 questões = 0,2). Sem informação de total, vale peso cheio.
    """
    if total is None:
        return 1.0
    return min(1.0, max(0, total) / QUESTOES_REFERENCIA)


def dominio(percentuais: list[float], totais: list[int] | None = None) -> float:
    """
    Domínio do assunto = média ponderada das últimas 3 sessões.

    Peso de cada sessão = peso da posição × peso do tamanho:
    - posição: 50% para a mais recente, 30% para a anterior, 20% para a
      antepenúltima;
    - tamanho: sessões com menos de 10 questões valem proporcionalmente
      menos (ver peso_por_tamanho). Assim, errar 1 de 2 questões mexe pouco
      no domínio, mas várias sessões ruins seguidas mexem bastante.

    Os pesos são normalizados para somar 1 (com menos de 3 sessões, ou com
    sessões pequenas, o que sobra é redistribuído).

    `percentuais` e `totais` estão em ordem cronológica (mais recente por último).
    """
    if not percentuais:
        return 0.0
    if totais is None:
        totais = [None] * len(percentuais)
    ultimas = list(zip(reversed(percentuais), reversed(totais)))[:3]   # mais recente primeiro
    pesos = [pos * peso_por_tamanho(t) for pos, (_, t) in zip(PESOS_DOMINIO, ultimas)]
    soma_pesos = sum(pesos)
    if soma_pesos == 0:          # só sessões com 0 questões (não deve acontecer)
        return ultimas[0][0]
    return sum(p * w for (p, _), w in zip(ultimas, pesos)) / soma_pesos


def fator_bonus(total: int | None, sugeridas: int) -> float:
    """
    Quanto o intervalo cresce numa sessão boa da sequência.

    Fez pelo menos as questões sugeridas -> dobra (x2). Fez menos -> cresce
    em proporção: 1 de 4 sugeridas -> x1,25; 3 de 6 -> x1,5. Assim uma
    sessão de 1 questão não vale o mesmo bônus que uma revisão completa.
    """
    if total is None or sugeridas <= 0:
        return 2.0
    return 1.0 + min(1.0, total / sugeridas)


def calcular_intervalo(
    percentuais: list[float],
    totais: list[int] | None = None,
    questoes_fixas: int | None = None,
    tetos: tuple[int, ...] = TETOS_APRENDIZADO,
    fator: float = 1.0,
    teto: int | None = None,
) -> tuple[int, int]:
    """
    Intervalo (em dias) até a próxima revisão e o tamanho da sequência boa atual.

    Percorre as sessões em ordem cronológica. Depois de cada sessão:
    - O intervalo base é o da tabela aplicada ao DOMÍNIO (média ponderada),
      e não só à última sessão. Uma sessão ruim e pequena reduz o intervalo
      aos poucos; várias seguidas o levam até o fundo da tabela.
    - Bônus: com 2 ou mais sessões seguidas >= 85% (e domínio >= 85%), o
      intervalo anterior cresce a cada nova sessão boa: dobra se a sessão
      teve pelo menos as questões sugeridas (15 -> 30 -> 60), ou cresce em
      proporção se teve menos (ver fator_bonus). Nunca fica abaixo do valor
      da tabela e é limitado a INTERVALO_MAXIMO.
    - Uma sessão abaixo de 85% zera a sequência e o intervalo volta ao da
      tabela para o domínio atual.
    - Fase de aprendizado: depois da sessão n (n <= len(tetos)) o intervalo
      fica limitado a tetos[n-1]. O bônus seguinte parte do valor limitado,
      então um assunto novo cresce aos poucos (7 -> 15 -> 30 -> 60).
    - Tamanho da prática: o intervalo ANDA até o valor acima na proporção das
      questões feitas em relação às sugeridas (ver peso_do_passo). Fez as
      sugeridas: anda o passo inteiro; fez metade: anda metade do caminho
      (para cima ou para baixo). Assim poucas questões nunca "provam" demais.
    - Ritmo: no fim, o intervalo é multiplicado por `fator` (mínimo 1 dia).
    - Teto do usuário: o resultado final nunca passa de `teto` dias.
    """
    if not percentuais:
        raise ValueError("é preciso ao menos uma sessão")
    if totais is None:
        totais = [None] * len(percentuais)
    intervalo = 1   # antes da primeira prática: como se voltasse no dia seguinte
    sequencia = 0
    sugeridas = questoes_sugeridas(0.0, questoes_fixas)   # o que o app pede para um assunto novo
    for i, pct in enumerate(percentuais):
        anterior = intervalo
        dom = dominio(percentuais[: i + 1], totais[: i + 1])
        dias_tabela, _ = faixa_da_tabela(dom)
        sequencia = sequencia + 1 if pct + EPS >= LIMIAR_BOM else 0
        if sequencia >= 2 and dom + EPS >= LIMIAR_BOM:
            # bônus: dobra (o tamanho da prática entra logo abaixo, no passo)
            alvo = min(max(intervalo * 2, dias_tabela), INTERVALO_MAXIMO)
        else:
            alvo = dias_tabela
        if i < len(tetos):
            alvo = intervalo_na_fase(tetos[i], dom)
        intervalo = max(1, arredondar(anterior + (alvo - anterior) * peso_do_passo(totais[i], sugeridas)))
        sugeridas = questoes_sugeridas(dom, questoes_fixas)
    final = aplicar_ritmo(intervalo, fator)
    if teto:
        final = min(final, teto)
    return final, sequencia


def peso_do_passo(total: int | None, sugeridas: int) -> float:
    """
    Quanto o intervalo anda numa prática: questões feitas / questões que o app
    sugeria para aquele assunto (o número fixo escolhido, ou o da tabela),
    contando no máximo 10 como referência. Sem o total, anda o passo inteiro.
      sugeridas 10, fez 5 -> 0,5     sugeridas 4, fez 5 -> 1     fixo 5, fez 2 -> 0,4
    """
    if total is None:
        return 1.0
    referencia = min(QUESTOES_REFERENCIA, max(1, sugeridas))
    return min(1.0, max(0, total) / referencia)


def arredondar(x: float) -> int:
    """Arredonda com o "meio" para baixo (4,5 -> 4), como o ritmo."""
    return ceil(x - 0.5 - 1e-9)


def intervalo_na_fase(teto_fase: int, dom: float) -> int:
    """
    Fase de aprendizado: o assunto novo volta no teto do degrau só se foi bem.
      bom   (domínio >= 85%)  -> teto do degrau (ex.: 3 dias)
      médio (50% a 84%)       -> metade do teto, arredondando para cima (ex.: 2)
      mal   (abaixo de 50%)   -> 1 dia
    """
    if dom + EPS >= LIMIAR_BOM:
        return teto_fase
    if dom + EPS >= 0.50:
        return max(1, ceil(teto_fase / 2))
    return 1


def aplicar_ritmo(intervalo: int, fator: float) -> int:
    """
    Intervalo ajustado ao ritmo de estudo, arredondando o "meio" para baixo
    (ex.: 30 x 0,75 = 22,5 -> 22; 3 x 0,5 = 1,5 -> 1). Assim o assunto fraco
    volta em 3 dias no Leve, 2 no Moderado e 1 no Intenso.
    """
    return max(1, ceil(intervalo * fator - 0.5 - 1e-9))


def fator_do_ritmo(ritmo: str | None) -> float:
    return RITMOS.get(ritmo or "leve", 1.0)


def questoes_sugeridas(dominio_atual: float, numero_fixo: int | None = None) -> int:
    """Questões para a próxima revisão: o número fixo configurado ou o da tabela (pelo domínio)."""
    if numero_fixo:
        return numero_fixo
    return faixa_da_tabela(dominio_atual)[1]


def dias_de_atraso(proxima_revisao: date, hoje: date) -> int:
    """Dias passados desde a data de revisão (0 se ainda não venceu)."""
    return max(0, (hoje - proxima_revisao).days)


def dominio_efetivo(dominio_atual: float, atraso_dias: int) -> float:
    """
    Esquecimento: perde 5 pontos percentuais por semana COMPLETA de atraso.
    Ex.: 6 dias de atraso -> sem perda; 14 dias -> -10%. Nunca fica negativo.
    """
    semanas = floor(max(0, atraso_dias) / 7)
    return max(0.0, dominio_atual - PERDA_POR_SEMANA * semanas)


def prioridade(dominio_ef: float, atraso_dias: int) -> float:
    """prioridade = (1 − domínio efetivo) + dias de atraso × 0,1"""
    return (1 - dominio_ef) + max(0, atraso_dias) * PESO_ATRASO


# ---------------------------------------------------------------------------
# Estado completo de um assunto
# ---------------------------------------------------------------------------

@dataclass
class EstadoAssunto:
    """Tudo o que o app precisa saber sobre um assunto em uma data."""
    assunto_id: int
    n_sessoes: int
    ultima_data: date
    ultimo_pct: float
    dominio: float
    intervalo: int
    sequencia_boa: int
    proxima_revisao: date
    atraso: int
    dominio_efetivo: float
    prioridade: float
    questoes: int
    fase_total: int = len(TETOS_APRENDIZADO)   # quantas sessões dura a fase de aprendizado

    @property
    def vencido(self) -> bool:
        return self.atraso > 0

    @property
    def em_aprendizado(self) -> bool:
        """True enquanto o intervalo ainda está sob o teto da fase de aprendizado."""
        return self.n_sessoes <= self.fase_total


def juntar_por_dia(sessoes: list[tuple[date, int, int]]) -> list[tuple[date, int, int]]:
    """
    Práticas do mesmo assunto no mesmo dia contam como UMA só, somando acertos
    e total (ex.: 5/5 de manhã + 3/5 à tarde = 8/10 naquele dia). No histórico
    elas continuam separadas; a junção é só para o cálculo.
    """
    por_dia: dict[date, list[int]] = {}
    for d, acertos, total in sessoes:
        soma = por_dia.setdefault(d, [0, 0])
        soma[0] += acertos
        soma[1] += total
    return [(d, a, t) for d, (a, t) in sorted(por_dia.items())]


def analisar_assunto(
    assunto_id: int,
    sessoes: list[tuple[date, int, int]],
    hoje: date,
    questoes_fixas: int | None = None,
    fator: float = 1.0,
    tetos: tuple[int, ...] = TETOS_APRENDIZADO,
    teto: int | None = None,
    dias_estudo: list[int] | None = None,
    folga: int = 0,
    meta: date | None = None,
) -> EstadoAssunto | None:
    """
    Calcula o estado de um assunto a partir das suas sessões.
    Devolve None se o assunto ainda não tem sessões (é um assunto novo).
    """
    if not sessoes:
        return None
    sessoes = juntar_por_dia(sessoes)
    pcts =[percentual(acertos, total) for _, acertos, total in sessoes]
    totais = [total for _, _, total in sessoes]

    dom = dominio(pcts, totais)
    intervalo, sequencia = calcular_intervalo(pcts, totais, questoes_fixas, tetos=tetos, fator=fator, teto=teto)
    ultima_data = sessoes[-1][0]
    # Data da meta (prova): o intervalo nunca passa dela (ver limite_pela_meta).
    limite = limite_pela_meta(ultima_data, meta)
    if limite:
        intervalo = min(intervalo, limite)
    # Revisão que cairia num dia sem estudo daquela seção vai para o próximo dia de estudo.
    proxima = ajustar_para_dia_de_estudo(ultima_data + timedelta(days=intervalo), dias_estudo)
    # `folga`: no ciclo de estudos, a seção pode demorar alguns dias para chegar
    # na vez; esses dias de espera não contam como atraso.
    atraso = max(0, dias_de_atraso(proxima, hoje) - folga)
    dom_ef = dominio_efetivo(dom, atraso)

    return EstadoAssunto(
        assunto_id=assunto_id,
        n_sessoes=len(sessoes),
        ultima_data=ultima_data,
        ultimo_pct=pcts[-1],
        dominio=dom,
        intervalo=intervalo,
        sequencia_boa=sequencia,
        proxima_revisao=proxima,
        atraso=atraso,
        dominio_efetivo=dom_ef,
        prioridade=prioridade(dom_ef, atraso),
        questoes=questoes_sugeridas(dom, questoes_fixas),
        fase_total=len(tetos),
    )


# ---------------------------------------------------------------------------
# Data da meta (prova)
# ---------------------------------------------------------------------------

RETA_FINAL = 30            # últimos 30 dias antes da prova
MARGEM_MIN, MARGEM_MAX = 7, 60   # dias reservados só para revisar, antes da prova


def limite_pela_meta(ultima: date, meta: date | None) -> int | None:
    """
    Máximo de dias até a próxima revisão para o assunto não "pular" a prova:
    metade dos dias que faltam, contando da última prática. Assim os
    intervalos encolhem conforme a prova chega (60 dias antes -> até 30;
    14 -> 7; 2 -> 1) e todo assunto tem uma revisão perto dela.
    Sem meta, ou com a prova já passada, não há limite (None).
    """
    if not meta:
        return None
    faltam = (meta - ultima).days
    if faltam <= 0:
        return None
    return max(1, faltam // 2)


def margem_de_revisao(faltam: int) -> int:
    """Dias antes da prova reservados só para revisão: 1/5 do tempo, entre 7 e 60."""
    return min(MARGEM_MAX, max(MARGEM_MIN, faltam // 5))


def plano_da_meta(hoje: date, meta: date, nao_iniciados: int, iniciados_semana: int) -> dict:
    """
    Ritmo para começar todo o conteúdo a tempo de revisar antes da prova.

    - fim_conteudo: data até a qual todos os assuntos devem ter sido começados
      (a prova menos a margem de revisão);
    - por_semana: assuntos novos por semana para chegar lá;
    - status: 'passou' (a prova já foi), 'concluido' (tudo começado),
      'atrasado' (o prazo do conteúdo passou e ainda falta assunto),
      'abaixo' (nos últimos 7 dias começou menos que o ritmo pede) ou 'em_dia'.
    """
    faltam = (meta - hoje).days
    fim = meta - timedelta(days=margem_de_revisao(max(0, faltam)))
    dias_conteudo = (fim - hoje).days
    if nao_iniciados <= 0:
        por_semana = 0
    elif dias_conteudo <= 0:
        por_semana = nao_iniciados
    else:
        por_semana = ceil(nao_iniciados * 7 / dias_conteudo)
    if faltam < 0:
        status = "passou"
    elif nao_iniciados <= 0:
        status = "concluido"
    elif dias_conteudo <= 0:
        status = "atrasado"
    elif iniciados_semana < por_semana:
        status = "abaixo"
    else:
        status = "em_dia"
    return {
        "meta": meta, "faltam": faltam, "fim_conteudo": fim, "por_semana": por_semana,
        "nao_iniciados": nao_iniciados, "iniciados_semana": iniciados_semana,
        "status": status, "reta_final": 0 <= faltam <= RETA_FINAL,
    }


# ---------------------------------------------------------------------------
# Agenda: que tipo de revisão acontece hoje
# ---------------------------------------------------------------------------

# fixa     -> revisão grande só no(s) dia(s) fixo(s)
# diaria   -> todo dia, revisão mínima (poucos assuntos)
# ambos    -> revisão grande no dia fixo + mínima nos outros dias
# completa -> todo dia, tudo que vence ou está atrasado (fase só de questões)
MODOS = ("fixa", "diaria", "ambos", "completa")
MODOS_COM_DIA_FIXO = ("fixa", "ambos")
MODOS_COM_MINIMA = ("diaria", "ambos")


def estuda_no_dia(dia: date, dias_estudo: list[int] | None) -> bool:
    """A seção é estudada neste dia? Lista vazia/None = todo dia."""
    return not dias_estudo or dia.weekday() in dias_estudo


def ajustar_para_dia_de_estudo(d: date, dias_estudo: list[int] | None) -> date:
    """
    Se a revisão cai num dia em que a seção não é estudada, ela passa para o
    próximo dia de estudo. Assim esses dias não contam como atraso.
    """
    if not dias_estudo:
        return d
    for i in range(7):
        if (d + timedelta(days=i)).weekday() in dias_estudo:
            return d + timedelta(days=i)
    return d


def proximo_dia_fixo(hoje: date, dias_fixos: list[int]) -> date | None:
    """Próxima data (depois de hoje) que cai em um dos dias fixos."""
    if not dias_fixos:
        return None
    for i in range(1, 8):
        d = hoje + timedelta(days=i)
        if d.weekday() in dias_fixos:
            return d
    return None


def tipo_de_revisao(modo: str, dias_fixos: list[int], hoje: date) -> str | None:
    """
    'grande'  -> hoje é dia fixo (modos 'fixa' e 'ambos');
    'diaria'  -> revisão mínima (modo 'diaria', ou 'ambos' fora do dia fixo);
    'completa'-> modo 'completa': todo dia, tudo que vence;
    None      -> modo 'fixa' fora do dia fixo: não há revisão hoje.
    """
    if modo == "completa":
        return "completa"
    e_dia_fixo = hoje.weekday() in dias_fixos
    if modo in ("fixa", "ambos") and e_dia_fixo:
        return "grande"
    if modo in ("diaria", "ambos"):
        return "diaria"
    return None


# ---------------------------------------------------------------------------
# Seleção das revisões
# ---------------------------------------------------------------------------

def ordenar_por_prioridade(estados: list[EstadoAssunto]) -> list[EstadoAssunto]:
    """Maior prioridade primeiro; empate -> menor domínio efetivo primeiro."""
    return sorted(estados, key=lambda e: (-e.prioridade, e.dominio_efetivo, e.assunto_id))


def selecionar_revisao_diaria(
    estados: list[EstadoAssunto],
    hoje: date,
    n: int,
    secao_de: dict[int, str] | None = None,
) -> list[EstadoAssunto]:
    """
    Revisão do dia: só os assuntos que já venceram, até n POR SEÇÃO,
    começando pelos que mais precisam (maior prioridade). O que passar do
    limite continua vencido e entra nos próximos dias.
    `secao_de` liga cada assunto à sua seção (sem ele, o limite vale para tudo).
    """
    if n <= 0:
        return []
    secao_de = secao_de or {}
    escolhidos: list[EstadoAssunto] = []
    por_secao: dict[str, int] = {}
    for e in ordenar_por_prioridade([e for e in estados if e.proxima_revisao <= hoje]):
        sec = secao_de.get(e.assunto_id, "")
        if por_secao.get(sec, 0) < n:
            escolhidos.append(e)
            por_secao[sec] = por_secao.get(sec, 0) + 1
    return escolhidos


def selecionar_revisao_grande(
    estados: list[EstadoAssunto],
    hoje: date,
    proximo_fixo: date | None,
) -> list[EstadoAssunto]:
    """
    Revisão grande (dia fixo): tudo que já venceu e não foi feito + tudo que
    vence antes do próximo dia fixo, ordenado por prioridade. Sem limite.
    """
    limite = proximo_fixo or (hoje + timedelta(days=1))
    itens = [e for e in estados if e.proxima_revisao < limite]
    return ordenar_por_prioridade(itens)


def dominio_do_grupo(dominios: list[float]) -> float | None:
    """
    Domínio de um assunto que tem subassuntos: média simples do domínio
    efetivo dos subassuntos já estudados (None se nenhum foi estudado).
    Cada subassunto pesa igual, para que um ponto fraco não fique escondido
    atrás de um subassunto com muitas sessões.
    """
    if not dominios:
        return None
    return sum(dominios) / len(dominios)


def selecionar_revisao_completa(estados: list[EstadoAssunto], hoje: date) -> list[EstadoAssunto]:
    """
    Revisão completa do dia (fase só de questões): tudo que vence hoje ou já
    venceu, da maior para a menor prioridade. Sem limite de assuntos.
    """
    return ordenar_por_prioridade([e for e in estados if e.proxima_revisao <= hoje])


# ---------------------------------------------------------------------------
# Ciclo de estudos
# ---------------------------------------------------------------------------

def secoes_da_vez(itens: list[dict], k: int, dia: date) -> list[dict]:
    """
    Ciclo de estudos: fila de seções que se repete. Cada item tem `posicao`
    (ordem na fila), `rodada` (quantas vezes já foi feito/pulado) e
    `ultimo_dia` (data em que foi feito pela última vez).

    A vez do dia são os k primeiros pela ordem (rodada, posicao). Um item
    feito HOJE conta com a rodada anterior, para continuar aparecendo (com ✓)
    até o fim do dia em vez de dar lugar ao próximo. Se a pessoa não estuda
    num dia, nada muda: a fila espera.
    """
    if k <= 0:
        return []
    def chave(it):
        feito_hoje = it.get("ultimo_dia") == dia
        return (it["rodada"] - (1 if feito_hoje else 0), it["posicao"])
    return sorted(itens, key=chave)[:k]


def folga_do_ciclo(n_itens: int, k: int) -> int:
    """Dias que uma seção pode esperar a vez dela numa volta do ciclo."""
    if n_itens <= 0 or k <= 0:
        return 0
    return max(0, ceil(n_itens / k) - 1)


def classificar_para_mapa(estado: EstadoAssunto, hoje: date) -> str:
    """
    Grupo do assunto no mapa de domínio:
    'agora'    -> revisão vencida ou para hoje;
    'dominado' -> domínio efetivo >= 85% e revisão no futuro;
    'esperar'  -> o resto.
    """
    if estado.proxima_revisao <= hoje:
        return "agora"
    if estado.dominio_efetivo + EPS >= LIMIAR_BOM:
        return "dominado"
    return "esperar"


# ---------------------------------------------------------------------------
# Flashcards
# ---------------------------------------------------------------------------
# Cada cartão segue a MESMA lógica dos assuntos: cada resposta conta como uma
# prática com uma % de acerto, e o intervalo sai da tabela pelo domínio, com
# fase de aprendizado, bônus, ritmo, máximo de dias e data da prova.

NOTAS_CARTAO = ("errei", "demorei", "acertei")
PONTOS_CARTAO = {"errei": 0.0, "demorei": 0.75, "acertei": 1.0}
NOVOS_POR_DIA = 20          # cartões novos apresentados por dia (todos os baralhos)


def agenda_cartao(
    respostas: list[tuple[date, str]],
    fator: float = 1.0,
    tetos: tuple[int, ...] = TETOS_APRENDIZADO,
    teto: int | None = None,
    meta: date | None = None,
) -> tuple[date, int] | None:
    """
    Próxima revisão do cartão e o intervalo, a partir das respostas
    [(data, 'errei' | 'demorei' | 'acertei'), ...]. None = cartão novo.
      errei   = 0%   (volta logo: 1 dia na fase de aprendizado, 3 dias depois)
      demorei = 75%  (acertou, mas foi difícil lembrar)
      acertei = 100%
    """
    if not respostas:
        return None
    # Como no Anki: errou, o cartão volta na mesma sessão até você acertar.
    # Para a agenda vale só a PRIMEIRA resposta de cada dia; as outras do mesmo
    # dia são os passos de reaprendizado.
    respostas = sorted(respostas, key=lambda r: r[0])
    vistos: set[date] = set()
    respostas = [r for r in respostas if not (r[0] in vistos or vistos.add(r[0]))]
    pcts = [PONTOS_CARTAO[n] for _, n in respostas]
    intervalo, _ = calcular_intervalo(pcts, None, None, tetos=tetos, fator=fator, teto=teto)
    ultima = respostas[-1][0]
    limite = limite_pela_meta(ultima, meta)
    if limite:
        intervalo = min(intervalo, limite)
    return ultima + timedelta(days=intervalo), intervalo
