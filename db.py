"""Conexão com o SQLite e criação do esquema (feita automaticamente)."""

import sqlite3

from flask import current_app, g

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nome          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    senha_hash    TEXT    NOT NULL,
    criado_em     TEXT    NOT NULL DEFAULT (date('now')),
    onboarding_ok INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS configuracoes (
    usuario_id      INTEGER PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    modo            TEXT    NOT NULL DEFAULT 'ambos',   -- fixa | diaria | ambos
    dias_fixos      TEXT    NOT NULL DEFAULT '6',       -- ex.: '0,3' (0 = segunda)
    revisao_minima  INTEGER NOT NULL DEFAULT 2,
    questoes_modo   TEXT    NOT NULL DEFAULT 'auto',    -- auto | fixo
    questoes_fixas  INTEGER NOT NULL DEFAULT 10,
    ritmo           TEXT    NOT NULL DEFAULT 'leve',    -- leve | moderado | intenso
    aprendizado     TEXT    NOT NULL DEFAULT 'padrao',  -- cautelosa | degraus | padrao | solta
    teto_dias       INTEGER NOT NULL DEFAULT 45,        -- máximo de dias sem revisar um assunto
    adiantar        INTEGER NOT NULL DEFAULT 1,         -- (sem uso) antigo "adiantar revisões"
    distribuicao    TEXT    NOT NULL DEFAULT 'todas'    -- todas (todo dia) | dias (cada seção tem seus dias)
);

-- "Seções" na interface (ex.: SAT Math). dias_estudo vazio = todo dia;
-- senão, dias da semana em que a seção é estudada (ex.: '0,2,4' = seg/qua/sex).
CREATE TABLE IF NOT EXISTS materias (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nome        TEXT    NOT NULL,
    dias_estudo TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS assuntos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    materia_id  INTEGER NOT NULL REFERENCES materias(id) ON DELETE CASCADE,
    nome        TEXT    NOT NULL,
    -- Subassunto: aponta para o assunto "pai" (um nível só). NULL = assunto de topo.
    parent_id   INTEGER REFERENCES assuntos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    assunto_id  INTEGER NOT NULL REFERENCES assuntos(id) ON DELETE CASCADE,
    data        TEXT    NOT NULL,                       -- AAAA-MM-DD
    acertos     INTEGER NOT NULL CHECK (acertos >= 0),
    total       INTEGER NOT NULL CHECK (total > 0 AND acertos <= total),
    observacao  TEXT
);

-- Assunto novo escolhido na tela "Hoje" (usado para saber o que foi estudado ontem)
CREATE TABLE IF NOT EXISTS estudo_do_dia (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    assunto_id  INTEGER NOT NULL REFERENCES assuntos(id) ON DELETE CASCADE,
    data        TEXT    NOT NULL,
    UNIQUE (usuario_id, assunto_id, data)
);

CREATE INDEX IF NOT EXISTS ix_materias_usuario ON materias(usuario_id);
CREATE INDEX IF NOT EXISTS ix_assuntos_usuario ON assuntos(usuario_id);
CREATE INDEX IF NOT EXISTS ix_sessoes_usuario  ON sessoes(usuario_id, assunto_id, data);
"""


def conectar(caminho: str) -> sqlite3.Connection:
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db() -> sqlite3.Connection:
    """Uma conexão por requisição, guardada em flask.g."""
    if "db" not in g:
        g.db = conectar(current_app.config["DATABASE"])
    return g.db


def fechar_db(_erro=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def iniciar_db(caminho: str):
    con = conectar(caminho)
    con.executescript(ESQUEMA)
    # Migração: bancos criados antes dos subassuntos não têm a coluna parent_id.
    colunas = [r["name"] for r in con.execute("PRAGMA table_info(assuntos)")]
    if "parent_id" not in colunas:
        con.execute("ALTER TABLE assuntos ADD COLUMN parent_id INTEGER REFERENCES assuntos(id) ON DELETE CASCADE")
    con.execute("CREATE INDEX IF NOT EXISTS ix_assuntos_pai ON assuntos(parent_id)")
    # Migração: dias de estudo por seção
    if "dias_estudo" not in [r["name"] for r in con.execute("PRAGMA table_info(materias)")]:
        con.execute("ALTER TABLE materias ADD COLUMN dias_estudo TEXT NOT NULL DEFAULT ''")
    # Migração: ritmo de estudo
    colunas = [r["name"] for r in con.execute("PRAGMA table_info(configuracoes)")]
    if "ritmo" not in colunas:
        con.execute("ALTER TABLE configuracoes ADD COLUMN ritmo TEXT NOT NULL DEFAULT 'leve'")
    if "aprendizado" not in colunas:
        con.execute("ALTER TABLE configuracoes ADD COLUMN aprendizado TEXT NOT NULL DEFAULT 'padrao'")
    if "distribuicao" not in colunas:
        con.execute("ALTER TABLE configuracoes ADD COLUMN distribuicao TEXT NOT NULL DEFAULT 'todas'")
        # quem já tinha marcado dias numa seção continua usando os dias
        con.execute("""UPDATE configuracoes SET distribuicao = 'dias' WHERE usuario_id IN
                       (SELECT usuario_id FROM materias WHERE dias_estudo != '')""")
    if "adiantar" not in colunas:
        con.execute("ALTER TABLE configuracoes ADD COLUMN adiantar INTEGER NOT NULL DEFAULT 1")
    if "teto_dias" not in colunas:
        con.execute("ALTER TABLE configuracoes ADD COLUMN teto_dias INTEGER NOT NULL DEFAULT 45")
    con.commit()
    con.close()


def init_app(app):
    iniciar_db(app.config["DATABASE"])
    app.teardown_appcontext(fechar_db)
