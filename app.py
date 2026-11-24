"""
Revisa: app de repetição espaçada para estudos.

Rotas, autenticação e formulários. A lógica do algoritmo fica em logica.py
e o acesso aos dados em servicos.py.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import date
from urllib.parse import urlparse

import click
from dotenv import load_dotenv
from flask import (Flask, Response, abort, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from werkzeug.security import check_password_hash, generate_password_hash

import db as banco
import logica as L
import cartoes as C
import servicos as S

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DEMO_EMAIL = "demo@demo.com"


# ---------------------------------------------------------------------------
# Usuário (Flask-Login)
# ---------------------------------------------------------------------------

class Usuario(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.nome = row["nome"]
        self.email = row["email"]
        self.onboarding_ok = bool(row["onboarding_ok"])

    @property
    def primeiro_nome(self):
        return self.nome.split()[0] if self.nome else ""

    @property
    def e_demo(self):
        return self.email == DEMO_EMAIL


login_manager = LoginManager()
login_manager.login_view = "entrar"
login_manager.login_message = "Entre na sua conta para continuar."
login_manager.login_message_category = "info"


@login_manager.user_loader
def carregar_usuario(uid):
    row = banco.get_db().execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
    return Usuario(row) if row else None


# ---------------------------------------------------------------------------
# Fábrica do app
# ---------------------------------------------------------------------------

def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or "dev-troque-esta-chave",
        DATABASE=os.environ.get("DATABASE_PATH") or os.path.join(BASE_DIR, "estudos.db"),
        MAX_CONTENT_LENGTH=30 * 1024 * 1024,  # limite para importar o JSON (com as imagens dos flashcards)
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        CSRF_ATIVO=True,
    )
    if config:
        app.config.update(config)

    banco.init_app(app)
    login_manager.init_app(app)
    registrar_filtros(app)
    registrar_rotas(app)
    registrar_comandos(app)
    return app


# ---------------------------------------------------------------------------
# Utilidades: CSRF, filtros, validação
# ---------------------------------------------------------------------------

def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def destino_seguro(url: str | None, padrao: str) -> str:
    """Evita redirecionamento para outro site via ?next=."""
    if url and url.startswith("/") and not url.startswith("//") and not urlparse(url).netloc:
        return url
    return padrao


def br(valor) -> str:
    """Data no formato dd/mm/aaaa."""
    if not valor:
        return ""
    if isinstance(valor, str):
        valor = date.fromisoformat(valor[:10])
    return valor.strftime("%d/%m/%Y")


def relativo(d: date) -> str:
    dias = (d - S.hoje()).days
    if dias == 0:
        return "hoje"
    if dias == 1:
        return "amanhã"
    if dias == -1:
        return "ontem"
    if dias > 1:
        return f"em {dias} dias"
    return f"há {-dias} dias"


def pct(valor: float) -> str:
    return f"{round(valor * 100)}%"


def cor_dominio(valor: float) -> str:
    """vermelho < 50%, amarelo 50–84%, verde >= 85%"""
    if valor + L.EPS >= 0.85:
        return "verde"
    if valor + L.EPS >= 0.50:
        return "amarelo"
    return "vermelho"


def registrar_filtros(app):
    def estatico(arquivo: str) -> str:
        """URL de um arquivo estático com ?v=<data de modificação>: quando o
        arquivo muda, o endereço muda e o navegador não usa a versão em cache."""
        caminho = os.path.join(app.static_folder, arquivo)
        try:
            versao = int(os.path.getmtime(caminho))
        except OSError:
            versao = 0
        return url_for("static", filename=arquivo, v=versao)

    app.jinja_env.globals["estatico"] = estatico
    app.jinja_env.filters.update(br=br, relativo=relativo, pct=pct, cor=cor_dominio, meta_txt=S.meta_txt)
    # Sugestão de teto para cada combinação ritmo × fase (usada no onboarding/Configurações)
    sugestoes = {r: {f: L.sugerir_teto(r, f) for f in L.FASES_APRENDIZADO} for r in L.RITMOS}
    app.jinja_env.globals.update(csrf_token=csrf_token, NOMES_DIAS=S.NOMES_DIAS,
                                 SUGESTOES_TETO=sugestoes, TETO_MIN=L.TETO_MIN, TETO_MAX=L.TETO_MAX,
                                 FATORES_RITMO=L.RITMOS)


def ler_inteiro(valor, nome: str) -> int:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        raise ValueError(f"Informe um número inteiro em {nome}.")


def validar_resultado(acertos_txt, total_txt) -> tuple[int, int]:
    """Regras: total > 0 e 0 <= acertos <= total."""
    acertos = ler_inteiro(acertos_txt, "acertos")
    total = ler_inteiro(total_txt, "total")
    if total <= 0:
        raise ValueError("O total de questões deve ser maior que zero.")
    if acertos < 0:
        raise ValueError("Os acertos não podem ser negativos.")
    if acertos > total:
        raise ValueError("Os acertos não podem ser maiores que o total.")
    return acertos, total


def validar_data(texto) -> date:
    try:
        d = date.fromisoformat(str(texto))
    except ValueError:
        raise ValueError("Data inválida.")
    if d > S.hoje():
        raise ValueError("A data da prática não pode estar no futuro.")
    return d


# ---------------------------------------------------------------------------
# Acesso aos dados do usuário logado (sempre filtrado por usuario_id)
# ---------------------------------------------------------------------------

def do_usuario(tabela: str, id_: int):
    """Busca um registro do usuário logado ou responde 404."""
    assert tabela in ("secoes", "materias", "assuntos", "sessoes", "ciclo_itens", "baralhos", "cartoes")
    row = banco.get_db().execute(
        f"SELECT * FROM {tabela} WHERE id = ? AND usuario_id = ?", (id_, current_user.id)
    ).fetchone()
    if row is None:
        abort(404)
    return row


def materias_com_assuntos(uid: int) -> list[dict]:
    """
    Matérias com seus assuntos de topo; cada assunto traz a lista `filhos`
    (subassuntos). Usado na tela Matérias e no formulário de sessão.
    """
    db = banco.get_db()
    materias = sorted((dict(m) for m in db.execute(
        "SELECT id, nome, dias_estudo, secao_id FROM materias WHERE usuario_id = ?", (uid,))), key=lambda m: S.chave_ordem(m["nome"]))
    for m in materias:
        m["dias_estudo"] = S.ler_dias(m["dias_estudo"])
    por_materia: dict[int, list] = {m["id"]: [] for m in materias}
    contagem = {r["assunto_id"]: r["n"] for r in db.execute(
        "SELECT assunto_id, COUNT(*) AS n FROM sessoes WHERE usuario_id = ? GROUP BY assunto_id", (uid,))}
    todos = S.listar_assuntos(db, uid)
    filhos: dict[int, list] = {}
    for a in todos:
        a["n_sessoes"] = contagem.get(a["id"], 0)
        if a["parent_id"]:
            filhos.setdefault(a["parent_id"], []).append(a)
    for a in todos:
        if not a["parent_id"]:
            a["filhos"] = filhos.get(a["id"], [])
            por_materia[a["materia_id"]].append(a)
    for m in materias:
        m["assuntos"] = por_materia[m["id"]]
        m["folhas"] = [f for a in m["assuntos"] for f in (a["filhos"] or [a])]
    return materias


def e_grupo(aid: int) -> bool:
    """True se o assunto tem subassuntos (então não recebe sessões diretamente)."""
    return banco.get_db().execute(
        "SELECT 1 FROM assuntos WHERE parent_id = ? AND usuario_id = ? LIMIT 1",
        (aid, current_user.id)).fetchone() is not None


def nome_valido(texto, campo: str, limite: int) -> str:
    nome = (texto or "").strip()
    if not nome:
        raise ValueError(f"Informe o nome {campo}.")
    return nome[:limite]


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

def registrar_rotas(app: Flask):

    @app.before_request
    def protecoes():
        # CSRF em todo POST
        if request.method == "POST" and app.config["CSRF_ATIVO"]:
            enviado = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not enviado or not secrets.compare_digest(enviado, session.get("csrf", "")):
                abort(400, "A página expirou. Recarregue e tente de novo.")
        # Onboarding obrigatório no primeiro acesso
        livres = {"onboarding", "sair", "static", "landing", "demo", "manifest", "service_worker", "offline"}
        if (current_user.is_authenticated and not current_user.onboarding_ok
                and request.endpoint not in livres):
            return redirect(url_for("onboarding"))

    @app.context_processor
    def contexto():
        return {"hoje_data": S.hoje()}

    @app.errorhandler(404)
    def nao_encontrado(_e):
        return render_template("erro.html", codigo=404,
                               mensagem="Página não encontrada (ou não pertence à sua conta)."), 404

    @app.errorhandler(400)
    def requisicao_ruim(e):
        return render_template("erro.html", codigo=400, mensagem=e.description), 400

    @app.errorhandler(413)
    def muito_grande(_e):
        return render_template("erro.html", codigo=413, mensagem="Arquivo grande demais (máximo 5 MB)."), 413

    # ------------------------------------------------------------------ PWA
    # Manifesto e service worker servidos na raiz, para valerem para o site todo
    # (é isso que faz o Chrome oferecer "Instalar Revisa").

    @app.route("/manifest.webmanifest")
    def manifest():
        r = app.send_static_file("manifest.webmanifest")
        r.mimetype = "application/manifest+json"
        return r

    @app.route("/sw.js")
    def service_worker():
        r = app.send_static_file("sw.js")
        r.mimetype = "application/javascript"
        r.headers["Cache-Control"] = "no-cache"
        return r

    @app.route("/offline")
    def offline():
        return render_template("offline.html")

    # ------------------------------------------------------------------ público

    @app.route("/")
    def landing():
        if current_user.is_authenticated:
            return redirect(url_for("hoje"))
        return render_template("landing.html")

    @app.route("/cadastro", methods=["GET", "POST"])
    def cadastro():
        if current_user.is_authenticated:
            return redirect(url_for("hoje"))
        if request.method == "POST":
            nome = (request.form.get("nome") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            senha = request.form.get("senha") or ""
            erro = None
            if not nome or not email or not senha:
                erro = "Preencha nome, e-mail e senha."
            elif "@" not in email or "." not in email.split("@")[-1]:
                erro = "Informe um e-mail válido."
            elif len(senha) < 6:
                erro = "A senha precisa ter pelo menos 6 caracteres."
            db = banco.get_db()
            if not erro and db.execute("SELECT 1 FROM usuarios WHERE email = ?", (email,)).fetchone():
                erro = "Já existe uma conta com este e-mail."
            if erro:
                flash(erro, "erro")
                return render_template("auth/cadastro.html", nome=nome, email=email)
            cur = db.execute(
                "INSERT INTO usuarios (nome, email, senha_hash) VALUES (?, ?, ?)",
                (nome[:100], email[:200], generate_password_hash(senha)))
            db.execute("INSERT INTO configuracoes (usuario_id) VALUES (?)", (cur.lastrowid,))
            db.commit()
            login_user(carregar_usuario(cur.lastrowid))
            return redirect(url_for("onboarding"))
        return render_template("auth/cadastro.html")

    @app.route("/entrar", methods=["GET", "POST"])
    def entrar():
        if current_user.is_authenticated:
            return redirect(url_for("hoje"))
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            senha = request.form.get("senha") or ""
            row = banco.get_db().execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
            if row and check_password_hash(row["senha_hash"], senha):
                login_user(Usuario(row), remember=bool(request.form.get("lembrar")))
                return redirect(destino_seguro(request.args.get("next"), url_for("hoje")))
            flash("E-mail ou senha incorretos.", "erro")
            return render_template("auth/entrar.html", email=email)
        return render_template("auth/entrar.html")

    @app.route("/demo")
    def demo():
        """Entra direto na conta demo (criada com `flask seed-demo`)."""
        row = banco.get_db().execute("SELECT * FROM usuarios WHERE email = ?", (DEMO_EMAIL,)).fetchone()
        if not row:
            flash("A conta demo ainda não foi criada. Rode: flask seed-demo", "erro")
            return redirect(url_for("entrar"))
        login_user(Usuario(row))
        return redirect(destino_seguro(request.args.get("next"), url_for("hoje")))

    @app.route("/sair", methods=["POST"])
    @login_required
    def sair():
        logout_user()
        flash("Você saiu da sua conta.", "info")
        return redirect(url_for("landing"))

    # ------------------------------------------------------------- onboarding

    @app.route("/onboarding", methods=["GET", "POST"])
    @login_required
    def onboarding():
        db = banco.get_db()
        cfg = S.carregar_config(db, current_user.id)
        if request.method == "POST":
            dados = dict(request.form)
            dados["dias_fixos"] = request.form.getlist("dias_fixos")
            try:
                S.salvar_config(db, current_user.id, dados, commit=False)
                # Prova com data: já cria a seção (ex.: ENEM) com a data
                meta = S.ler_campo_meta(request.form, "meta")
                if meta:
                    nome = nome_valido(request.form.get("prova_nome"), "da prova", 120)
                    db.execute("INSERT INTO secoes (usuario_id, nome, data_meta) VALUES (?, ?, ?)",
                               (current_user.id, nome, meta))
            except ValueError as e:
                db.rollback()
                flash(str(e) if "invalid literal" not in str(e) else "Confira os números informados.", "erro")
                return render_template("onboarding.html", cfg=cfg)
            db.execute("UPDATE usuarios SET onboarding_ok = 1 WHERE id = ?", (current_user.id,))
            db.commit()
            flash("Tudo pronto! Agora cadastre suas matérias e os assuntos de cada uma.", "ok")
            return redirect(url_for("materias"))
        return render_template("onboarding.html", cfg=cfg)

    # ------------------------------------------------------------------- hoje

    @app.route("/hoje")
    @login_required
    def hoje():
        dados = S.montar_hoje(banco.get_db(), current_user.id, S.hoje())
        return render_template("hoje.html", **dados)

    @app.route("/hoje/mais", methods=["POST"])
    @login_required
    def fazer_mais_hoje():
        """Atrasou: puxa para hoje mais revisões vencidas que ficaram fora do limite."""
        texto = request.form.get("quantos", "")
        quantos = None if texto == "todas" else (int(texto) if texto.isdigit() else 0)
        n = S.puxar_revisoes(banco.get_db(), current_user.id, S.hoje(), quantos)
        if n:
            flash(f"{n} revis{'ões' if n > 1 else 'ão'} a mais na lista de hoje.", "ok")
        return redirect(url_for("hoje") + "#revisao")

    @app.route("/hoje/registrar", methods=["POST"])
    @login_required
    def registrar_hoje():
        """Registra de uma vez os resultados preenchidos no bloco 3 da tela Hoje."""
        db = banco.get_db()
        dia = S.hoje().isoformat()
        linhas, erros = [], []
        for aid_txt in request.form.getlist("assunto_ids"):
            try:
                aid = int(aid_txt)
            except ValueError:
                continue
            ac, tot = request.form.get(f"acertos_{aid}", "").strip(), request.form.get(f"total_{aid}", "").strip()
            if ac == "":
                continue  # linha sem acertos = não feita (o total já vem sugerido)
            assunto = do_usuario("assuntos", aid)
            try:
                if e_grupo(aid):
                    raise ValueError("tem subassuntos; registre a prática em um deles.")
                acertos, total = validar_resultado(ac, tot)
            except ValueError as e:
                erros.append(f"{assunto['nome']}: {e}")
                continue
            obs = (request.form.get(f"obs_{aid}") or "").strip()[:1000] or None
            linhas.append((current_user.id, aid, dia, acertos, total, obs))
        if erros:
            for e in erros:
                flash(e, "erro")
            flash("Nada foi salvo. Corrija os campos e envie de novo.", "erro")
            return redirect(url_for("hoje") + "#revisao")
        if not linhas:
            flash("Preencha acertos e total de pelo menos um assunto.", "erro")
            return redirect(url_for("hoje") + "#revisao")
        db.executemany(
            "INSERT INTO sessoes (usuario_id, assunto_id, data, acertos, total, observacao) VALUES (?, ?, ?, ?, ?, ?)",
            linhas)
        cfg = S.carregar_config(db, current_user.id)
        for linha in linhas:
            mid = db.execute("SELECT materia_id FROM assuntos WHERE id = ?", (linha[1],)).fetchone()[0]
            S.marcar_ciclo(db, current_user.id, mid, S.hoje(), cfg)
        db.commit()
        flash(f"{len(linhas)} resultado(s) registrado(s). Bom trabalho!", "ok")
        return redirect(url_for("hoje") + "#revisao")

    # ---------------------------------------------------------------- sessões

    def form_sessao(sessao=None):
        """GET/POST compartilhado entre nova sessão e edição."""
        db = banco.get_db()
        materias = materias_com_assuntos(current_user.id)
        valores = {
            "assunto_id": request.args.get("assunto", type=int),
            "data": S.hoje().isoformat(), "acertos": "", "total": "", "observacao": "",
        }
        if sessao:
            valores.update({k: sessao[k] for k in ("assunto_id", "data", "acertos", "total")})
            valores["observacao"] = sessao["observacao"] or ""
        if request.method == "POST":
            valores.update({k: request.form.get(k, "") for k in ("data", "acertos", "total", "observacao")})
            try:
                aid = ler_inteiro(request.form.get("assunto_id"), "assunto")
                valores["assunto_id"] = aid
                do_usuario("assuntos", aid)
                if e_grupo(aid):
                    raise ValueError("Este assunto tem subassuntos: registre a prática em um deles.")
                d = validar_data(valores["data"])
                acertos, total = validar_resultado(valores["acertos"], valores["total"])
            except ValueError as e:
                flash(str(e), "erro")
            else:
                obs = valores["observacao"].strip()[:1000] or None
                if sessao:
                    db.execute(
                        """UPDATE sessoes SET assunto_id = ?, data = ?, acertos = ?, total = ?, observacao = ?
                           WHERE id = ? AND usuario_id = ?""",
                        (aid, d.isoformat(), acertos, total, obs, sessao["id"], current_user.id))
                    msg = "Prática atualizada."
                else:
                    db.execute(
                        """INSERT INTO sessoes (usuario_id, assunto_id, data, acertos, total, observacao)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (current_user.id, aid, d.isoformat(), acertos, total, obs))
                    if d == S.hoje():
                        assunto_reg = do_usuario("assuntos", aid)
                        S.marcar_ciclo(db, current_user.id, assunto_reg["materia_id"], d,
                                       S.carregar_config(db, current_user.id))
                    msg = f"Prática registrada: {acertos}/{total} ({round(acertos / total * 100)}%)."
                db.commit()
                flash(msg, "ok")
                return redirect(url_for("historico", aid=aid))
        return render_template("sessao_form.html", materias=materias, v=valores, sessao=sessao)

    @app.route("/sessoes/nova", methods=["GET", "POST"])
    @login_required
    def nova_sessao():
        return form_sessao()

    @app.route("/sessoes/<int:sid>/editar", methods=["GET", "POST"])
    @login_required
    def editar_sessao(sid):
        return form_sessao(do_usuario("sessoes", sid))

    @app.route("/sessoes/<int:sid>/excluir", methods=["POST"])
    @login_required
    def excluir_sessao(sid):
        s = do_usuario("sessoes", sid)
        db = banco.get_db()
        db.execute("DELETE FROM sessoes WHERE id = ? AND usuario_id = ?", (sid, current_user.id))
        db.commit()
        flash("Prática excluída.", "ok")
        return redirect(url_for("historico", aid=s["assunto_id"]))

    # ------------------------------------------------------------------- mapa

    @app.route("/vencimentos")
    @login_required
    def vencimentos():
        n = 14 if request.args.get("dias") == "14" else 7
        dados = S.montar_vencimentos(banco.get_db(), current_user.id, S.hoje(), n)
        return render_template("vencimentos.html", n_dias=n, **dados)

    @app.route("/mapa")
    @login_required
    def mapa():
        dados = S.montar_mapa(banco.get_db(), current_user.id, S.hoje())
        return render_template("mapa.html", **dados)

    @app.route("/assuntos/<int:aid>")
    @login_required
    def historico(aid):
        db = banco.get_db()
        assunto = dict(do_usuario("assuntos", aid))
        assunto["materia"] = db.execute("SELECT nome FROM materias WHERE id = ? AND usuario_id = ?",
                                        (assunto["materia_id"], current_user.id)).fetchone()["nome"]
        sessoes = [dict(s) for s in db.execute(
            "SELECT * FROM sessoes WHERE assunto_id = ? AND usuario_id = ? ORDER BY data, id",
            (aid, current_user.id))]
        for s in sessoes:
            s["pct"] = s["acertos"] / s["total"]
        cfg = S.carregar_config(db, current_user.id)
        estado = S.estados(db, current_user.id, S.hoje(), cfg, ids={aid}).get(aid)
        grafico = {"labels": [br(s["data"]) for s in sessoes],
                   "valores": [round(s["pct"] * 100, 1) for s in sessoes]}

        # Assunto pai: nome para o caminho no topo da página
        pai = None
        if assunto["parent_id"]:
            pai = dict(do_usuario("assuntos", assunto["parent_id"]))

        # Assunto com subassuntos: vira grupo, mostra o domínio de cada um e a média
        filhos = [dict(f) for f in db.execute(
            "SELECT id, nome FROM assuntos WHERE parent_id = ? AND usuario_id = ? ORDER BY nome COLLATE NOCASE",
            (aid, current_user.id))]
        dominio_grupo = None
        if filhos:
            est = S.estados(db, current_user.id, S.hoje(), cfg, ids={f["id"] for f in filhos})
            for f in filhos:
                f["estado"] = est.get(f["id"])
            dominio_grupo = L.dominio_do_grupo([f["estado"].dominio_efetivo for f in filhos if f["estado"]])
            estado = None  # o grupo em si não tem agenda própria
        return render_template("historico.html", assunto=assunto, sessoes=list(reversed(sessoes)),
                               estado=estado, grafico=grafico, pai=pai, filhos=filhos,
                               dominio_grupo=dominio_grupo)

    # ------------------------------------------------------------- flashcards

    @app.route("/flashcards")
    @login_required
    def flashcards():
        db = banco.get_db()
        return render_template("flashcards.html", materias=C.listar_baralhos(db, current_user.id, S.hoje()),
                               resumo=C.resumo_hoje(db, current_user.id, S.hoje()))

    @app.route("/flashcards/baralhos/novo", methods=["POST"])
    @login_required
    def criar_baralho():
        try:
            nome = nome_valido(request.form.get("nome"), "do baralho", 120)
            mid = ler_inteiro(request.form.get("materia_id"), "matéria")
        except ValueError as e:
            flash(str(e), "erro")
            return redirect(url_for("flashcards"))
        do_usuario("materias", mid)
        bid = banco.get_db().execute("INSERT INTO baralhos (usuario_id, materia_id, nome) VALUES (?, ?, ?)",
                                     (current_user.id, mid, nome)).lastrowid
        banco.get_db().commit()
        flash("Baralho criado. Agora adicione os cartões.", "ok")
        return redirect(url_for("baralho", bid=bid))

    @app.route("/flashcards/baralhos/<int:bid>")
    @login_required
    def baralho(bid):
        db = banco.get_db()
        b = dict(do_usuario("baralhos", bid))
        b["materia"] = db.execute("SELECT nome FROM materias WHERE id = ?", (b["materia_id"],)).fetchone()["nome"]
        # um item por cartão, com a próxima revisão do lado que vence primeiro
        por_cartao: dict[int, dict] = {}
        for lado in C.cartoes_com_agenda(db, current_user.id, S.hoje(), baralho_id=bid):
            atual = por_cartao.get(lado["id"])
            if atual is None or (lado["proxima"] or date.min) < (atual["proxima"] or date.min):
                por_cartao[lado["id"]] = lado
        lista = sorted(por_cartao.values(), key=lambda c: -c["id"])
        f = C.fila(db, current_user.id, S.hoje(), baralho_id=bid)
        materias_b = sorted((dict(m) for m in db.execute("SELECT id, nome FROM materias WHERE usuario_id = ?",
                                                         (current_user.id,))), key=lambda m: S.chave_ordem(m["nome"]))
        return render_template("baralho.html", b=b, cartoes=lista, fila=f, materias=materias_b,
                               busca=(request.args.get("q") or "").strip())

    @app.route("/flashcards/baralhos/<int:bid>/editar", methods=["POST"])
    @login_required
    def editar_baralho(bid):
        do_usuario("baralhos", bid)
        try:
            nome = nome_valido(request.form.get("nome"), "do baralho", 120)
            mid = ler_inteiro(request.form.get("materia_id"), "matéria")
            do_usuario("materias", mid)
            banco.get_db().execute("UPDATE baralhos SET nome = ?, materia_id = ? WHERE id = ? AND usuario_id = ?",
                                   (nome, mid, bid, current_user.id))
            banco.get_db().commit()
            flash("Baralho atualizado.", "ok")
        except ValueError as e:
            flash(str(e), "erro")
        return redirect(url_for("baralho", bid=bid))

    @app.route("/flashcards/baralhos/<int:bid>/excluir", methods=["POST"])
    @login_required
    def excluir_baralho(bid):
        do_usuario("baralhos", bid)
        db = banco.get_db()
        db.execute("DELETE FROM baralhos WHERE id = ? AND usuario_id = ?", (bid, current_user.id))
        C.apagar_imagens_soltas(db, current_user.id)
        db.commit()
        flash("Baralho excluído, com os cartões.", "ok")
        return redirect(url_for("flashcards"))

    def imagem_do_form(campo: str, atual: int | None = None) -> int | None:
        """Imagem enviada (ou colada) no formulário; "remover_<campo>" tira a atual."""
        arq = request.files.get(campo)
        if arq and arq.filename:
            return C.guardar_imagem(banco.get_db(), current_user.id, arq.read())
        if request.form.get(f"remover_{campo}"):
            return None
        return atual

    def textos_do_cartao(img_frente, img_verso) -> tuple[str, str]:
        frente = (request.form.get("frente") or "").strip()[:2000]
        verso = (request.form.get("verso") or "").strip()[:2000]
        if not (frente or img_frente) or not (verso or img_verso):
            raise ValueError("Preencha a frente e o verso do cartão (texto ou imagem).")
        return frente, verso

    @app.route("/flashcards/baralhos/<int:bid>/cartoes", methods=["POST"])
    @login_required
    def criar_cartoes(bid):
        do_usuario("baralhos", bid)
        db = banco.get_db()
        invertido = 1 if request.form.get("invertido") else 0
        try:
            if request.form.get("lote") is not None:
                for frente, verso in C.ler_em_lote(request.form.get("lote")):
                    db.execute("INSERT INTO cartoes (usuario_id, baralho_id, frente, verso, invertido) VALUES (?, ?, ?, ?, ?)",
                               (current_user.id, bid, frente, verso, invertido))
            else:
                img_f, img_v = imagem_do_form("imagem_frente"), imagem_do_form("imagem_verso")
                frente, verso = textos_do_cartao(img_f, img_v)
                db.execute("""INSERT INTO cartoes (usuario_id, baralho_id, frente, verso, invertido, imagem_frente, imagem_verso)
                              VALUES (?, ?, ?, ?, ?, ?, ?)""", (current_user.id, bid, frente, verso, invertido, img_f, img_v))
        except ValueError as e:
            db.rollback()
            flash(str(e), "erro")
            return redirect(url_for("baralho", bid=bid) + "#novo")
        db.commit()
        if request.form.get("lote") is not None:
            n = len(C.ler_em_lote(request.form.get("lote")))
            flash(f"{n} cart{'ões' if n > 1 else 'ão'} adicionado{'s' if n > 1 else ''}.", "ok")
            return redirect(url_for("baralho", bid=bid) + "#lote")
        flash("Cartão adicionado.", "ok")
        return redirect(url_for("baralho", bid=bid) + "#novo")

    def voltar_do_cartao(c):
        """Depois de mexer num cartão: volta para o estudo (se veio dele) ou para o baralho."""
        if request.form.get("voltar") == "estudo":
            args = {k: v for k, v in (("baralho", request.form.get("baralho", type=int)),
                                      ("materia", request.form.get("materia", type=int))) if v}
            return redirect(url_for("estudar", **args))
        return redirect(url_for("baralho", bid=c["baralho_id"]) + f"#cartao-{c['id']}")

    @app.route("/flashcards/cartoes/<int:cid>/editar", methods=["POST"])
    @login_required
    def editar_cartao(cid):
        c = do_usuario("cartoes", cid)
        db = banco.get_db()
        try:
            img_f = imagem_do_form("imagem_frente", c["imagem_frente"])
            img_v = imagem_do_form("imagem_verso", c["imagem_verso"])
            frente, verso = textos_do_cartao(img_f, img_v)
            invertido = (1 if request.form.get("invertido") else 0) if "tem_invertido" in request.form else c["invertido"]
            db.execute("""UPDATE cartoes SET frente = ?, verso = ?, invertido = ?, imagem_frente = ?, imagem_verso = ?
                          WHERE id = ? AND usuario_id = ?""", (frente, verso, invertido, img_f, img_v, cid, current_user.id))
            C.apagar_imagens_soltas(db, current_user.id)
            db.commit()
            flash("Cartão atualizado.", "ok")
        except ValueError as e:
            db.rollback()
            flash(str(e), "erro")
        return voltar_do_cartao(c)

    @app.route("/flashcards/cartoes/<int:cid>/excluir", methods=["POST"])
    @login_required
    def excluir_cartao(cid):
        c = do_usuario("cartoes", cid)
        db = banco.get_db()
        db.execute("DELETE FROM cartoes WHERE id = ? AND usuario_id = ?", (cid, current_user.id))
        C.apagar_imagens_soltas(db, current_user.id)
        db.commit()
        flash("Cartão excluído.", "ok")
        if request.form.get("voltar") == "estudo":
            return voltar_do_cartao(c)
        return redirect(url_for("baralho", bid=c["baralho_id"]))

    @app.route("/flashcards/cartoes/<int:cid>/suspender", methods=["POST"])
    @login_required
    def suspender_cartao(cid):
        """Suspender tira o cartão do estudo até reativar (de novo = reativa)."""
        c = do_usuario("cartoes", cid)
        novo = 0 if c["suspenso"] else 1
        banco.get_db().execute("UPDATE cartoes SET suspenso = ? WHERE id = ? AND usuario_id = ?",
                               (novo, cid, current_user.id))
        banco.get_db().commit()
        flash("Cartão suspenso: ele não aparece no estudo até você reativar." if novo else "Cartão reativado.", "ok")
        return voltar_do_cartao(c)

    @app.route("/flashcards/cartoes/<int:cid>/adiar", methods=["POST"])
    @login_required
    def adiar_cartao(cid):
        """Adiar tira o cartão só de hoje: amanhã ele volta."""
        c = do_usuario("cartoes", cid)
        banco.get_db().execute("UPDATE cartoes SET adiado = ? WHERE id = ? AND usuario_id = ?",
                               (S.hoje().isoformat(), cid, current_user.id))
        banco.get_db().commit()
        flash("Cartão adiado para amanhã.", "ok")
        return voltar_do_cartao(c)

    @app.route("/flashcards/imagens/<int:iid>")
    @login_required
    def imagem_cartao(iid):
        r = banco.get_db().execute("SELECT tipo, dados FROM imagens WHERE id = ? AND usuario_id = ?",
                                   (iid, current_user.id)).fetchone()
        if r is None:
            abort(404)
        return Response(r["dados"], mimetype=r["tipo"], headers={"Cache-Control": "private, max-age=86400"})

    def escopo_estudo():
        """Estudar um baralho, uma matéria ou tudo (?baralho= / ?materia=)."""
        bid = request.values.get("baralho", type=int)
        mid = request.values.get("materia", type=int)
        if bid:
            do_usuario("baralhos", bid)
        if mid:
            do_usuario("materias", mid)
        return bid, mid

    @app.route("/flashcards/estudar")
    @login_required
    def estudar():
        db = banco.get_db()
        bid, mid = escopo_estudo()
        f = C.fila(db, current_user.id, S.hoje(), baralho_id=bid, materia_id=mid)
        titulo = "Todos os baralhos"
        if bid:
            titulo = do_usuario("baralhos", bid)["nome"]
        elif mid:
            titulo = do_usuario("materias", mid)["nome"]
        cartao = f["cartoes"][0] if f["cartoes"] else None
        feitos = db.execute("SELECT COUNT(*) FROM respostas_cartao WHERE usuario_id = ? AND data = ?",
                            (current_user.id, S.hoje().isoformat())).fetchone()[0]
        return render_template("estudar.html", cartao=cartao, fila=f, titulo=titulo, bid=bid, mid=mid, feitos=feitos)

    @app.route("/flashcards/responder", methods=["POST"])
    @login_required
    def responder_cartao():
        db = banco.get_db()
        bid, mid = escopo_estudo()
        cid = request.form.get("cartao_id", type=int)
        nota = request.form.get("nota")
        if cid and nota in L.NOTAS_CARTAO:
            c = do_usuario("cartoes", cid)
            lado = 1 if request.form.get("lado", type=int) and c["invertido"] else 0
            C.responder(db, current_user.id, cid, lado, nota, S.hoje())
        args = {k: v for k, v in (("baralho", bid), ("materia", mid)) if v}
        return redirect(url_for("estudar", **args))

    @app.route("/flashcards/desfazer", methods=["POST"])
    @login_required
    def desfazer_resposta():
        """Desfaz a última resposta de hoje: o cartão volta para a fila."""
        bid, mid = escopo_estudo()
        if C.desfazer(banco.get_db(), current_user.id, S.hoje()):
            flash("Última resposta desfeita.", "ok")
        args = {k: v for k, v in (("baralho", bid), ("materia", mid)) if v}
        return redirect(url_for("estudar", **args))

    # ------------------------------------------------------- matérias/assuntos

    @app.route("/materias")
    @login_required
    def materias():
        cfg_m = S.carregar_config(banco.get_db(), current_user.id)
        todas = materias_com_assuntos(current_user.id)
        secoes = S.listar_secoes(banco.get_db(), current_user.id)
        hoje_d = S.hoje()
        for sec in secoes:
            sec["materias"] = [m for m in todas if m["secao_id"] == sec["id"]]
            sec["faltam"] = (sec["meta"] - hoje_d).days if sec["meta"] else None
        soltas = [m for m in todas if not m["secao_id"]]
        return render_template("materias.html", materias=todas, secoes=secoes, soltas=soltas,
                               cfg=cfg_m, ciclo=S.ler_ciclo(banco.get_db(), current_user.id),
                               vez_ids=[it["id"] for it in S.vez_do_ciclo(banco.get_db(), current_user.id, S.hoje(), cfg_m)],
                               editando=request.args.get("editar", type=int))

    def executar(acao, ok_msg, mid=None):
        """
        Executa uma alteração e volta para a tela de matérias na MESMA matéria
        (âncora #materia-ID), mantendo o modo de edição se ele estava aberto.
        `acao` pode devolver o id da matéria (ex.: matéria recém-criada).
        """
        try:
            r = acao()
        except ValueError as e:
            flash(str(e), "erro")
        else:
            banco.get_db().commit()
            flash(ok_msg, "ok")
            mid = r or mid
        args = {"editar": mid} if mid and request.form.get("editando") else {}
        return redirect(url_for("materias", **args) + (f"#materia-{mid}" if mid else ""))

    def secao_do_form():
        """Seção escolhida num formulário (vazio = sem seção), conferindo o dono."""
        sid = request.form.get("secao_id", type=int)
        if sid:
            do_usuario("secoes", sid)
        return sid or None

    @app.route("/secoes/nova", methods=["POST"])
    @login_required
    def criar_secao():
        try:
            nome = nome_valido(request.form.get("nome"), "da seção", 120)
            meta = S.ler_campo_meta(request.form, "meta")
        except ValueError as e:
            flash(str(e), "erro")
            return redirect(url_for("materias"))
        sid = banco.get_db().execute("INSERT INTO secoes (usuario_id, nome, data_meta) VALUES (?, ?, ?)",
                                     (current_user.id, nome, meta)).lastrowid
        banco.get_db().commit()
        flash("Seção criada. Agora adicione as matérias dela.", "ok")
        return redirect(url_for("materias") + f"#secao-{sid}")

    @app.route("/secoes/<int:sid>/editar", methods=["POST"])
    @login_required
    def editar_secao(sid):
        do_usuario("secoes", sid)
        try:
            nome = nome_valido(request.form.get("nome"), "da seção", 120)
            meta = S.ler_campo_meta(request.form, "meta")
            banco.get_db().execute("UPDATE secoes SET nome = ?, data_meta = ? WHERE id = ? AND usuario_id = ?",
                                   (nome, meta, sid, current_user.id))
            banco.get_db().commit()
            flash("Seção atualizada.", "ok")
        except ValueError as e:
            flash(str(e), "erro")
        return redirect(url_for("materias") + f"#secao-{sid}")

    @app.route("/secoes/<int:sid>/excluir", methods=["POST"])
    @login_required
    def excluir_secao(sid):
        do_usuario("secoes", sid)
        banco.get_db().execute("DELETE FROM secoes WHERE id = ? AND usuario_id = ?", (sid, current_user.id))
        banco.get_db().commit()
        flash("Seção excluída. As matérias dela continuam, sem seção.", "ok")
        return redirect(url_for("materias"))

    @app.route("/materias/nova", methods=["POST"])
    @login_required
    def criar_materia():
        sid = secao_do_form()

        def acao():
            nome = nome_valido(request.form.get("nome"), "da matéria", 120)
            return banco.get_db().execute("INSERT INTO materias (usuario_id, nome, secao_id) VALUES (?, ?, ?)",
                                          (current_user.id, nome, sid)).lastrowid
        return executar(acao, "Matéria criada.")

    @app.route("/materias/<int:mid>/editar", methods=["POST"])
    @login_required
    def editar_materia(mid):
        atual = do_usuario("materias", mid)
        sid = secao_do_form() if "secao_id" in request.form else atual["secao_id"]

        def acao():
            nome = nome_valido(request.form.get("nome"), "da matéria", 120)
            # "Quando estudo esta matéria": todo dia (vazio) ou dias escolhidos
            # Sem o campo (pessoa estuda todas as matérias todo dia): mantém o que já estava salvo
            if "frequencia" not in request.form:
                dias = banco.get_db().execute("SELECT dias_estudo FROM materias WHERE id = ?", (mid,)).fetchone()[0]
            else:
                dias = ""
            if request.form.get("frequencia") == "dias":
                dias = ",".join(map(str, S.ler_dias(",".join(request.form.getlist("dias_estudo")))))
                if not dias:
                    raise ValueError("Escolha pelo menos um dia de estudo para a matéria.")
            banco.get_db().execute(
                "UPDATE materias SET nome = ?, dias_estudo = ?, secao_id = ? WHERE id = ? AND usuario_id = ?",
                (nome, dias, sid, mid, current_user.id))
        return executar(acao, "Matéria atualizada.", mid)

    @app.route("/materias/<int:mid>/excluir", methods=["POST"])
    @login_required
    def excluir_materia(mid):
        do_usuario("materias", mid)
        def acao():
            banco.get_db().execute("DELETE FROM materias WHERE id = ? AND usuario_id = ?", (mid, current_user.id))
        return executar(acao, "Matéria excluída, com seus assuntos e práticas.")

    @app.route("/assuntos/novo", methods=["POST"])
    @login_required
    def criar_assunto():
        pai_id = request.form.get("parent_id", type=int)

        def acao():
            nome = nome_valido(request.form.get("nome"), "do assunto", 160)
            if pai_id:
                # Subassunto: herda a matéria do pai; só um nível de profundidade.
                pai = do_usuario("assuntos", pai_id)
                if pai["parent_id"]:
                    raise ValueError("Subassuntos não podem ter outros subassuntos.")
                mid = pai["materia_id"]
            else:
                mid = ler_inteiro(request.form.get("materia_id"), "matéria")
                do_usuario("materias", mid)
            banco.get_db().execute(
                "INSERT INTO assuntos (usuario_id, materia_id, nome, parent_id) VALUES (?, ?, ?, ?)",
                (current_user.id, mid, nome, pai_id or None))
            return mid
        return executar(acao, "Subassunto criado." if pai_id else "Assunto criado.",
                        request.form.get("materia_id", type=int))

    @app.route("/assuntos/<int:aid>/editar", methods=["POST"])
    @login_required
    def editar_assunto(aid):
        assunto = do_usuario("assuntos", aid)
        def acao():
            db = banco.get_db()
            nome = nome_valido(request.form.get("nome"), "do assunto", 160)
            if assunto["parent_id"]:
                # Subassunto: só o nome muda (a matéria é sempre a do pai).
                db.execute("UPDATE assuntos SET nome = ? WHERE id = ? AND usuario_id = ?",
                           (nome, aid, current_user.id))
                return assunto["materia_id"]
            mid = request.form.get("materia_id", type=int) or assunto["materia_id"]
            do_usuario("materias", mid)
            db.execute("UPDATE assuntos SET nome = ?, materia_id = ? WHERE id = ? AND usuario_id = ?",
                       (nome, mid, aid, current_user.id))
            # Os subassuntos acompanham o pai se ele mudar de matéria.
            db.execute("UPDATE assuntos SET materia_id = ? WHERE parent_id = ? AND usuario_id = ?",
                       (mid, aid, current_user.id))
            return mid
        return executar(acao, "Assunto atualizado.", assunto["materia_id"])

    @app.route("/assuntos/<int:aid>/excluir", methods=["POST"])
    @login_required
    def excluir_assunto(aid):
        assunto = do_usuario("assuntos", aid)
        def acao():
            banco.get_db().execute("DELETE FROM assuntos WHERE id = ? AND usuario_id = ?", (aid, current_user.id))
        return executar(acao, "Excluído, com as práticas.", assunto["materia_id"])

    # ---------------------------------------------------------- ciclo de estudos

    def voltar_ciclo():
        return redirect(url_for("materias") + "#ciclo")

    def renumerar_ciclo(db):
        ids = [r["id"] for r in db.execute(
            "SELECT id FROM ciclo_itens WHERE usuario_id = ? ORDER BY posicao, id", (current_user.id,))]
        for pos, iid in enumerate(ids):
            db.execute("UPDATE ciclo_itens SET posicao = ? WHERE id = ?", (pos, iid))

    @app.route("/ciclo/adicionar", methods=["POST"])
    @login_required
    def ciclo_adicionar():
        mid = request.form.get("materia_id", type=int)
        if not mid:
            flash("Escolha uma matéria para adicionar ao ciclo.", "erro")
            return voltar_ciclo()
        do_usuario("materias", mid)
        db = banco.get_db()
        fim = db.execute("SELECT COALESCE(MAX(posicao), -1) + 1 FROM ciclo_itens WHERE usuario_id = ?",
                         (current_user.id,)).fetchone()[0]
        # entra na rodada atual mais baixa, para não furar nem ficar para trás na fila
        rodada = db.execute("SELECT COALESCE(MIN(rodada), 0) FROM ciclo_itens WHERE usuario_id = ?",
                            (current_user.id,)).fetchone()[0]
        db.execute("INSERT INTO ciclo_itens (usuario_id, materia_id, posicao, rodada) VALUES (?, ?, ?, ?)",
                   (current_user.id, mid, fim, rodada))
        db.commit()
        return voltar_ciclo()

    @app.route("/ciclo/<int:iid>/mover/<direcao>", methods=["POST"])
    @login_required
    def ciclo_mover(iid, direcao):
        do_usuario("ciclo_itens", iid)
        db = banco.get_db()
        renumerar_ciclo(db)
        ids = [r["id"] for r in db.execute(
            "SELECT id FROM ciclo_itens WHERE usuario_id = ? ORDER BY posicao", (current_user.id,))]
        i = ids.index(iid)
        j = i - 1 if direcao == "cima" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            for pos, x in enumerate(ids):
                db.execute("UPDATE ciclo_itens SET posicao = ? WHERE id = ?", (pos, x))
        db.commit()
        return voltar_ciclo()

    @app.route("/ciclo/<int:iid>/remover", methods=["POST"])
    @login_required
    def ciclo_remover(iid):
        do_usuario("ciclo_itens", iid)
        db = banco.get_db()
        db.execute("DELETE FROM ciclo_itens WHERE id = ? AND usuario_id = ?", (iid, current_user.id))
        renumerar_ciclo(db)
        db.commit()
        return voltar_ciclo()

    @app.route("/ciclo/<int:iid>/pular", methods=["POST"])
    @login_required
    def ciclo_pular(iid):
        """Passa a vez da matéria hoje: ela vai para o fim da rodada e entra a próxima."""
        do_usuario("ciclo_itens", iid)
        db = banco.get_db()
        db.execute("UPDATE ciclo_itens SET rodada = rodada + 1 WHERE id = ? AND usuario_id = ?",
                   (iid, current_user.id))
        db.commit()
        return redirect(url_for("hoje"))

    # ----------------------------------------------------------- configurações

    @app.route("/configuracoes", methods=["GET", "POST"])
    @login_required
    def configuracoes():
        db = banco.get_db()
        if request.method == "POST":
            dados = dict(request.form)
            dados["dias_fixos"] = request.form.getlist("dias_fixos")
            try:
                S.salvar_config(db, current_user.id, dados, commit=False)
                # data da prova de cada seção
                for sec in db.execute("SELECT id FROM secoes WHERE usuario_id = ?", (current_user.id,)).fetchall():
                    if f"meta_{sec['id']}_tipo" in request.form:
                        db.execute("UPDATE secoes SET data_meta = ? WHERE id = ? AND usuario_id = ?",
                                   (S.ler_campo_meta(request.form, f"meta_{sec['id']}"), sec["id"], current_user.id))
                db.commit()
                flash("Configurações salvas.", "ok")
            except ValueError as e:
                db.rollback()
                flash(str(e) if "invalid literal" not in str(e) else "Confira os números informados.", "erro")
            return redirect(url_for("configuracoes"))
        return render_template("configuracoes.html", cfg=S.carregar_config(db, current_user.id),
                               secoes=S.listar_secoes(db, current_user.id))

    @app.route("/configuracoes/exportar")
    @login_required
    def exportar():
        dados = S.exportar(banco.get_db(), current_user.id)
        nome = f"revisa-{S.hoje().isoformat()}.json"
        return Response(json.dumps(dados, ensure_ascii=False, indent=2),
                        mimetype="application/json",
                        headers={"Content-Disposition": f"attachment; filename={nome}"})

    @app.route("/configuracoes/importar", methods=["POST"])
    @login_required
    def importar():
        arquivo = request.files.get("arquivo")
        if not arquivo or not arquivo.filename:
            flash("Escolha um arquivo .json exportado pelo Revisa.", "erro")
            return redirect(url_for("configuracoes"))
        if not request.form.get("confirmar"):
            flash("Marque a confirmação: a importação substitui seus dados atuais.", "erro")
            return redirect(url_for("configuracoes"))
        try:
            dados = json.loads(arquivo.read().decode("utf-8-sig"))
            r = S.importar(banco.get_db(), current_user.id, dados, substituir=True)
        except (UnicodeDecodeError, json.JSONDecodeError):
            flash("O arquivo não é um JSON válido.", "erro")
        except (S.ErroImportacao, ValueError) as e:
            flash(f"Importação cancelada: {e}", "erro")
        else:
            flash(f"Importado: {r['materias']} matérias, {r['assuntos']} assuntos, {r['sessoes']} práticas"
                  f" e {r['cartoes']} flashcards.", "ok")
        return redirect(url_for("configuracoes"))


# ---------------------------------------------------------------------------
# Comandos de linha (flask seed-demo)
# ---------------------------------------------------------------------------

def registrar_comandos(app: Flask):
    @app.cli.command("seed-demo")
    def seed_demo():
        """Cria (ou recria) a conta demo@demo.com / demo123 com dados de exemplo."""
        from seed import criar_demo
        con = banco.conectar(app.config["DATABASE"])
        n = criar_demo(con, S.hoje())
        con.close()
        click.echo(f"Conta demo pronta: {DEMO_EMAIL} / demo123 ({n} práticas de exemplo).")


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")
