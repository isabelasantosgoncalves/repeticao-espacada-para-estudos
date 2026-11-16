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
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,  # limite para importação de JSON
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
    app.jinja_env.filters.update(br=br, relativo=relativo, pct=pct, cor=cor_dominio)
    app.jinja_env.globals.update(csrf_token=csrf_token, NOMES_DIAS=S.NOMES_DIAS)


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
        raise ValueError("A data da sessão não pode estar no futuro.")
    return d


# ---------------------------------------------------------------------------
# Acesso aos dados do usuário logado (sempre filtrado por usuario_id)
# ---------------------------------------------------------------------------

def do_usuario(tabela: str, id_: int):
    """Busca um registro do usuário logado ou responde 404."""
    assert tabela in ("materias", "assuntos", "sessoes")
    row = banco.get_db().execute(
        f"SELECT * FROM {tabela} WHERE id = ? AND usuario_id = ?", (id_, current_user.id)
    ).fetchone()
    if row is None:
        abort(404)
    return row


def materias_com_assuntos(uid: int) -> list[dict]:
    db = banco.get_db()
    materias = [dict(m) for m in db.execute(
        "SELECT id, nome FROM materias WHERE usuario_id = ? ORDER BY nome COLLATE NOCASE", (uid,))]
    por_materia: dict[int, list] = {m["id"]: [] for m in materias}
    contagem = {r["assunto_id"]: r["n"] for r in db.execute(
        "SELECT assunto_id, COUNT(*) AS n FROM sessoes WHERE usuario_id = ? GROUP BY assunto_id", (uid,))}
    for a in db.execute(
            "SELECT id, nome, materia_id FROM assuntos WHERE usuario_id = ? ORDER BY nome COLLATE NOCASE", (uid,)):
        a = dict(a)
        a["n_sessoes"] = contagem.get(a["id"], 0)
        por_materia[a["materia_id"]].append(a)
    for m in materias:
        m["assuntos"] = por_materia[m["id"]]
    return materias


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
                abort(400, "Sessão expirada. Recarregue a página e tente de novo.")
        # Onboarding obrigatório no primeiro acesso
        livres = {"onboarding", "sair", "static", "landing"}
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
            except ValueError as e:
                flash(str(e) if "invalid literal" not in str(e) else "Confira os números informados.", "erro")
                return render_template("onboarding.html", cfg=cfg)
            db.execute("UPDATE usuarios SET onboarding_ok = 1 WHERE id = ?", (current_user.id,))
            db.commit()
            flash("Tudo pronto! Comece cadastrando suas matérias e assuntos.", "ok")
            return redirect(url_for("materias"))
        return render_template("onboarding.html", cfg=cfg)

    # ------------------------------------------------------------------- hoje

    @app.route("/hoje")
    @login_required
    def hoje():
        dados = S.montar_hoje(banco.get_db(), current_user.id, S.hoje())
        return render_template("hoje.html", **dados)

    @app.route("/hoje/novo", methods=["POST"])
    @login_required
    def escolher_novo():
        aid = request.form.get("assunto_id", type=int)
        if not aid:
            flash("Escolha um assunto.", "erro")
            return redirect(url_for("hoje") + "#novo")
        do_usuario("assuntos", aid)
        db = banco.get_db()
        db.execute("INSERT OR IGNORE INTO estudo_do_dia (usuario_id, assunto_id, data) VALUES (?, ?, ?)",
                   (current_user.id, aid, S.hoje().isoformat()))
        db.commit()
        return redirect(url_for("hoje") + "#novo")

    @app.route("/hoje/novo/<int:aid>/remover", methods=["POST"])
    @login_required
    def remover_novo(aid):
        db = banco.get_db()
        db.execute("DELETE FROM estudo_do_dia WHERE usuario_id = ? AND assunto_id = ? AND data = ?",
                   (current_user.id, aid, S.hoje().isoformat()))
        db.commit()
        return redirect(url_for("hoje") + "#novo")

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
            return redirect(url_for("hoje") + "#registrar")
        if not linhas:
            flash("Preencha acertos e total de pelo menos um assunto.", "erro")
            return redirect(url_for("hoje") + "#registrar")
        db.executemany(
            "INSERT INTO sessoes (usuario_id, assunto_id, data, acertos, total, observacao) VALUES (?, ?, ?, ?, ?, ?)",
            linhas)
        db.commit()
        flash(f"{len(linhas)} resultado(s) registrado(s). Bom trabalho!", "ok")
        return redirect(url_for("hoje") + "#registrar")

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
                    msg = "Sessão atualizada."
                else:
                    db.execute(
                        """INSERT INTO sessoes (usuario_id, assunto_id, data, acertos, total, observacao)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (current_user.id, aid, d.isoformat(), acertos, total, obs))
                    msg = f"Sessão registrada: {acertos}/{total} ({round(acertos / total * 100)}%)."
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
        flash("Sessão excluída.", "ok")
        return redirect(url_for("historico", aid=s["assunto_id"]))

    # ------------------------------------------------------------------- mapa

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
        estado = L.analisar_assunto(
            aid, [(date.fromisoformat(s["data"]), s["acertos"], s["total"]) for s in sessoes],
            S.hoje(), S.questoes_fixas(cfg))
        grafico = {"labels": [br(s["data"]) for s in sessoes],
                   "valores": [round(s["pct"] * 100, 1) for s in sessoes]}
        return render_template("historico.html", assunto=assunto, sessoes=list(reversed(sessoes)),
                               estado=estado, grafico=grafico)

    # ------------------------------------------------------- matérias/assuntos

    @app.route("/materias")
    @login_required
    def materias():
        return render_template("materias.html", materias=materias_com_assuntos(current_user.id))

    def executar(acao, ok_msg):
        """Executa uma alteração simples e volta para a tela de matérias."""
        try:
            acao()
        except ValueError as e:
            flash(str(e), "erro")
        else:
            banco.get_db().commit()
            flash(ok_msg, "ok")
        return redirect(url_for("materias"))

    @app.route("/materias/nova", methods=["POST"])
    @login_required
    def criar_materia():
        def acao():
            nome = nome_valido(request.form.get("nome"), "da matéria", 120)
            banco.get_db().execute("INSERT INTO materias (usuario_id, nome) VALUES (?, ?)", (current_user.id, nome))
        return executar(acao, "Matéria criada.")

    @app.route("/materias/<int:mid>/editar", methods=["POST"])
    @login_required
    def editar_materia(mid):
        do_usuario("materias", mid)
        def acao():
            nome = nome_valido(request.form.get("nome"), "da matéria", 120)
            banco.get_db().execute("UPDATE materias SET nome = ? WHERE id = ? AND usuario_id = ?",
                                   (nome, mid, current_user.id))
        return executar(acao, "Matéria renomeada.")

    @app.route("/materias/<int:mid>/excluir", methods=["POST"])
    @login_required
    def excluir_materia(mid):
        do_usuario("materias", mid)
        def acao():
            banco.get_db().execute("DELETE FROM materias WHERE id = ? AND usuario_id = ?", (mid, current_user.id))
        return executar(acao, "Matéria excluída, com seus assuntos e sessões.")

    @app.route("/assuntos/novo", methods=["POST"])
    @login_required
    def criar_assunto():
        def acao():
            mid = ler_inteiro(request.form.get("materia_id"), "matéria")
            do_usuario("materias", mid)
            nome = nome_valido(request.form.get("nome"), "do assunto", 160)
            banco.get_db().execute("INSERT INTO assuntos (usuario_id, materia_id, nome) VALUES (?, ?, ?)",
                                   (current_user.id, mid, nome))
        return executar(acao, "Assunto criado.")

    @app.route("/assuntos/<int:aid>/editar", methods=["POST"])
    @login_required
    def editar_assunto(aid):
        do_usuario("assuntos", aid)
        def acao():
            nome = nome_valido(request.form.get("nome"), "do assunto", 160)
            mid = ler_inteiro(request.form.get("materia_id"), "matéria")
            do_usuario("materias", mid)
            banco.get_db().execute("UPDATE assuntos SET nome = ?, materia_id = ? WHERE id = ? AND usuario_id = ?",
                                   (nome, mid, aid, current_user.id))
        return executar(acao, "Assunto atualizado.")

    @app.route("/assuntos/<int:aid>/excluir", methods=["POST"])
    @login_required
    def excluir_assunto(aid):
        do_usuario("assuntos", aid)
        def acao():
            banco.get_db().execute("DELETE FROM assuntos WHERE id = ? AND usuario_id = ?", (aid, current_user.id))
        return executar(acao, "Assunto excluído, com suas sessões.")

    # ----------------------------------------------------------- configurações

    @app.route("/configuracoes", methods=["GET", "POST"])
    @login_required
    def configuracoes():
        db = banco.get_db()
        if request.method == "POST":
            dados = dict(request.form)
            dados["dias_fixos"] = request.form.getlist("dias_fixos")
            try:
                S.salvar_config(db, current_user.id, dados)
                flash("Configurações salvas.", "ok")
            except ValueError as e:
                flash(str(e) if "invalid literal" not in str(e) else "Confira os números informados.", "erro")
            return redirect(url_for("configuracoes"))
        return render_template("configuracoes.html", cfg=S.carregar_config(db, current_user.id))

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
            flash(f"Importado: {r['materias']} matérias, {r['assuntos']} assuntos e {r['sessoes']} sessões.", "ok")
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
        click.echo(f"Conta demo pronta: {DEMO_EMAIL} / demo123 ({n} sessões de exemplo).")


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")
