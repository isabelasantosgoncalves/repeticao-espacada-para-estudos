"""
Dados de exemplo para a conta demo (demo@demo.com / demo123).

As sessões são geradas simulando um estudante que segue o próprio algoritmo:
cada assunto começa em uma data, melhora aos poucos e volta na data de revisão
sugerida (às vezes com alguns dias de atraso). Usa uma semente fixa, então o
resultado é sempre parecido.
"""

import random
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

import logica as L

DEMO = ("Estudante Demo", "demo@demo.com", "demo123")

# matéria -> [(assunto, dias atrás do início ou None = nunca estudado, nível inicial, ganho por sessão)]
CURRICULO = {
    "Matemática": [
        ("Funções do 1º grau", 70, 0.55, 0.12),
        ("Porcentagem", 52, 0.70, 0.08),
        ("Geometria plana", 30, 0.35, 0.10),
        ("Probabilidade", 1, 0.45, 0.10),
        ("Logaritmos", None, 0, 0),
    ],
    "Português": [
        ("Crase", 60, 0.40, 0.15),
        ("Concordância verbal", 40, 0.60, 0.07),
        ("Interpretação de texto", 85, 0.75, 0.06),
        ("Regência", None, 0, 0),
    ],
    "Biologia": [
        ("Citologia", 45, 0.50, 0.10),
        ("Genética", 21, 0.30, 0.12),
        ("Ecologia", None, 0, 0),
    ],
    "História": [
        ("Brasil Colônia", 75, 0.65, 0.09),
        ("Era Vargas", 26, 0.45, 0.06),
        ("Revolução Industrial", None, 0, 0),
    ],
}

OBSERVACOES = [
    None, None, None,
    "Errei por falta de atenção no enunciado.",
    "Revisar a teoria antes da próxima.",
    "Questões da banca mais difíceis.",
    "Fiz com tempo cronometrado.",
    "Melhorou bastante depois do resumo.",
]


def simular(inicio: date, hoje: date, nivel: float, ganho: float, rnd: random.Random):
    """Gera sessões (data, acertos, total) seguindo as datas que o algoritmo sugere."""
    sessoes = []
    d = inicio
    while d < hoje:
        pcts = [L.percentual(a, t) for _, a, t in sessoes]
        totais = [t for _, _, t in sessoes]
        total = L.questoes_sugeridas(L.dominio(pcts, totais)) if pcts else 20
        chance = min(0.98, max(0.1, nivel + rnd.uniform(-0.12, 0.08)))
        acertos = sum(1 for _ in range(total) if rnd.random() < chance)
        sessoes.append((d, acertos, total))
        nivel = min(0.97, nivel + ganho * rnd.uniform(0.5, 1.2))
        intervalo, _ = L.calcular_intervalo(pcts + [acertos / total], totais + [total])
        # às vezes o estudante atrasa a revisão
        atraso = rnd.choice([0, 0, 0, 1, 2, 5, 9])
        d = d + timedelta(days=intervalo + atraso)
    return sessoes


def criar_demo(con, hoje: date) -> int:
    """Apaga e recria a conta demo. Devolve o número de sessões criadas."""
    nome, email, senha = DEMO
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("DELETE FROM usuarios WHERE email = ?", (email,))
    uid = con.execute(
        "INSERT INTO usuarios (nome, email, senha_hash, onboarding_ok) VALUES (?, ?, ?, 1)",
        (nome, email, generate_password_hash(senha))).lastrowid
    con.execute(
        """INSERT INTO configuracoes (usuario_id, modo, dias_fixos, revisao_minima, questoes_modo, questoes_fixas)
           VALUES (?, 'ambos', '6', 3, 'auto', 10)""", (uid,))

    rnd = random.Random(2026)
    n = 0
    for materia, assuntos in CURRICULO.items():
        mid = con.execute("INSERT INTO materias (usuario_id, nome) VALUES (?, ?)", (uid, materia)).lastrowid
        for assunto, dias_atras, nivel, ganho in assuntos:
            aid = con.execute("INSERT INTO assuntos (usuario_id, materia_id, nome) VALUES (?, ?, ?)",
                              (uid, mid, assunto)).lastrowid
            if dias_atras is None:
                continue
            inicio = hoje - timedelta(days=dias_atras)
            if dias_atras == 1:
                con.execute("INSERT INTO estudo_do_dia (usuario_id, assunto_id, data) VALUES (?, ?, ?)",
                            (uid, aid, inicio.isoformat()))
            for d, acertos, total in simular(inicio, hoje, nivel, ganho, rnd):
                con.execute(
                    """INSERT INTO sessoes (usuario_id, assunto_id, data, acertos, total, observacao)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (uid, aid, d.isoformat(), acertos, total, rnd.choice(OBSERVACOES)))
                n += 1
    con.commit()
    return n
