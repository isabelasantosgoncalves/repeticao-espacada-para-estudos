"""
Flashcards: baralhos (ligados a uma matéria) e cartões, no estilo do Anki.

- A agenda de cada cartão é calculada a partir das respostas (Errei / Acertei,
  mas demorei / Acertei), com a mesma lógica das questões (ver
  logica.agenda_cartao). Nada de agenda fica gravado: mudar o ritmo, a fase de
  aprendizado, o máximo de dias ou a prova vale na hora para os cartões.
- Errou: o cartão volta no fim da fila da mesma sessão até você acertar
  (passos de reaprendizado). Para a agenda vale só a primeira resposta do dia.
- Cartão invertido: além de frente -> verso, pergunta verso -> frente. Cada
  lado tem a sua agenda; no dia em que um lado é estudado, o outro espera
  (como o "irmão enterrado" do Anki).
- Suspender tira o cartão do estudo; adiar o tira só de hoje.
Todas as consultas filtram por usuario_id.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from datetime import date

import logica as L
import servicos as S

TAMANHO_MAX_IMAGEM = 2 * 1024 * 1024
TIPOS_IMAGEM = {"image/png", "image/jpeg", "image/gif", "image/webp"}


# ---------------------------------------------------------------------------
# Agenda e fila de estudo
# ---------------------------------------------------------------------------

def _respostas(db, uid: int) -> dict[tuple[int, int], list[tuple[date, str, int]]]:
    """{(cartão, lado): [(data, nota, id), ...]} em ordem."""
    res: dict[tuple[int, int], list] = defaultdict(list)
    for r in db.execute(
            "SELECT id, cartao_id, lado, data, nota FROM respostas_cartao WHERE usuario_id = ? ORDER BY data, id",
            (uid,)):
        if r["nota"] in L.PONTOS_CARTAO:
            res[(r["cartao_id"], r["lado"])].append((date.fromisoformat(r["data"]), r["nota"], r["id"]))
    return res


def cartoes_com_agenda(db, uid: int, dia: date, baralho_id: int | None = None,
                       materia_id: int | None = None) -> list[dict]:
    """
    Um item por LADO de cartão (o invertido tem dois), com a agenda:
    `proxima` (None = novo), `intervalo`, `inicio`, `ultima`, `aprendendo`
    (errou hoje e ainda não acertou) e `estudado_hoje`.
    """
    cfg = S.carregar_config(db, uid)
    metas = S.metas_por_materia(db, uid)
    respostas = _respostas(db, uid)
    sql = """SELECT c.*, b.nome AS baralho, b.materia_id, m.nome AS materia
             FROM cartoes c JOIN baralhos b ON b.id = c.baralho_id JOIN materias m ON m.id = b.materia_id
             WHERE c.usuario_id = ?"""
    params: list = [uid]
    if baralho_id:
        sql += " AND c.baralho_id = ?"
        params.append(baralho_id)
    if materia_id:
        sql += " AND b.materia_id = ?"
        params.append(materia_id)
    res = []
    for r in db.execute(sql + " ORDER BY c.id", params):
        c = dict(r)
        for lado in ((0, 1) if c["invertido"] else (0,)):
            resp = respostas.get((c["id"], lado), [])
            agenda = L.agenda_cartao([(d, n) for d, n, _ in resp], S.fator(cfg), S.tetos(cfg),
                                     cfg.get("teto_dias"), metas.get(c["materia_id"]))
            item = dict(c, lado=lado, chave=f"{c['id']}-{lado}")
            item["pergunta"], item["resposta"] = (c["frente"], c["verso"]) if lado == 0 else (c["verso"], c["frente"])
            item["img_pergunta"], item["img_resposta"] = ((c["imagem_frente"], c["imagem_verso"]) if lado == 0
                                                          else (c["imagem_verso"], c["imagem_frente"]))
            item["proxima"], item["intervalo"] = agenda if agenda else (None, 0)
            item["inicio"] = resp[0][0] if resp else None
            item["ultima"] = resp[-1][0] if resp else None
            item["estudado_hoje"] = bool(resp) and resp[-1][0] == dia
            item["aprendendo"] = item["estudado_hoje"] and resp[-1][1] == "errei"
            item["ordem_resposta"] = resp[-1][2] if resp else 0
            res.append(item)
    return res


def _classificar(itens: list[dict], dia: date, novos_ja: int) -> dict[str, list[dict]]:
    """Separa os lados em revisar, novos (com o limite diário) e aprendendo."""
    hoje_ativos = [c for c in itens if not c["suspenso"] and c["adiado"] != dia.isoformat()]
    # lado irmão já estudado hoje: o outro lado espera até amanhã
    estudados = {c["id"] for c in hoje_ativos if c["estudado_hoje"]}
    aprendendo = sorted([c for c in hoje_ativos if c["aprendendo"]], key=lambda c: c["ordem_resposta"])
    livres = [c for c in hoje_ativos if not c["estudado_hoje"] and c["id"] not in estudados]
    revisar = sorted([c for c in livres if c["proxima"] and c["proxima"] <= dia], key=lambda c: (c["proxima"], c["id"]))
    novos = [c for c in livres if not c["proxima"]][:max(0, L.NOVOS_POR_DIA - novos_ja)]
    return {"revisar": revisar, "novos": novos, "aprendendo": aprendendo}


def fila(db, uid: int, dia: date, baralho_id: int | None = None, materia_id: int | None = None) -> dict:
    """
    Estudo do dia, como no Anki: primeiro os que venceram, depois os novos (até
    o limite diário de novos, contando todos os baralhos) e, no fim, os que você
    errou hoje e ainda não acertou. Devolve a fila e os três contadores.
    """
    todos = cartoes_com_agenda(db, uid, dia)
    novos_ja = sum(1 for c in todos if c["inicio"] == dia)
    escopo = [c for c in todos if (not baralho_id or c["baralho_id"] == baralho_id)
              and (not materia_id or c["materia_id"] == materia_id)]
    grupos = _classificar(escopo, dia, novos_ja)
    return {"cartoes": grupos["revisar"] + grupos["novos"] + grupos["aprendendo"],
            "n_revisar": len(grupos["revisar"]), "n_novos": len(grupos["novos"]),
            "n_aprendendo": len(grupos["aprendendo"])}


def listar_baralhos(db, uid: int, dia: date) -> list[dict]:
    """Matérias com seus baralhos e, em cada um: total, novos, aprendendo e a revisar hoje."""
    todos = cartoes_com_agenda(db, uid, dia)
    novos_ja = sum(1 for c in todos if c["inicio"] == dia)
    por_baralho: dict[int, list] = defaultdict(list)
    for c in todos:
        por_baralho[c["baralho_id"]].append(c)
    materias = sorted((dict(m) for m in db.execute(
        """SELECT m.id, m.nome, s.nome AS secao, COALESCE(s.ordem, s.id) AS pos_secao,
                  COALESCE(m.ordem, m.id) AS pos FROM materias m LEFT JOIN secoes s ON s.id = m.secao_id
           WHERE m.usuario_id = ?""", (uid,))),
        key=lambda m: (m["pos_secao"] is None, m["pos_secao"] or 0, m["pos"], m["id"]))
    por_materia = {m["id"]: [] for m in materias}
    for b in db.execute("SELECT id, materia_id, nome FROM baralhos WHERE usuario_id = ?", (uid,)):
        lados = por_baralho.get(b["id"], [])
        g = _classificar(lados, dia, novos_ja)
        por_materia[b["materia_id"]].append(dict(
            b, total=len({c["id"] for c in lados}), novos=len(g["novos"]),
            aprendendo=len(g["aprendendo"]), revisar=len(g["revisar"])))
    for m in materias:
        m["baralhos"] = sorted(por_materia[m["id"]], key=lambda b: S.chave_ordem(b["nome"]))
    return materias


def resumo_hoje(db, uid: int, dia: date) -> dict | None:
    """Painel: quantos cartões estudar hoje, por matéria. None se não há baralhos."""
    if not db.execute("SELECT 1 FROM baralhos WHERE usuario_id = ? LIMIT 1", (uid,)).fetchone():
        return None
    f = fila(db, uid, dia)
    por_materia: dict[int, dict] = {}
    for c in f["cartoes"]:
        m = por_materia.setdefault(c["materia_id"], {"id": c["materia_id"], "nome": c["materia"], "n": 0})
        m["n"] += 1
    return {"total": len(f["cartoes"]), "novos": f["n_novos"], "aprendendo": f["n_aprendendo"],
            "revisar": f["n_revisar"],
            "materias": sorted(por_materia.values(), key=lambda m: S.chave_ordem(m["nome"]))}


# ---------------------------------------------------------------------------
# Ações do estudo
# ---------------------------------------------------------------------------

def responder(db, uid: int, cartao_id: int, lado: int, nota: str, dia: date):
    if nota not in L.NOTAS_CARTAO:
        raise ValueError("Resposta inválida.")
    db.execute("INSERT INTO respostas_cartao (usuario_id, cartao_id, lado, data, nota) VALUES (?, ?, ?, ?, ?)",
               (uid, cartao_id, 1 if lado else 0, dia.isoformat(), nota))
    db.commit()


def desfazer(db, uid: int, dia: date) -> dict | None:
    """Apaga a última resposta de hoje e devolve qual cartão ela era."""
    r = db.execute("SELECT id, cartao_id, lado FROM respostas_cartao WHERE usuario_id = ? AND data = ? "
                   "ORDER BY id DESC LIMIT 1", (uid, dia.isoformat())).fetchone()
    if not r:
        return None
    db.execute("DELETE FROM respostas_cartao WHERE id = ? AND usuario_id = ?", (r["id"], uid))
    db.commit()
    return dict(r)


# ---------------------------------------------------------------------------
# Imagens
# ---------------------------------------------------------------------------

def tipo_da_imagem(dados: bytes) -> str | None:
    """Confere pelo conteúdo (não pelo nome do arquivo) se é PNG, JPEG, GIF ou WebP."""
    if dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if dados.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if dados[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    return None


def guardar_imagem(db, uid: int, dados: bytes) -> int:
    if not dados:
        raise ValueError("Imagem vazia.")
    if len(dados) > TAMANHO_MAX_IMAGEM:
        raise ValueError("A imagem passa de 2 MB. Use uma menor.")
    tipo = tipo_da_imagem(dados)
    if not tipo:
        raise ValueError("Use uma imagem PNG, JPG, GIF ou WebP.")
    return db.execute("INSERT INTO imagens (usuario_id, tipo, dados) VALUES (?, ?, ?)",
                      (uid, tipo, dados)).lastrowid


def apagar_imagens_soltas(db, uid: int):
    """Imagens que nenhum cartão usa mais."""
    db.execute("""DELETE FROM imagens WHERE usuario_id = ? AND id NOT IN (
                    SELECT imagem_frente FROM cartoes WHERE usuario_id = ? AND imagem_frente IS NOT NULL
                    UNION SELECT imagem_verso FROM cartoes WHERE usuario_id = ? AND imagem_verso IS NOT NULL)""",
               (uid, uid, uid))


def imagem_em_data_uri(db, uid: int, iid: int | None) -> str | None:
    if not iid:
        return None
    r = db.execute("SELECT tipo, dados FROM imagens WHERE id = ? AND usuario_id = ?", (iid, uid)).fetchone()
    if not r:
        return None
    return f"data:{r['tipo']};base64,{base64.b64encode(r['dados']).decode()}"


def ler_data_uri(texto) -> bytes | None:
    if not texto:
        return None
    try:
        cab, corpo = str(texto).split(",", 1)
        if not cab.startswith("data:image/") or ";base64" not in cab:
            raise ValueError
        return base64.b64decode(corpo, validate=True)
    except (ValueError, TypeError):
        raise S.ErroImportacao("Imagem inválida num cartão.")


# ---------------------------------------------------------------------------
# Vários cartões de uma vez
# ---------------------------------------------------------------------------

def ler_em_lote(texto: str) -> list[tuple[str, str]]:
    """
    Uma linha por cartão, frente e verso separados por TAB (duas colunas
    coladas de uma planilha) ou por " | ". Linhas sem separador são recusadas.
    """
    cartoes = []
    for n, linha in enumerate((texto or "").splitlines(), 1):
        if not linha.strip():
            continue
        if "\t" in linha:
            frente, verso = linha.split("\t", 1)
        elif " | " in linha:
            frente, verso = linha.split(" | ", 1)
        else:
            raise ValueError(f"Linha {n}: separe a frente e o verso com TAB ou com “ | ”.")
        frente, verso = frente.strip(), verso.strip()
        if not frente or not verso:
            raise ValueError(f"Linha {n}: falta a frente ou o verso.")
        cartoes.append((frente[:2000], verso[:2000]))
    if not cartoes:
        raise ValueError("Cole pelo menos um cartão.")
    return cartoes


# ---------------------------------------------------------------------------
# Exportar / importar (os baralhos vão dentro de cada matéria)
# ---------------------------------------------------------------------------

def exportar_baralhos(db, uid: int, materia_id: int) -> list[dict]:
    res = []
    for b in db.execute("SELECT id, nome FROM baralhos WHERE usuario_id = ? AND materia_id = ? ORDER BY id",
                        (uid, materia_id)):
        cartoes = []
        for c in db.execute("SELECT * FROM cartoes WHERE usuario_id = ? AND baralho_id = ? ORDER BY id",
                            (uid, b["id"])):
            item = {"frente": c["frente"], "verso": c["verso"],
                    "respostas": [[r["data"], r["nota"], r["lado"]] for r in db.execute(
                        "SELECT data, nota, lado FROM respostas_cartao WHERE usuario_id = ? AND cartao_id = ? "
                        "ORDER BY data, id", (uid, c["id"]))]}
            if c["invertido"]:
                item["invertido"] = True
            if c["suspenso"]:
                item["suspenso"] = True
            for campo in ("imagem_frente", "imagem_verso"):
                uri = imagem_em_data_uri(db, uid, c[campo])
                if uri:
                    item[campo] = uri
            cartoes.append(item)
        res.append({"nome": b["nome"], "cartoes": cartoes})
    return res


def validar_baralhos(lista) -> list[tuple[str, list[dict]]]:
    """Confere os baralhos de uma matéria vindos de um arquivo importado."""
    res = []
    for b in lista or []:
        nome = str(b.get("nome", "")).strip()[:120]
        if not nome:
            raise S.ErroImportacao("Baralho sem nome no arquivo.")
        cartoes = []
        for c in b.get("cartoes", []) or []:
            frente, verso = str(c.get("frente", "")).strip(), str(c.get("verso", "")).strip()
            imgs = {campo: ler_data_uri(c.get(campo)) for campo in ("imagem_frente", "imagem_verso")}
            if not (frente or imgs["imagem_frente"]) or not (verso or imgs["imagem_verso"]):
                raise S.ErroImportacao(f"Cartão sem frente ou verso em {nome}.")
            respostas = []
            for r in c.get("respostas", []) or []:
                try:
                    data, nota = date.fromisoformat(str(r[0])).isoformat(), str(r[1])
                    lado = 1 if len(r) > 2 and int(r[2]) else 0
                except (TypeError, ValueError, IndexError):
                    raise S.ErroImportacao(f"Resposta inválida num cartão de {nome}.")
                if nota not in L.NOTAS_CARTAO:
                    raise S.ErroImportacao(f"Resposta inválida num cartão de {nome}.")
                respostas.append((data, nota, lado))
            cartoes.append({"frente": frente[:2000], "verso": verso[:2000], "respostas": respostas,
                            "invertido": bool(c.get("invertido")), "suspenso": bool(c.get("suspenso")), **imgs})
        res.append((nome, cartoes))
    return res


def gravar_baralhos(db, uid: int, materia_id: int, baralhos: list[tuple[str, list[dict]]]) -> int:
    n = 0
    for nome, cartoes in baralhos:
        bid = db.execute("INSERT INTO baralhos (usuario_id, materia_id, nome) VALUES (?, ?, ?)",
                         (uid, materia_id, nome)).lastrowid
        for c in cartoes:
            imgs = {campo: (guardar_imagem(db, uid, c[campo]) if c.get(campo) else None)
                    for campo in ("imagem_frente", "imagem_verso")}
            cid = db.execute(
                """INSERT INTO cartoes (usuario_id, baralho_id, frente, verso, invertido, suspenso,
                                        imagem_frente, imagem_verso) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (uid, bid, c["frente"], c["verso"], int(c["invertido"]), int(c["suspenso"]),
                 imgs["imagem_frente"], imgs["imagem_verso"])).lastrowid
            for data, nota, lado in c["respostas"]:
                db.execute("INSERT INTO respostas_cartao (usuario_id, cartao_id, lado, data, nota) VALUES (?, ?, ?, ?, ?)",
                           (uid, cid, lado, data, nota))
            n += 1
    return n
