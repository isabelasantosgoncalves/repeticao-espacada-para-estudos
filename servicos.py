"""
Camada entre o banco e a lógica: busca os dados do usuário e chama logica.py.
Todas as consultas filtram por usuario_id.
"""

from __future__ import annotations

import os
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta

import logica as L

NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def hoje() -> date:
    """Data de hoje no fuso configurado (APP_TZ), útil no servidor em UTC."""
    tz = os.environ.get("APP_TZ", "America/Sao_Paulo")
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz)).date()
    except Exception:
        return date.today()


def para_data(texto: str) -> date:
    return date.fromisoformat(texto)


def ler_dias(texto: str | None) -> list[int]:
    """'0,2,4' -> [0, 2, 4]. Vazio -> [] (todo dia)."""
    return sorted({int(d) for d in (texto or "").split(",") if d.strip().isdigit() and 0 <= int(d) <= 6})


def usa_dias_por_secao(cfg: dict) -> bool:
    """Os dias de cada matéria só valem se a pessoa escolheu "cada matéria tem seus dias"."""
    return cfg.get("distribuicao") == "dias"


def dias_por_assunto(db, uid: int, cfg: dict | None = None) -> dict[int, list[int]]:
    """Dias de estudo da matéria de cada assunto ([] = todo dia)."""
    if cfg is not None and not usa_dias_por_secao(cfg):
        return {}
    return {r["id"]: ler_dias(r["dias_estudo"]) for r in db.execute(
        """SELECT a.id, m.dias_estudo FROM assuntos a JOIN materias m ON m.id = a.materia_id
           WHERE a.usuario_id = ?""", (uid,))}


# ---------------------------------------------------------------------------
# Data da prova (meta): fica na SEÇÃO (ex.: ENEM) e vale para todas as matérias
# dela. Pode ser exata (AAAA-MM-DD) ou só o mês (AAAA-MM); com só o mês, os
# cálculos usam o dia 1º, para nenhuma revisão passar da prova.
# ---------------------------------------------------------------------------

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def normalizar_meta(texto) -> str | None:
    """'2027-11-07' ou '2027-11' -> o mesmo texto; vazio ou inválido -> None."""
    texto = str(texto or "").strip()
    try:
        if len(texto) == 7:
            date.fromisoformat(texto + "-01")
            return texto
        if len(texto) == 10:
            return date.fromisoformat(texto).isoformat()
    except ValueError:
        pass
    return None


def ler_meta(texto: str | None) -> date | None:
    """Data usada nos cálculos: a exata, ou o dia 1º se for só o mês."""
    texto = normalizar_meta(texto)
    if not texto:
        return None
    return date.fromisoformat(texto + "-01" if len(texto) == 7 else texto)


def meta_aproximada(texto: str | None) -> bool:
    return bool(normalizar_meta(texto)) and len(str(texto).strip()) == 7


def meta_txt(texto: str | None) -> str:
    """'2027-11' -> 'nov/2027'; '2027-11-07' -> '07/11/2027'."""
    t = normalizar_meta(texto)
    if not t:
        return ""
    if len(t) == 7:
        return f"{MESES[int(t[5:7]) - 1]}/{t[:4]}"
    return f"{t[8:10]}/{t[5:7]}/{t[:4]}"


def ler_fim_conteudo(form) -> str | None:
    """Campo "Terminar conteúdo novo até": vazio = automático; senão, uma data."""
    texto = (form.get("fim_conteudo") or "").strip()
    if not texto:
        return None
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError:
        raise ValueError("Data para terminar o conteúdo inválida.")


def ler_campo_meta(form, prefixo: str) -> str | None:
    """
    Campos de prova de um formulário: `<prefixo>_tipo` (sem, mes ou dia) e
    `<prefixo>_mes` / `<prefixo>_dia`. Devolve a data a gravar ou None.
    """
    tipo = form.get(f"{prefixo}_tipo")
    if tipo == "mes":
        valor = normalizar_meta(form.get(f"{prefixo}_mes"))
        if not valor or len(valor) != 7:
            raise ValueError("Escolha o mês da prova.")
        return valor
    if tipo == "dia":
        valor = normalizar_meta(form.get(f"{prefixo}_dia"))
        if not valor or len(valor) != 10:
            raise ValueError("Escolha o dia da prova.")
        return valor
    return None


def metas_por_materia(db, uid: int) -> dict[int, date]:
    """Data da prova de cada matéria (a da seção dela), só as que têm prova."""
    res = {}
    for r in db.execute(
            """SELECT m.id, s.data_meta FROM materias m JOIN secoes s ON s.id = m.secao_id
               WHERE m.usuario_id = ?""", (uid,)):
        meta = ler_meta(r["data_meta"])
        if meta:
            res[r["id"]] = meta
    return res


def metas_por_assunto(db, uid: int) -> dict[int, date]:
    """Data da prova que vale para cada assunto."""
    por_materia = metas_por_materia(db, uid)
    return {r["id"]: por_materia[r["materia_id"]] for r in db.execute(
        "SELECT id, materia_id FROM assuntos WHERE usuario_id = ?", (uid,)) if r["materia_id"] in por_materia}


def listar_secoes(db, uid: int) -> list[dict]:
    """Seções do usuário (com a prova já formatada), em ordem alfabética."""
    res = []
    for r in db.execute("SELECT id, nome, data_meta, fim_conteudo FROM secoes WHERE usuario_id = ?", (uid,)):
        sec = dict(r)
        try:
            sec["fim"] = date.fromisoformat(sec["fim_conteudo"]) if sec["fim_conteudo"] else None
        except ValueError:
            sec["fim"] = None
        sec["meta"] = ler_meta(sec["data_meta"])
        sec["meta_txt"] = meta_txt(sec["data_meta"])
        sec["aproximada"] = meta_aproximada(sec["data_meta"])
        res.append(sec)
    return sorted(res, key=lambda x: chave_ordem(x["nome"]))


# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------

def carregar_config(db, uid: int) -> dict:
    row = db.execute("SELECT * FROM configuracoes WHERE usuario_id = ?", (uid,)).fetchone()
    if row is None:
        db.execute("INSERT INTO configuracoes (usuario_id) VALUES (?)", (uid,))
        db.commit()
        row = db.execute("SELECT * FROM configuracoes WHERE usuario_id = ?", (uid,)).fetchone()
    cfg = dict(row)
    cfg["dias_fixos"] = sorted(int(d) for d in cfg["dias_fixos"].split(",") if d.strip() != "")
    return cfg


def fator(cfg: dict) -> float:
    return L.fator_do_ritmo(cfg.get("ritmo"))


def tetos(cfg: dict) -> tuple[int, ...]:
    return L.tetos_da_fase(cfg.get("aprendizado"))


def questoes_fixas(cfg: dict) -> int | None:
    return cfg["questoes_modo"] == "fixo" and cfg["questoes_fixas"] or None


# ---------------------------------------------------------------------------
# Assuntos e estados
# ---------------------------------------------------------------------------

def listar_assuntos(db, uid: int) -> list[dict]:
    """
    Todos os assuntos do usuário, já com:
    - pai: nome do assunto pai (subassuntos) ou None;
    - rotulo: "Pai › Sub" ou só o nome;
    - grupo: True se o assunto tem subassuntos (vira um agrupador: as sessões
      e revisões acontecem nos subassuntos).
    Ordenados por matéria, depois pai, com os subassuntos logo abaixo do pai.
    """
    rows = db.execute(
        """SELECT a.id, a.nome, a.materia_id, a.parent_id, m.nome AS materia, p.nome AS pai,
                  m.dias_estudo AS dias_materia,
                  (SELECT COUNT(*) FROM assuntos f WHERE f.parent_id = a.id) AS n_filhos
           FROM assuntos a
           JOIN materias m ON m.id = a.materia_id
           LEFT JOIN assuntos p ON p.id = a.parent_id
           WHERE a.usuario_id = ?
           ORDER BY m.nome COLLATE NOCASE, COALESCE(p.nome, a.nome) COLLATE NOCASE,
                    a.parent_id IS NOT NULL, a.nome COLLATE NOCASE""",
        (uid,),
    ).fetchall()
    res = []
    for r in rows:
        a = dict(r)
        a["rotulo"] = f"{a['pai']} › {a['nome']}" if a["pai"] else a["nome"]
        a["grupo"] = a["n_filhos"] > 0
        a["dias_materia"] = ler_dias(a["dias_materia"])
        res.append(a)
    # Ordem alfabética ignorando acentos (o SQLite poria "Álgebra" depois de "Z")
    res.sort(key=lambda a: (chave_ordem(a["materia"]), chave_ordem(a["pai"] or a["nome"]),
                            a["parent_id"] is not None, chave_ordem(a["nome"])))
    return res


def chave_ordem(texto: str) -> str:
    """Texto sem acentos e em minúsculas, para ordenar como num dicionário."""
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn").casefold()


def listar_folhas(db, uid: int) -> list[dict]:
    """Assuntos que recebem sessões e entram nas revisões (os que não são grupo)."""
    return [a for a in listar_assuntos(db, uid) if not a["grupo"]]


def sessoes_por_assunto(db, uid: int, antes_de: date | None = None) -> dict[int, list]:
    """{assunto_id: [(data, acertos, total), ...]} em ordem cronológica."""
    sql = "SELECT assunto_id, data, acertos, total FROM sessoes WHERE usuario_id = ?"
    params: list = [uid]
    if antes_de:
        sql += " AND data < ?"
        params.append(antes_de.isoformat())
    sql += " ORDER BY data, id"
    res: dict[int, list] = defaultdict(list)
    for r in db.execute(sql, params):
        res[r["assunto_id"]].append((para_data(r["data"]), r["acertos"], r["total"]))
    return res


# ---------------------------------------------------------------------------
# Ciclo de estudos
# ---------------------------------------------------------------------------

def usa_ciclo(cfg: dict) -> bool:
    return cfg.get("distribuicao") == "ciclo"


def ler_ciclo(db, uid: int) -> list[dict]:
    """Itens do ciclo, na ordem da fila."""
    res = []
    for r in db.execute(
            """SELECT c.id, c.materia_id, c.posicao, c.rodada, c.ultimo_dia, m.nome
               FROM ciclo_itens c JOIN materias m ON m.id = c.materia_id
               WHERE c.usuario_id = ? ORDER BY c.posicao, c.id""", (uid,)):
        it = dict(r)
        it["ultimo_dia"] = para_data(it["ultimo_dia"]) if it["ultimo_dia"] else None
        res.append(it)
    return res


def vez_do_ciclo(db, uid: int, dia: date, cfg: dict) -> list[dict]:
    """Matérias da vez no dia (com `feito` = já estudada nesse dia)."""
    vez = L.secoes_da_vez(ler_ciclo(db, uid), cfg.get("secoes_por_dia", 2), dia)
    return [dict(it, feito=it["ultimo_dia"] == dia) for it in vez]


def marcar_ciclo(db, uid: int, materia_id: int, dia: date, cfg: dict):
    """Registrou prática numa matéria da vez: aquele item do ciclo conta como feito."""
    if not usa_ciclo(cfg):
        return
    for it in vez_do_ciclo(db, uid, dia, cfg):
        if it["materia_id"] == materia_id and not it["feito"]:
            db.execute("UPDATE ciclo_itens SET rodada = rodada + 1, ultimo_dia = ? WHERE id = ? AND usuario_id = ?",
                       (dia.isoformat(), it["id"], uid))
            return


def estados(db, uid: int, dia: date, cfg: dict, antes_de: date | None = None,
            ids: set[int] | None = None) -> dict[int, L.EstadoAssunto]:
    """Estado de cada assunto que já tem sessões (só os de `ids`, se informado)."""
    fixas = questoes_fixas(cfg)
    dias = dias_por_assunto(db, uid, cfg)
    metas = metas_por_assunto(db, uid)
    folga = 0
    if usa_ciclo(cfg):
        n_itens = db.execute("SELECT COUNT(*) FROM ciclo_itens WHERE usuario_id = ?", (uid,)).fetchone()[0]
        folga = L.folga_do_ciclo(n_itens, cfg.get("secoes_por_dia", 2))
    res = {}
    for aid, sess in sessoes_por_assunto(db, uid, antes_de).items():
        if ids is not None and aid not in ids:
            continue
        e = L.analisar_assunto(aid, sess, dia, fixas, fator=fator(cfg), tetos=tetos(cfg),
                               teto=cfg.get("teto_dias"), dias_estudo=dias.get(aid), folga=folga,
                               meta=metas.get(aid))
        if e:
            res[aid] = e
    return res


# ---------------------------------------------------------------------------
# Tela "Hoje"
# ---------------------------------------------------------------------------

def selecao_do_dia(db, uid: int, dia: date, cfg: dict, assuntos: dict) -> dict:
    """
    Lista de revisão de um dia, com as mesmas regras da tela Hoje.
    Usa só as práticas ANTERIORES ao dia: para hoje, a lista não muda enquanto
    o usuário registra resultados; para amanhã, já conta o que foi feito hoje.
    """
    est = estados(db, uid, dia, cfg, antes_de=dia, ids=set(assuntos))
    tipo = L.tipo_de_revisao(cfg["modo"], cfg["dias_fixos"], dia)
    proximo_fixo = L.proximo_dia_fixo(dia, cfg["dias_fixos"])

    # Matérias que não são estudadas no dia ficam fora da revisão
    # (só quando a pessoa usa "cada matéria tem seus dias").
    if not usa_dias_por_secao(cfg):
        assuntos = {aid: dict(a, dias_materia=[]) for aid, a in assuntos.items()}
    pausadas = {a["materia"] for a in assuntos.values() if not L.estuda_no_dia(dia, a["dias_materia"])}
    est = {aid: e for aid, e in est.items() if L.estuda_no_dia(dia, assuntos[aid]["dias_materia"])}

    # Ciclo de estudos: só as matérias da vez entram na revisão do dia.
    vez = vez_do_ciclo(db, uid, dia, cfg) if usa_ciclo(cfg) else []
    if vez:
        da_vez = {it["materia_id"] for it in vez}
        est = {aid: e for aid, e in est.items() if assuntos[aid]["materia_id"] in da_vez}

    if tipo == "grande":
        selecao = L.selecionar_revisao_grande(list(est.values()), dia, proximo_fixo)
    elif tipo == "diaria":
        secao_de = {aid: assuntos[aid]["materia_id"] for aid in est}
        selecao = L.selecionar_revisao_diaria(list(est.values()), dia, cfg["revisao_minima"], secao_de)
    elif tipo == "completa":
        selecao = L.selecionar_revisao_completa(list(est.values()), dia)
    else:
        selecao = []

    # Atrasou? Revisões vencidas que ficaram fora do limite podem ser puxadas
    # para o dia ("fazer mais hoje"). Só existem quando há atraso acumulado.
    puxados = {r[0] for r in db.execute(
        "SELECT assunto_id FROM estudo_do_dia WHERE usuario_id = ? AND data = ?", (uid, dia.isoformat()))}
    na_lista = {e.assunto_id for e in selecao}
    fora = L.ordenar_por_prioridade([e for aid, e in est.items()
                                     if e.proxima_revisao <= dia and aid not in na_lista and aid in assuntos])
    extras = [e for e in fora if e.assunto_id in puxados]
    restantes = [e for e in fora if e.assunto_id not in puxados]

    return {"tipo": tipo, "proximo_fixo": proximo_fixo,
            "selecao": [e for e in selecao if e.assunto_id in assuntos] + extras,
            "pausadas": pausadas, "vez": vez,
            "puxados": {e.assunto_id for e in extras}, "restantes": restantes}


def puxar_revisoes(db, uid: int, dia: date, quantos: int | None) -> int:
    """
    Coloca na lista do dia as próximas revisões vencidas que ficaram de fora
    (as de maior prioridade primeiro). `quantos` None = todas. Devolve quantas entraram.
    """
    cfg = carregar_config(db, uid)
    assuntos = {a["id"]: a for a in listar_folhas(db, uid)}
    feitos = {r[0] for r in db.execute(
        "SELECT DISTINCT assunto_id FROM sessoes WHERE usuario_id = ? AND data = ?", (uid, dia.isoformat()))}
    restantes = [e for e in selecao_do_dia(db, uid, dia, cfg, assuntos)["restantes"] if e.assunto_id not in feitos]
    escolhidos = restantes if quantos is None else restantes[:max(0, quantos)]
    for e in escolhidos:
        db.execute("INSERT OR IGNORE INTO estudo_do_dia (usuario_id, assunto_id, data) VALUES (?, ?, ?)",
                   (uid, e.assunto_id, dia.isoformat()))
    db.commit()
    return len(escolhidos)


def montar_hoje(db, uid: int, dia: date) -> dict:
    """
    Monta o painel da tela Hoje (e a prévia de amanhã).

    A seleção da revisão usa só as sessões ANTERIORES a hoje, para que a lista
    não mude enquanto o usuário registra resultados ao longo do dia. Os
    assuntos já feitos hoje aparecem marcados como concluídos.
    """
    cfg = carregar_config(db, uid)
    assuntos = {a["id"]: a for a in listar_folhas(db, uid)}   # grupos não entram na revisão
    sel = selecao_do_dia(db, uid, dia, cfg, assuntos)
    tipo, proximo_fixo, selecao = sel["tipo"], sel["proximo_fixo"], sel["selecao"]
    pausadas, vez = sel["pausadas"], sel["vez"]
    puxados, restantes = sel["puxados"], sel["restantes"]

    # Prévia de amanhã: mesmas regras, já contando as práticas de hoje.
    amanha_dia = dia + timedelta(days=1)
    sel_am = selecao_do_dia(db, uid, amanha_dia, cfg, assuntos)
    amanha = {
        "data": amanha_dia,
        "tipo": sel_am["tipo"],
        "itens": [{"assunto": assuntos[e.assunto_id], "estado": e} for e in sel_am["selecao"]],
        "questoes": sum(e.questoes for e in sel_am["selecao"]),
        "pausadas": sorted(sel_am["pausadas"], key=chave_ordem),
        "vez": sel_am["vez"],
    }

    # Sessões já registradas hoje
    feitas_hoje: dict[int, list] = defaultdict(list)
    for r in db.execute(
        "SELECT assunto_id, acertos, total FROM sessoes WHERE usuario_id = ? AND data = ? ORDER BY id",
        (uid, dia.isoformat())):
        feitas_hoje[r["assunto_id"]].append(dict(r))

    revisao = []
    for e in selecao:
        if e.assunto_id in assuntos:
            revisao.append({"assunto": assuntos[e.assunto_id], "estado": e,
                            "feito": feitas_hoje.get(e.assunto_id), "extra": e.assunto_id in puxados})

    # ---- Painel: números do dia, próximos dias e progresso no conteúdo ----
    # Estado ATUAL (inclui as sessões de hoje) para atrasos, domínio e agenda.
    atual = estados(db, uid, dia, cfg, ids=set(assuntos))

    # Próximos dias: a mesma revisão planejada da página "Próximas revisões".
    plano = planejar_revisoes(db, uid, dia, 8, cfg)
    proximos = [{"data": p["data"], "n": len(p["itens"])} for p in plano[1:]]

    com_sessao = {r["assunto_id"] for r in db.execute(
        "SELECT DISTINCT assunto_id FROM sessoes WHERE usuario_id = ?", (uid,))}
    nao_estudados = [a for a in assuntos.values() if a["id"] not in com_sessao]

    metas = montar_metas(db, uid, dia, assuntos)

    # Sessões de hoje em assuntos que não estavam na revisão (ex.: assunto novo)
    na_revisao = {item["assunto"]["id"] for item in revisao}
    extras = [{"assunto": assuntos[aid], "feito": f} for aid, f in feitas_hoje.items()
              if aid in assuntos and aid not in na_revisao]

    return {
        "cfg": cfg,
        "tipo": tipo,
        "proximo_fixo": proximo_fixo,
        "revisao": revisao,
        "feitas": sum(1 for item in revisao if item["feito"]),
        "total_questoes": sum(item["estado"].questoes for item in revisao),
        "atrasados": sum(1 for e in atual.values() if e.atraso > 0),
        "dominio_medio": (sum(e.dominio_efetivo for e in atual.values()) / len(atual)) if atual else None,
        "proximos": proximos,
        "max_proximos": max([p["n"] for p in proximos] + [1]),
        "nao_estudados": nao_estudados,
        "total_assuntos": len(assuntos),
        "extras": extras,
        "fixas": questoes_fixas(cfg),
        "tem_assuntos": bool(assuntos),
        "pausadas": sorted(pausadas, key=chave_ordem),
        "vez": vez,
        "amanha": amanha,
        "metas": metas,
        "flashcards": _cartoes().resumo_hoje(db, uid, dia),
        # vencidas fora da lista e ainda não feitas hoje
        "n_restantes": sum(1 for e in restantes if e.assunto_id not in feitas_hoje),
    }


def montar_metas(db, uid: int, dia: date, assuntos: dict | None = None, com_plano: bool = False) -> list[dict]:
    """
    Seções com data de prova: contagem regressiva, ritmo de assuntos novos,
    previsão no ritmo atual (ver logica.plano_da_meta) e, com `com_plano`, o
    plano semana a semana. Ordenadas pela prova mais próxima.
    """
    if assuntos is None:
        assuntos = {a["id"]: a for a in listar_folhas(db, uid)}
    # data da 1ª prática de cada assunto
    primeira = {r["assunto_id"]: para_data(r["d"]) for r in db.execute(
        "SELECT assunto_id, MIN(data) AS d FROM sessoes WHERE usuario_id = ? GROUP BY assunto_id", (uid,))}
    inicio_semana = dia - timedelta(days=6)
    inicio_4_semanas = dia - timedelta(days=27)
    materias = {r["id"]: dict(r) for r in db.execute(
        "SELECT id, nome, secao_id FROM materias WHERE usuario_id = ?", (uid,))}
    res = []
    for sec in listar_secoes(db, uid):
        meta, texto = sec["meta"], sec["data_meta"]
        if not meta:
            continue
        folhas = [a for a in assuntos.values() if materias.get(a["materia_id"], {}).get("secao_id") == sec["id"]]
        nao = sum(1 for a in folhas if a["id"] not in primeira)
        semana = sum(1 for a in folhas if a["id"] in primeira and inicio_semana <= primeira[a["id"]] <= dia)
        quatro = sum(1 for a in folhas if a["id"] in primeira and inicio_4_semanas <= primeira[a["id"]] <= dia)
        plano = L.plano_da_meta(dia, meta, nao, semana, fim=sec["fim"], iniciados_4_semanas=quatro)
        plano.update({"secao_id": sec["id"], "nome": sec["nome"], "total": len(folhas),
                      "meta_txt": meta_txt(texto), "aproximada": meta_aproximada(texto),
                      "fim_sugerido": L.fim_automatico(dia, meta)})
        if com_plano:
            # cada matéria é uma fila, na ordem em que os assuntos foram cadastrados
            # (assunto pai primeiro, depois os subassuntos dele)
            filas = {}
            for a in sorted(folhas, key=lambda a: (a["parent_id"] or a["id"], a["id"])):
                if a["id"] not in primeira:
                    filas.setdefault(a["materia_id"], []).append(a)
            ordem = sorted(filas, key=lambda mid: chave_ordem(materias[mid]["nome"]))
            plano["semanas"] = L.plano_semanal(dia, plano["por_semana"], [filas[m] for m in ordem])
        res.append(plano)
    res.sort(key=lambda p: (p["faltam"] < 0, p["meta"]))
    return res


def planejar_revisoes(db, uid: int, dia: date, n_dias: int = 7, cfg: dict | None = None) -> list[dict]:
    """
    Revisão planejada de cada dia, com as mesmas regras da tela Hoje (modo,
    limite por matéria, dia fixo, dias de cada matéria e ciclo de estudos).

    Supõe que a pessoa faz a revisão de cada dia: o que entra num dia sai da
    fila; o que não cabe no limite continua vencido e passa para o dia
    seguinte. Hoje usa exatamente a mesma lista da tela Hoje.
    """
    cfg = cfg or carregar_config(db, uid)
    assuntos = {a["id"]: a for a in listar_folhas(db, uid)}
    if not usa_dias_por_secao(cfg):
        assuntos = {aid: dict(a, dias_materia=[]) for aid, a in assuntos.items()}
    atual = estados(db, uid, dia, cfg, ids=set(assuntos))
    feitas_hoje = {r["assunto_id"] for r in db.execute(
        "SELECT DISTINCT assunto_id FROM sessoes WHERE usuario_id = ? AND data = ?", (uid, dia.isoformat()))}

    # Hoje: a mesma seleção da tela Hoje.
    sel_hoje = selecao_do_dia(db, uid, dia, cfg, assuntos)["selecao"]
    dias = [{"data": dia, "itens": [{"assunto": assuntos[e.assunto_id], "estado": e,
                                     "feito": e.assunto_id in feitas_hoje} for e in sel_hoje]}]
    # Fila para os próximos dias: estado atual (já com as práticas de hoje),
    # sem o que entra hoje e ainda não foi feito.
    fila = {aid: e for aid, e in atual.items()
            if not (aid in {x.assunto_id for x in sel_hoje} and aid not in feitas_hoje)}

    # Ciclo: simula a fila de matérias andando um passo por dia.
    ciclo = [dict(it) for it in ler_ciclo(db, uid)] if usa_ciclo(cfg) else []
    k = cfg.get("secoes_por_dia", 2)
    if ciclo:
        for it in L.secoes_da_vez(ciclo, k, dia):
            if it["ultimo_dia"] != dia:
                it["rodada"] += 1

    secao_de = {aid: a["materia_id"] for aid, a in assuntos.items()}
    for i in range(1, n_dias):
        d = dia + timedelta(days=i)
        candidatos = [e for aid, e in fila.items() if L.estuda_no_dia(d, assuntos[aid]["dias_materia"])]
        if ciclo:
            vez = L.secoes_da_vez(ciclo, k, d)
            da_vez = {it["materia_id"] for it in vez}
            candidatos = [e for e in candidatos if secao_de[e.assunto_id] in da_vez]
            for it in vez:
                it["rodada"] += 1
        tipo = L.tipo_de_revisao(cfg["modo"], cfg["dias_fixos"], d)
        if tipo == "grande":
            sel = L.selecionar_revisao_grande(candidatos, d, L.proximo_dia_fixo(d, cfg["dias_fixos"]))
        elif tipo == "diaria":
            sel = L.selecionar_revisao_diaria(candidatos, d, cfg["revisao_minima"], secao_de)
        elif tipo == "completa":
            sel = L.selecionar_revisao_completa(candidatos, d)
        else:
            sel = []
        for e in sel:
            fila.pop(e.assunto_id, None)
        dias.append({"data": d, "itens": [{"assunto": assuntos[e.assunto_id], "estado": e, "feito": False}
                                         for e in sel]})
    return dias


def montar_vencimentos(db, uid: int, dia: date, n_dias: int = 7) -> dict:
    """Página "Próximas revisões": a revisão planejada de cada dia."""
    cfg = carregar_config(db, uid)
    return {"dias": planejar_revisoes(db, uid, dia, n_dias, cfg), "cfg": cfg}


# ---------------------------------------------------------------------------
# Mapa de domínio
# ---------------------------------------------------------------------------

def montar_mapa(db, uid: int, dia: date) -> dict:
    """
    Mapa de domínio numa lista só: assuntos já estudados agrupados por matéria,
    cada um com seu status (agora / esperar / dominado). Os contadores do topo
    servem de filtro. Assuntos ainda não estudados ficam só na tela Hoje.
    """
    cfg = carregar_config(db, uid)
    folhas = listar_folhas(db, uid)
    est = estados(db, uid, dia, cfg, ids={a["id"] for a in folhas})
    ordem_status = {"agora": 0, "esperar": 1, "dominado": 2}
    secoes: dict[str, list] = {}
    contagem = {"agora": 0, "esperar": 0, "dominado": 0}
    for a in folhas:
        e = est.get(a["id"])
        if e is None:
            continue
        status = L.classificar_para_mapa(e, dia)
        contagem[status] += 1
        secoes.setdefault(a["materia"], []).append({"assunto": a, "estado": e, "status": status})
    for lista in secoes.values():
        lista.sort(key=lambda x: (ordem_status[x["status"]], -x["estado"].prioridade))
    return {"secoes": secoes, "contagem": contagem, "total": sum(contagem.values()),
            "n_nao_estudados": sum(1 for a in folhas if a["id"] not in est)}


# ---------------------------------------------------------------------------
# Exportar / importar
# ---------------------------------------------------------------------------

def exportar(db, uid: int) -> dict:
    cfg = carregar_config(db, uid)
    materias = []
    def sessoes_de(aid):
        return [dict(s) for s in db.execute(
            """SELECT data, acertos, total, observacao FROM sessoes
               WHERE usuario_id = ? AND assunto_id = ? ORDER BY data, id""", (uid, aid))]

    for m in db.execute("""SELECT m.id, m.nome, m.dias_estudo, s.nome AS secao FROM materias m
                            LEFT JOIN secoes s ON s.id = m.secao_id WHERE m.usuario_id = ? ORDER BY m.id""", (uid,)):
        assuntos = []
        for a in db.execute(
                """SELECT id, nome FROM assuntos
                   WHERE usuario_id = ? AND materia_id = ? AND parent_id IS NULL ORDER BY id""",
                (uid, m["id"])):
            item = {"nome": a["nome"], "sessoes": sessoes_de(a["id"])}
            subs = [{"nome": s["nome"], "sessoes": sessoes_de(s["id"])} for s in db.execute(
                "SELECT id, nome FROM assuntos WHERE usuario_id = ? AND parent_id = ? ORDER BY id",
                (uid, a["id"]))]
            if subs:
                item["subassuntos"] = subs
            assuntos.append(item)
        item_m = {"nome": m["nome"], "dias_estudo": ler_dias(m["dias_estudo"]), "assuntos": assuntos}
        import cartoes as C
        baralhos = C.exportar_baralhos(db, uid, m["id"])
        if baralhos:
            item_m["baralhos"] = baralhos
        if m["secao"]:
            item_m["secao"] = m["secao"]
        materias.append(item_m)
    return {
        "app": "revisa",
        "versao": 1,
        "exportado_em": datetime.now().isoformat(timespec="seconds"),
        "configuracoes": {
            "modo": cfg["modo"],
            "dias_fixos": cfg["dias_fixos"],
            "revisao_minima": cfg["revisao_minima"],
            "questoes_modo": cfg["questoes_modo"],
            "questoes_fixas": cfg["questoes_fixas"],
            "ritmo": cfg["ritmo"],
            "aprendizado": cfg["aprendizado"],
            "teto_dias": cfg["teto_dias"],
            "distribuicao": cfg["distribuicao"],
            "secoes_por_dia": cfg["secoes_por_dia"],
        },
        "secoes": [{"nome": x["nome"], **({"data_meta": x["data_meta"]} if normalizar_meta(x["data_meta"]) else {}),
                    **({"fim_conteudo": x["fim"].isoformat()} if x["fim"] else {})}
                   for x in listar_secoes(db, uid)],
        "ciclo": [it["nome"] for it in ler_ciclo(db, uid)],
        "materias": materias,
    }


class ErroImportacao(ValueError):
    pass


def _validar_sessao(s: dict) -> tuple[str, int, int, str | None]:
    try:
        data = date.fromisoformat(str(s["data"])).isoformat()
        acertos, total = int(s["acertos"]), int(s["total"])
    except (KeyError, TypeError, ValueError):
        raise ErroImportacao("Prática com data, acertos ou total inválidos.")
    if total <= 0 or acertos < 0 or acertos > total:
        raise ErroImportacao(f"Prática de {data}: acertos deve estar entre 0 e o total, e o total deve ser maior que 0.")
    obs = s.get("observacao")
    return data, acertos, total, (str(obs)[:1000] if obs else None)


def importar(db, uid: int, dados: dict, substituir: bool = True) -> dict:
    """
    Importa um arquivo gerado por exportar(). Valida tudo antes de gravar;
    se algo estiver errado, nada é alterado. Com `substituir`, apaga antes
    as matérias/assuntos/sessões atuais do usuário.
    """
    if not isinstance(dados, dict) or not isinstance(dados.get("materias"), list):
        raise ErroImportacao("Arquivo não reconhecido: esperado um JSON exportado pelo Revisa.")

    plano = []
    for m in dados["materias"]:
        nome_m = str(m.get("nome", "")).strip()[:120]
        if not nome_m:
            raise ErroImportacao("Matéria sem nome no arquivo.")
        assuntos = []
        for a in m.get("assuntos", []) or []:
            nome_a = str(a.get("nome", "")).strip()[:160]
            if not nome_a:
                raise ErroImportacao(f"Assunto sem nome em {nome_m}.")
            subs = []
            for s in a.get("subassuntos", []) or []:
                nome_s = str(s.get("nome", "")).strip()[:160]
                if not nome_s:
                    raise ErroImportacao(f"Subassunto sem nome em {nome_a}.")
                subs.append((nome_s, [_validar_sessao(x) for x in s.get("sessoes", []) or []]))
            assuntos.append((nome_a, [_validar_sessao(s) for s in a.get("sessoes", []) or []], subs))
        dias_m = ",".join(map(str, ler_dias(",".join(map(str, m.get("dias_estudo") or [])))))
        secao_m = str(m.get("secao") or "").strip()[:120] or None
        import cartoes as C
        plano.append((nome_m, assuntos, dias_m, secao_m, C.validar_baralhos(m.get("baralhos"))))

    secoes_novas = []
    for x in dados.get("secoes") or []:
        nome_x = str((x or {}).get("nome", "")).strip()[:120]
        if nome_x:
            fim_x = normalizar_meta(x.get("fim_conteudo"))
            secoes_novas.append((nome_x, normalizar_meta(x.get("data_meta")),
                                 fim_x if fim_x and len(fim_x) == 10 else None))
    # seção citada por uma matéria e ausente da lista: cria sem prova
    for *_, secao_m, _b in plano:
        if secao_m and secao_m not in {n for n, *_ in secoes_novas}:
            secoes_novas.append((secao_m, None, None))

    cfg_nova = dados.get("configuracoes") or {}

    try:
        if substituir:
            db.execute("DELETE FROM estudo_do_dia WHERE usuario_id = ?", (uid,))
            db.execute("DELETE FROM sessoes WHERE usuario_id = ?", (uid,))
            db.execute("DELETE FROM assuntos WHERE usuario_id = ?", (uid,))
            db.execute("DELETE FROM materias WHERE usuario_id = ?", (uid,))
            db.execute("DELETE FROM secoes WHERE usuario_id = ?", (uid,))
            db.execute("DELETE FROM imagens WHERE usuario_id = ?", (uid,))
        ids_secao = {}
        for nome_x, meta_x, fim_x in secoes_novas:
            ids_secao[nome_x] = db.execute(
                "INSERT INTO secoes (usuario_id, nome, data_meta, fim_conteudo) VALUES (?, ?, ?, ?)",
                (uid, nome_x, meta_x, fim_x)).lastrowid
        n_m = n_a = n_s = 0
        import cartoes as C
        n_c = 0
        for nome_m, assuntos, dias_m, secao_m, baralhos in plano:
            mid = db.execute("INSERT INTO materias (usuario_id, nome, dias_estudo, secao_id) VALUES (?, ?, ?, ?)",
                             (uid, nome_m, dias_m, ids_secao.get(secao_m))).lastrowid
            n_m += 1
            def gravar(nome, sessoes, pai=None):
                nonlocal n_a, n_s
                aid = db.execute(
                    "INSERT INTO assuntos (usuario_id, materia_id, nome, parent_id) VALUES (?, ?, ?, ?)",
                    (uid, mid, nome, pai)).lastrowid
                n_a += 1
                for data, acertos, total, obs in sessoes:
                    db.execute(
                        """INSERT INTO sessoes (usuario_id, assunto_id, data, acertos, total, observacao)
                           VALUES (?, ?, ?, ?, ?, ?)""", (uid, aid, data, acertos, total, obs))
                    n_s += 1
                return aid

            for nome_a, sessoes, subs in assuntos:
                aid = gravar(nome_a, sessoes)
                for nome_s, sessoes_s in subs:
                    gravar(nome_s, sessoes_s, aid)
            n_c += C.gravar_baralhos(db, uid, mid, baralhos)
        if cfg_nova:
            salvar_config(db, uid, cfg_nova, commit=False)
        # ciclo de estudos (pelos nomes das matérias importadas)
        if isinstance(dados.get("ciclo"), list):
            db.execute("DELETE FROM ciclo_itens WHERE usuario_id = ?", (uid,))
            ids = {r["nome"]: r["id"] for r in db.execute("SELECT id, nome FROM materias WHERE usuario_id = ?", (uid,))}
            for pos, nome in enumerate(dados["ciclo"]):
                if str(nome) in ids:
                    db.execute("INSERT INTO ciclo_itens (usuario_id, materia_id, posicao) VALUES (?, ?, ?)",
                               (uid, ids[str(nome)], pos))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"materias": n_m, "assuntos": n_a, "sessoes": n_s, "cartoes": n_c}


def validar_config(form: dict) -> dict:
    """Normaliza e valida configurações vindas de formulário ou JSON."""
    modo = form.get("modo")
    if modo not in L.MODOS:
        raise ValueError("Escolha um modo de revisão válido.")
    dias = form.get("dias_fixos") or []
    if isinstance(dias, str):
        dias = [d for d in dias.split(",") if d.strip()]
    dias = sorted({int(d) for d in dias if 0 <= int(d) <= 6})
    if modo in L.MODOS_COM_DIA_FIXO and not dias:
        raise ValueError("Escolha pelo menos um dia para a revisão fixa.")
    minima = int(form.get("revisao_minima") or 2)
    if not 1 <= minima <= 50:
        raise ValueError("A revisão mínima diária deve ficar entre 1 e 50 assuntos.")
    qmodo = form.get("questoes_modo") or "auto"
    if qmodo not in ("auto", "fixo"):
        raise ValueError("Modo de questões inválido.")
    qfixas = int(form.get("questoes_fixas") or 10)
    if not 1 <= qfixas <= 500:
        raise ValueError("O número fixo de questões deve ficar entre 1 e 500.")
    ritmo = form.get("ritmo") or "leve"
    if ritmo not in L.RITMOS:
        raise ValueError("Escolha um ritmo de estudo válido.")
    aprendizado = form.get("aprendizado") or "padrao"
    if aprendizado not in L.FASES_APRENDIZADO:
        raise ValueError("Escolha uma opção válida para assuntos novos.")
    teto = form.get("teto_dias")
    teto = int(teto) if teto not in (None, "") else L.sugerir_teto(ritmo, aprendizado)
    if not L.TETO_MIN <= teto <= L.TETO_MAX:
        raise ValueError(f"O máximo de dias sem revisão deve ficar entre {L.TETO_MIN} e {L.TETO_MAX}.")
    distribuicao = form.get("distribuicao") or "todas"
    if distribuicao not in ("todas", "dias", "ciclo"):
        raise ValueError("Escolha como você distribui as matérias na semana.")
    por_dia = int(form.get("secoes_por_dia") or 2)
    if not 1 <= por_dia <= 10:
        raise ValueError("O ciclo deve ter de 1 a 10 matérias por dia.")
    return {"modo": modo, "dias_fixos": dias, "revisao_minima": minima,
            "questoes_modo": qmodo, "questoes_fixas": qfixas, "ritmo": ritmo,
            "aprendizado": aprendizado, "teto_dias": teto, "distribuicao": distribuicao,
            "secoes_por_dia": por_dia}


def salvar_config(db, uid: int, dados: dict, commit: bool = True):
    c = validar_config(dados)
    carregar_config(db, uid)  # garante que a linha existe
    db.execute(
        """UPDATE configuracoes SET modo = ?, dias_fixos = ?, revisao_minima = ?,
           questoes_modo = ?, questoes_fixas = ?, ritmo = ?, aprendizado = ?, teto_dias = ?,
           distribuicao = ?, secoes_por_dia = ? WHERE usuario_id = ?""",
        (c["modo"], ",".join(map(str, c["dias_fixos"])), c["revisao_minima"],
         c["questoes_modo"], c["questoes_fixas"], c["ritmo"], c["aprendizado"], c["teto_dias"],
         c["distribuicao"], c["secoes_por_dia"], uid))
    if commit:
        db.commit()


def _cartoes():
    """Módulo dos flashcards (importado aqui dentro: ele também importa este módulo)."""
    import cartoes
    return cartoes
