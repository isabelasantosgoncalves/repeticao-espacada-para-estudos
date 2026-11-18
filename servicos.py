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


def estados(db, uid: int, dia: date, cfg: dict, antes_de: date | None = None,
            ids: set[int] | None = None) -> dict[int, L.EstadoAssunto]:
    """Estado de cada assunto que já tem sessões (só os de `ids`, se informado)."""
    fixas = questoes_fixas(cfg)
    res = {}
    for aid, sess in sessoes_por_assunto(db, uid, antes_de).items():
        if ids is not None and aid not in ids:
            continue
        e = L.analisar_assunto(aid, sess, dia, fixas, fator=fator(cfg), tetos=tetos(cfg),
                               teto=cfg.get("teto_dias"))
        if e:
            res[aid] = e
    return res


# ---------------------------------------------------------------------------
# Tela "Hoje"
# ---------------------------------------------------------------------------

def montar_hoje(db, uid: int, dia: date) -> dict:
    """
    Monta o painel da tela Hoje.

    A seleção da revisão usa só as sessões ANTERIORES a hoje, para que a lista
    não mude enquanto o usuário registra resultados ao longo do dia. Os
    assuntos já feitos hoje aparecem marcados como concluídos.
    """
    cfg = carregar_config(db, uid)
    assuntos = {a["id"]: a for a in listar_folhas(db, uid)}   # grupos não entram na revisão
    est = estados(db, uid, dia, cfg, antes_de=dia, ids=set(assuntos))

    tipo = L.tipo_de_revisao(cfg["modo"], cfg["dias_fixos"], dia)
    proximo_fixo = L.proximo_dia_fixo(dia, cfg["dias_fixos"])

    ontem = (dia - timedelta(days=1)).isoformat()
    ids_ontem = [r["assunto_id"] for r in db.execute(
        "SELECT assunto_id FROM estudo_do_dia WHERE usuario_id = ? AND data = ? ORDER BY id",
        (uid, ontem))]
    # Também conta como "estudado ontem" o assunto cuja primeira sessão foi ontem.
    for r in db.execute(
        """SELECT assunto_id FROM sessoes WHERE usuario_id = ?
           GROUP BY assunto_id HAVING MIN(data) = ?""", (uid, ontem)):
        if r["assunto_id"] not in ids_ontem:
            ids_ontem.append(r["assunto_id"])

    if tipo == "grande":
        selecao = L.selecionar_revisao_grande(list(est.values()), dia, proximo_fixo)
    elif tipo == "diaria":
        selecao = L.selecionar_revisao_diaria(list(est.values()), ids_ontem, cfg["revisao_minima"])
    elif tipo == "completa":
        selecao = L.selecionar_revisao_completa(list(est.values()), dia)
    else:
        selecao = []

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
                            "feito": feitas_hoje.get(e.assunto_id)})

    # ---- Painel: números do dia, próximos dias e progresso no conteúdo ----
    # Estado ATUAL (inclui as sessões de hoje) para atrasos, domínio e agenda.
    atual = estados(db, uid, dia, cfg, ids=set(assuntos))

    proximos = []
    for i in range(1, 8):
        d = dia + timedelta(days=i)
        proximos.append({"data": d, "n": sum(1 for e in atual.values() if e.proxima_revisao == d)})

    com_sessao = {r["assunto_id"] for r in db.execute(
        "SELECT DISTINCT assunto_id FROM sessoes WHERE usuario_id = ?", (uid,))}
    nao_estudados = [a for a in assuntos.values() if a["id"] not in com_sessao]

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
    }


# ---------------------------------------------------------------------------
# Mapa de domínio
# ---------------------------------------------------------------------------

def montar_mapa(db, uid: int, dia: date) -> dict:
    cfg = carregar_config(db, uid)
    folhas = listar_folhas(db, uid)
    est = estados(db, uid, dia, cfg, ids={a["id"] for a in folhas})
    grupos = {"agora": defaultdict(list), "esperar": defaultdict(list), "dominado": defaultdict(list)}
    nao_estudados = defaultdict(list)
    for a in folhas:
        e = est.get(a["id"])
        if e is None:
            nao_estudados[a["materia"]].append(a)
            continue
        grupos[L.classificar_para_mapa(e, dia)][a["materia"]].append({"assunto": a, "estado": e})
    for g in grupos.values():
        for lista in g.values():
            lista.sort(key=lambda x: (-x["estado"].prioridade))
    contagem = {k: sum(len(v) for v in g.values()) for k, g in grupos.items()}
    return {"grupos": grupos, "nao_estudados": nao_estudados, "contagem": contagem}


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

    for m in db.execute("SELECT id, nome FROM materias WHERE usuario_id = ? ORDER BY id", (uid,)):
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
        materias.append({"nome": m["nome"], "assuntos": assuntos})
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
        },
        "materias": materias,
    }


class ErroImportacao(ValueError):
    pass


def _validar_sessao(s: dict) -> tuple[str, int, int, str | None]:
    try:
        data = date.fromisoformat(str(s["data"])).isoformat()
        acertos, total = int(s["acertos"]), int(s["total"])
    except (KeyError, TypeError, ValueError):
        raise ErroImportacao("Sessão com data, acertos ou total inválidos.")
    if total <= 0 or acertos < 0 or acertos > total:
        raise ErroImportacao(f"Sessão de {data}: acertos deve estar entre 0 e o total, e o total deve ser maior que 0.")
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
        plano.append((nome_m, assuntos))

    cfg_nova = dados.get("configuracoes") or {}

    try:
        if substituir:
            db.execute("DELETE FROM estudo_do_dia WHERE usuario_id = ?", (uid,))
            db.execute("DELETE FROM sessoes WHERE usuario_id = ?", (uid,))
            db.execute("DELETE FROM assuntos WHERE usuario_id = ?", (uid,))
            db.execute("DELETE FROM materias WHERE usuario_id = ?", (uid,))
        n_m = n_a = n_s = 0
        for nome_m, assuntos in plano:
            mid = db.execute("INSERT INTO materias (usuario_id, nome) VALUES (?, ?)",
                             (uid, nome_m)).lastrowid
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
        if cfg_nova:
            salvar_config(db, uid, cfg_nova, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"materias": n_m, "assuntos": n_a, "sessoes": n_s}


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
    return {"modo": modo, "dias_fixos": dias, "revisao_minima": minima,
            "questoes_modo": qmodo, "questoes_fixas": qfixas, "ritmo": ritmo,
            "aprendizado": aprendizado, "teto_dias": teto}


def salvar_config(db, uid: int, dados: dict, commit: bool = True):
    c = validar_config(dados)
    carregar_config(db, uid)  # garante que a linha existe
    db.execute(
        """UPDATE configuracoes SET modo = ?, dias_fixos = ?, revisao_minima = ?,
           questoes_modo = ?, questoes_fixas = ?, ritmo = ?, aprendizado = ?, teto_dias = ?
           WHERE usuario_id = ?""",
        (c["modo"], ",".join(map(str, c["dias_fixos"])), c["revisao_minima"],
         c["questoes_modo"], c["questoes_fixas"], c["ritmo"], c["aprendizado"], c["teto_dias"], uid))
    if commit:
        db.commit()
