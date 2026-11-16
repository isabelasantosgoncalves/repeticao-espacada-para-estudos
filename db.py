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
    questoes_fixas  INTEGER NOT NULL DEFAULT 10
);

CREATE TABLE IF NOT EXISTS materias (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nome        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS assuntos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    materia_id  INTEGER NOT NULL REFERENCES materias(id) ON DELETE CASCADE,
    nome        TEXT    NOT NULL
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
    con.commit()
    con.close()


def init_app(app):
    iniciar_db(app.config["DATABASE"])
    app.teardown_appcontext(fechar_db)
